"""/check_recipes: compare the recipe forum with the database, and re-import
any posts the database is missing.

A post and its database row are written separately, so a failure in between
(see publish_recipe) can leave a post that /find_ingredient, /random,
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

from services.database import get_all_recipes, save_recipe
from services.forum import HUMAN_TAGS
from services.pantry_embed import chunk_lines
from services.recipe_sync import find_mismatches, recipe_from_post
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
        starter.embeds[0].to_dict(), instructions_text, [tag.name for tag in thread.applied_tags]
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


class ReimportView(discord.ui.View):
    def __init__(self, thread_ids: list[int]):
        super().__init__(timeout=900)
        self.add_item(ReimportButton(thread_ids))


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

        if not missing_in_db and not missing_in_forum:
            await interaction.followup.send(
                f"✅ All {len(threads)} recipe posts match the database.", ephemeral=True
            )
            return

        lines = [f"📋 {len(threads)} posts in the forum, {len(rows)} recipes in the database."]
        if missing_in_db:
            lines.append(f"\n**Posts the database is missing ({len(missing_in_db)})** — invisible to search, /random, /review:")
            lines += [f"• <#{thread_id}>" for thread_id, _ in missing_in_db]
        if missing_in_forum:
            lines.append(
                f"\n**In the database but the post is gone ({len(missing_in_forum)})** — "
                "probably deleted on purpose; left as they are:"
            )
            lines += [f"• {row['title']}" for row in missing_in_forum]

        chunks = chunk_lines(lines)
        view = ReimportView([thread_id for thread_id, _ in missing_in_db]) if missing_in_db else None
        for index, chunk in enumerate(chunks):
            if view and index == len(chunks) - 1:
                await interaction.followup.send(chunk, view=view, ephemeral=True)
            else:
                await interaction.followup.send(chunk, ephemeral=True)


async def setup(bot):
    await bot.add_cog(RecipeSync(bot))
