"""/check_recipes: compare the recipe forum with the database, and re-import
any posts the database is missing.

A post and its database row are written separately, so a failure in between
(see publish_recipe) can leave a post that /find_ingredient, /suggest_recipe,
/what_can_i_make, and /review can't see. This finds those - and database
rows whose post was deleted - and repairs the first kind: re-scraping the
original link when there is one, otherwise rebuilding from the post itself.
"""

import asyncio
import logging
import os

import discord
from discord import app_commands
from discord.ext import commands

from services.backup import backup_database
from services.database import (
    delete_recipe_by_thread,
    get_all_recipes,
    get_journaled_recipes,
    get_recipe_by_thread,
    get_recipe_sources,
    get_recipe_tags,
    save_recipe,
    update_recipe_source,
)
from commands.recipe_commands import sync_journal_message
from services.embed import create_recipe_embed
from services.forum import HUMAN_TAGS, forum_tag_label
from services.pantry_embed import chunk_lines
from services.recipe_sources import SourceFix, plan_source_fix, unlabelled_sites
from services.recipe_sync import find_mismatches, recipe_from_post, recipe_from_row
from services.recipe_tags import generate_recipe_tags
from services.scraper import scrape_recipe

logger = logging.getLogger(__name__)

REIMPORT_BATCH = 25  # per click, so one click can't run for many minutes
INSTRUCTIONS_TITLE = "📖 Instructions"


async def forum_threads(forum: discord.ForumChannel) -> dict[int, discord.Thread]:
    """Every post in the forum - open and archived (Discord archives quiet
    threads, and forum.threads only lists the open ones)."""
    threads = {thread.id: thread for thread in forum.threads}
    async for thread in forum.archived_threads(limit=None):
        threads[thread.id] = thread
    return threads


async def reimport_thread(thread: discord.Thread) -> str:
    """Save one post's recipe to the database. Returns a line for the report."""
    try:
        starter = await thread.fetch_message(thread.id)
    except discord.HTTPException:
        return f"• <#{thread.id}> — ❌ couldn't read the post's first message"
    if not starter.embeds:
        return f"• <#{thread.id}> — ❌ the post has no recipe card to read"

    instructions_text = None
    async for message in thread.history(limit=10, oldest_first=True):
        embed = next((embed for embed in message.embeds if embed.title == INSTRUCTIONS_TITLE), None)
        if embed:
            instructions_text = embed.description
            break

    recipe, complete = recipe_from_post(
        starter.embeds[0].to_dict(), instructions_text, [forum_tag_label(tag) for tag in thread.applied_tags]
    )
    how = "rebuilt from the post"
    if recipe.source_url:
        try:
            scraped = await asyncio.to_thread(scrape_recipe, recipe.source_url)
        except Exception as error:  # the site may block scrapers now; the post is still a fine source
            logger.info("Re-scrape of %s failed, using the post instead: %s", recipe.source_url, error)
        else:
            human = next((tag for tag in recipe.tags if tag in HUMAN_TAGS), "needs_review")
            fresh = [tag for tag in generate_recipe_tags(scraped) if tag not in HUMAN_TAGS]
            kept = [tag for tag in recipe.tags if tag not in HUMAN_TAGS]
            scraped.title = recipe.title  # keep any rename made with /fix
            scraped.image_url = recipe.image_url or scraped.image_url
            scraped.tags = [human] + sorted(set(fresh) | set(kept))
            recipe, complete, how = scraped, True, "re-imported from the original link"

    try:
        save_recipe(recipe, thread.id)
    except Exception as error:
        logger.exception("Couldn't save recipe for thread %s", thread.id)
        return f"• <#{thread.id}> — ❌ couldn't save: {error}"
    note = "" if complete else " ⚠️ the post had cut some ingredients or steps short, so check it with /fix"
    return f"• <#{thread.id}> — ✅ {how}{note}"


FIX_SOURCES_BATCH = 25  # per run, so one run can't go on for many minutes


async def edit_card(thread: discord.Thread, embed: discord.Embed) -> bool:
    """Replace a post's recipe card. An archived post is reopened first (Discord
    doesn't reliably allow edits inside one) and put back afterwards, even if
    the edit fails. Returns whether it had to be reopened."""
    reopened = thread.archived
    if reopened:
        await thread.edit(archived=False)
    try:
        starter = await thread.fetch_message(thread.id)
        await starter.edit(embed=embed)
    finally:
        if reopened:
            await thread.edit(archived=True)
    return reopened


async def apply_source_fix(thread: discord.Thread, row: dict, fix: SourceFix) -> str:
    """Re-render one post's card with the corrected source, then save it to the
    database. Card FIRST: if the edit fails the database is left alone, so the
    next run retries it instead of finding it "already fixed" and leaving the
    card stale. Returns a line for the report."""
    current = get_recipe_by_thread(thread.id)
    recipe = recipe_from_row(
        {**current, "source_name": fix.source_name, "source_url": fix.source_url},
        get_recipe_tags(thread.id),
    )
    embed = await asyncio.to_thread(create_recipe_embed, recipe)  # may probe a linked image's size
    reopened = await edit_card(thread, embed)
    update_recipe_source(thread.id, fix.source_name, fix.source_url)

    notes = []
    if fix.source_url != (row["source_url"] or ""):
        notes.append("link restored")
    if reopened:
        notes.append("post was archived - reopened, then archived again")
    suffix = f" ({'; '.join(notes)})" if notes else ""
    return f"• <#{thread.id}> — now says **{fix.source_name or 'the original recipe'}**{suffix}"


class ReimportButton(discord.ui.Button):
    def __init__(self, thread_ids: list[int]):
        count = min(len(thread_ids), REIMPORT_BATCH)
        super().__init__(label=f"🔧 Re-import {count} missing", style=discord.ButtonStyle.primary)
        self.thread_ids = thread_ids

    async def callback(self, interaction: discord.Interaction):
        if getattr(self.view, "claimed", False):
            await interaction.response.send_message("⏳ Already on it.", ephemeral=True)
            return
        self.view.claimed = True
        await interaction.response.defer()

        lines = []
        for thread_id in self.thread_ids[:REIMPORT_BATCH]:
            thread = interaction.client.get_channel(thread_id)
            if thread is None:
                try:
                    thread = await interaction.client.fetch_channel(thread_id)
                except discord.HTTPException:
                    lines.append(f"• {thread_id} — ❌ the post can't be found anymore")
                    continue
            lines.append(await reimport_thread(thread))
        remaining = len(self.thread_ids) - REIMPORT_BATCH
        if remaining > 0:
            lines.append(f"_{remaining} more — run /check_recipes again for the rest._")

        chunks = chunk_lines(["🔧 Re-imported:"] + lines)
        await interaction.edit_original_response(content=chunks[0], view=None)
        for chunk in chunks[1:]:
            await interaction.followup.send(chunk, ephemeral=True)


async def post_is_gone(client: discord.Client, thread_id: int) -> bool:
    """True only when Discord positively says the post doesn't exist. Any other
    failure (a hiccup, a permission problem) is NOT proof - and forgetting is
    permanent - so it counts as "not gone"."""
    try:
        await client.fetch_channel(thread_id)
    except discord.NotFound:
        return True
    except discord.HTTPException:
        return False
    return False


class ForgetButton(discord.ui.Button):
    """Delete database recipes whose forum post was deleted. Backs the
    database up first, and re-checks each post is really gone."""

    def __init__(self, rows: list[dict]):
        super().__init__(label=f"🗑️ Forget {len(rows)} deleted", style=discord.ButtonStyle.danger)
        self.rows = rows

    async def callback(self, interaction: discord.Interaction):
        if getattr(self.view, "forget_claimed", False):
            await interaction.response.send_message("⏳ Already on it.", ephemeral=True)
            return
        self.view.forget_claimed = True
        await interaction.response.defer()

        try:
            backup_path = await asyncio.to_thread(backup_database)
        except Exception as error:
            logger.exception("Backup before forgetting recipes failed")
            await interaction.edit_original_response(
                content=f"❌ I couldn't back up the database first ({error}), so nothing was deleted.", view=None
            )
            return

        lines = [f"🗑️ Forgot (backup saved as `{backup_path.name}`):"]
        for row in self.rows:
            if not await post_is_gone(interaction.client, row["discord_thread_id"]):
                lines.append(f"• {row['title']} — skipped, its post may still exist")
            elif delete_recipe_by_thread(row["discord_thread_id"]):
                lines.append(f"• {row['title']} — forgotten")
            else:
                lines.append(f"• {row['title']} — already gone from the database")
        chunks = chunk_lines(lines)
        await interaction.edit_original_response(content=chunks[0], view=None)
        for chunk in chunks[1:]:
            await interaction.followup.send(chunk, ephemeral=True)


REBUILD_JOURNALS_BATCH = 25


async def journal_is_missing(thread: discord.Thread, journal_message_id: int | None) -> bool:
    """True when a recipe has reviews but its journal message isn't in the post:
    never posted, or deleted. A failed lookup (anything but "not found") is not
    proof, so it counts as present."""
    if not journal_message_id:
        return True
    try:
        await thread.fetch_message(journal_message_id)
    except discord.NotFound:
        return True
    except discord.HTTPException:
        return False
    return False


async def find_missing_journals(threads: dict[int, discord.Thread]) -> list[dict]:
    """Journaled recipes (see get_journaled_recipes) whose journal message is
    missing from their post. A recipe whose post is gone is skipped - that's
    reported separately."""
    rows = [row for row in get_journaled_recipes() if row["discord_thread_id"] in threads]
    limit = asyncio.Semaphore(5)

    async def check(row):
        async with limit:
            return await journal_is_missing(threads[row["discord_thread_id"]], row["journal_message_id"])

    results = await asyncio.gather(*(check(row) for row in rows))
    return [row for row, missing in zip(rows, results) if missing]


async def restore_journal(thread: discord.Thread, title: str) -> str:
    """Re-post one recipe's journal. An archived post is reopened first and put
    back after, even on failure. Returns a line for the report."""
    reopened = thread.archived
    try:
        if reopened:
            await thread.edit(archived=False)
        try:
            await sync_journal_message(thread)
        finally:
            if reopened:
                await thread.edit(archived=True)
    except Exception as error:
        logger.exception("Couldn't rebuild the journal for %r", title)
        return f"• <#{thread.id}> — ❌ couldn't rebuild ({error})"
    return f"• <#{thread.id}> — ✅ journal restored"


class RebuildJournalsButton(discord.ui.Button):
    def __init__(self, rows: list[dict]):
        count = min(len(rows), REBUILD_JOURNALS_BATCH)
        super().__init__(label=f"📓 Rebuild {count} journal{'s' if count != 1 else ''}", style=discord.ButtonStyle.primary)
        self.rows = rows

    async def callback(self, interaction: discord.Interaction):
        if getattr(self.view, "rebuild_claimed", False):
            await interaction.response.send_message("⏳ Already on it.", ephemeral=True)
            return
        self.view.rebuild_claimed = True
        await interaction.response.defer()

        lines = ["📓 Journals rebuilt from the saved reviews:"]
        for row in self.rows[:REBUILD_JOURNALS_BATCH]:
            thread = interaction.client.get_channel(row["discord_thread_id"])
            if thread is None:
                try:
                    thread = await interaction.client.fetch_channel(row["discord_thread_id"])
                except discord.HTTPException:
                    lines.append(f"• {row['title']} — ❌ the post can't be found anymore")
                    continue
            lines.append(await restore_journal(thread, row["title"]))
        remaining = len(self.rows) - REBUILD_JOURNALS_BATCH
        if remaining > 0:
            lines.append(f"_{remaining} more — run /check_recipes again for the rest._")
        chunks = chunk_lines(lines)
        await interaction.edit_original_response(content=chunks[0], view=None)
        for chunk in chunks[1:]:
            await interaction.followup.send(chunk, ephemeral=True)


class ReimportView(discord.ui.View):
    """The /check_recipes buttons: re-import posts the database is missing,
    restore deleted review journals, and/or forget recipes whose post is gone."""

    def __init__(
        self,
        thread_ids: list[int],
        forgettable: list[dict] | None = None,
        missing_journals: list[dict] | None = None,
    ):
        super().__init__(timeout=900)
        if thread_ids:
            self.add_item(ReimportButton(thread_ids))
        if missing_journals:
            self.add_item(RebuildJournalsButton(missing_journals))
        if forgettable:
            self.add_item(ForgetButton(forgettable))


class RecipeSync(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        forum_id = os.getenv("RECIPE_FORUM_ID")
        self.recipe_forum_id = int(forum_id) if forum_id else None

    @app_commands.command(
        name="check_recipes",
        description="Compare the recipe forum with Rosie's database and fix posts it's missing",
    )
    async def check_recipes(self, interaction: discord.Interaction):
        forum = self.bot.get_channel(self.recipe_forum_id) if self.recipe_forum_id else None
        if not isinstance(forum, discord.ForumChannel):
            await interaction.response.send_message("❌ The recipe forum isn't configured (`RECIPE_FORUM_ID`).", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)

        threads = await forum_threads(forum)
        rows = get_all_recipes()
        missing_in_db, missing_in_forum = find_mismatches({thread_id: thread.name for thread_id, thread in threads.items()}, rows)

        missing_journals = await find_missing_journals(threads)

        if not missing_in_db and not missing_in_forum and not missing_journals:
            await interaction.followup.send(
                f"✅ All {len(threads)} recipe posts match the database.", ephemeral=True
            )
            return

        lines = [f"📋 {len(threads)} posts in the forum, {len(rows)} recipes in the database."]
        if missing_in_db:
            lines.append(f"\n**Posts the database is missing ({len(missing_in_db)})** — invisible to search, /suggest_recipe, /review:")
            lines += [f"• <#{thread_id}>" for thread_id, _ in missing_in_db]
        if missing_in_forum:
            lines.append(
                f"\n**In the database but the post is gone ({len(missing_in_forum)})** — "
                "probably deleted on purpose. Use the button to forget them (backs up first):"
            )
            lines += [f"• {row['title']}" for row in missing_in_forum]

        if missing_journals:
            lines.append(
                f"\n**Review journals missing from their post ({len(missing_journals)})** — "
                "deleted by accident? The reviews are still saved; the button reposts them:"
            )
            lines += [f"• <#{row['discord_thread_id']}>" for row in missing_journals]

        chunks = chunk_lines(lines)
        view = ReimportView([thread_id for thread_id, _ in missing_in_db], missing_in_forum, missing_journals)
        for index, chunk in enumerate(chunks):
            if view and index == len(chunks) - 1:
                await interaction.followup.send(chunk, view=view, ephemeral=True)
            else:
                await interaction.followup.send(chunk, ephemeral=True)


    @app_commands.command(
        name="fix_sources",
        description="Label recipes by where they came from (e.g. YouTube) and refresh their cards",
    )
    async def fix_sources(self, interaction: discord.Interaction):
        forum = self.bot.get_channel(self.recipe_forum_id) if self.recipe_forum_id else None
        if not isinstance(forum, discord.ForumChannel):
            await interaction.response.send_message("❌ The recipe forum isn't configured (`RECIPE_FORUM_ID`).", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)

        sources = get_recipe_sources()
        plans = [
            (row, fix)
            for row in sources
            if (fix := plan_source_fix(row["source_url"], row["source_name"]))
        ]
        unknown = unlabelled_sites(sources)
        unknown_lines = []
        if unknown:
            unknown_lines = ["\n**Sites Rosie has no name for yet** (tell me which to add):"]
            unknown_lines += [f"• {site} — {', '.join(titles)}" for site, titles in unknown.items()]
        if not plans:
            for chunk in chunk_lines(["✅ Every recipe's source is already labelled."] + unknown_lines):
                await interaction.followup.send(chunk, ephemeral=True)
            return

        threads = await forum_threads(forum)
        lines = [f"🏷️ Updated {min(len(plans), FIX_SOURCES_BATCH)} of {len(plans)} recipes:"]
        for row, fix in plans[:FIX_SOURCES_BATCH]:
            thread = threads.get(row["discord_thread_id"])
            if thread is None:
                lines.append(f"• {row['title']} — ❌ its post wasn't found in the forum")
                continue
            try:
                lines.append(await apply_source_fix(thread, row, fix))
            except Exception as error:
                logger.exception("Couldn't update the source on %r", row["title"])
                lines.append(f"• <#{thread.id}> — ❌ couldn't update the card ({error}); left as it was")

        if len(plans) > FIX_SOURCES_BATCH:
            lines.append(f"\n_{len(plans) - FIX_SOURCES_BATCH} more — run /fix_sources again for the rest._")
        for chunk in chunk_lines(lines + unknown_lines):
            await interaction.followup.send(chunk, ephemeral=True)


async def setup(bot):
    await bot.add_cog(RecipeSync(bot))
