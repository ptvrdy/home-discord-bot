import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord
from discord import app_commands
from discord.ext import commands

from config.discord_tags import DISCORD_TAGS
from models.recipe_card import Recipe as RecipeData
from services.database import (
    add_cooking_log,
    get_cooking_log_entries,
    get_journal_message_id,
    get_random_recipe,
    get_recipe_by_thread,
    get_recipe_by_url,
    save_recipe,
    set_journal_message_id,
    update_recipe_status,
)
from services.embed import create_recipe_embed
from services.forum import (
    HUMAN_TAGS,
    create_recipe_post,
    keep_single_human_tag,
    tags_with_human_status,
)
from services.journal import build_journal_embed
from services.recipe_tags import generate_recipe_tags
from services.scraper import scrape_recipe
from services.time_parser import parse_minutes


RECIPE_STATUS_CHOICES = [
    app_commands.Choice(name="📝 Needs Review", value="needs_review"),
    app_commands.Choice(name="✅ Made Before", value="made_before"),
    app_commands.Choice(name="🔁 Make Again", value="make_again"),
    app_commands.Choice(name="⭐ Favorite", value="favorite"),
]

RECIPE_TAG_CHOICES = [
    app_commands.Choice(name=tag_info["discord_name"], value=tag_key)
    for tag_key, tag_info in DISCORD_TAGS.items()
    if tag_key not in HUMAN_TAGS
]


class RecipeReviewModal(discord.ui.Modal):
    def __init__(
        self,
        thread: discord.Thread,
        status_key: str,
        made_recipe: bool,
    ):
        super().__init__(title="Add to Recipe Journal")
        self.thread = thread
        self.status_key = status_key
        self.made_recipe = made_recipe

        self.rating = discord.ui.TextInput(
            label="⭐ Rating (1-5)",
            placeholder="1-5",
            max_length=1,
        )
        self.notes = discord.ui.TextInput(
            label="Changes, substitutions, or feedback",
            placeholder="Example: Used chicken sausage and loved it.",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=1000,
        )
        self.next_time = discord.ui.TextInput(
            label="What would you change next time?",
            placeholder="Optional",
            required=False,
            max_length=500,
        )
        self.add_item(self.rating)
        self.add_item(self.notes)
        self.add_item(self.next_time)

    async def on_submit(self, interaction: discord.Interaction):
        rating_text = self.rating.value.strip()
        if rating_text not in {"1", "2", "3", "4", "5"}:
            await interaction.response.send_message(
                "❌ Rating needs to be a number from 1 to 5.",
                ephemeral=True,
            )
            return

        # Acknowledge privately: this modal was opened from a slash command, not
        # from a button on an existing message, so there's nothing to "update" -
        # the journal message itself is posted/edited directly via self.thread below.
        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            parent = self.thread.parent
            if not isinstance(parent, discord.ForumChannel):
                raise ValueError("This recipe is no longer in a forum channel.")

            updated_tags = tags_with_human_status(
                parent,
                self.thread.applied_tags,
                self.status_key,
            )
            await self.thread.edit(applied_tags=updated_tags)

            timezone_name = os.getenv("HOUSEHOLD_TIMEZONE", "America/New_York")
            try:
                timezone = ZoneInfo(timezone_name)
            except ZoneInfoNotFoundError:
                # Windows has no built-in IANA timezone database (the `tzdata`
                # package provides it); fall back to the system's local offset
                # rather than retrying the same lookup that just failed.
                timezone = datetime.now().astimezone().tzinfo
            made_at = datetime.now(timezone)
            activity = "Made" if self.made_recipe else "Reviewed"

            try:
                add_cooking_log(
                    self.thread.id,
                    made_at,
                    activity,
                    self.status_key,
                    self.notes.value or None,
                    self.next_time.value or None,
                    int(rating_text),
                    interaction.user.display_name,
                )
            except sqlite3.Error as error:
                await interaction.followup.send(
                    f"⚠️ Recipe status was updated, but I couldn't save the journal entry: {error}",
                    ephemeral=True,
                )
                return

            await self._sync_journal_message()
            await interaction.followup.send("✅ Review saved!", ephemeral=True)
        except (ValueError, discord.HTTPException) as error:
            await interaction.followup.send(
                f"❌ I couldn't update this recipe journal: {error}",
                ephemeral=True,
            )

    async def _sync_journal_message(self):
        """Rebuild the recipe's single journal message from its full cooking-log history."""
        entries = get_cooking_log_entries(self.thread.id)
        embed = build_journal_embed(entries)

        journal_message_id = get_journal_message_id(self.thread.id)
        if journal_message_id:
            try:
                message = await self.thread.fetch_message(journal_message_id)
                await message.edit(embed=embed)
                return
            except discord.NotFound:
                pass  # the message was deleted; fall through and repost it

        message = await self.thread.send(embed=embed)
        set_journal_message_id(self.thread.id, message.id)


class ManualRecipeTimingModal(discord.ui.Modal, title="Add a Recipe · Timing & Servings"):
    prep_time = discord.ui.TextInput(
        label="Prep Time",
        placeholder="e.g. 10 minutes (optional)",
        required=False,
        max_length=50,
    )
    cook_time = discord.ui.TextInput(
        label="Cook Time",
        placeholder="e.g. 15 minutes (optional)",
        required=False,
        max_length=50,
    )
    total_time = discord.ui.TextInput(
        label="Total Time",
        placeholder="e.g. 25 minutes (optional)",
        required=False,
        max_length=50,
    )
    yields = discord.ui.TextInput(
        label="Servings",
        placeholder="e.g. 4 servings (optional)",
        required=False,
        max_length=50,
    )

    def __init__(self, cog: "Recipe", partial_recipe: dict):
        super().__init__()
        self.cog = cog
        self.partial_recipe = partial_recipe

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()

        prep_time = self.prep_time.value.strip() or None
        cook_time = self.cook_time.value.strip() or None
        total_time = self.total_time.value.strip() or None

        recipe = RecipeData(
            **self.partial_recipe,
            prep_time=prep_time,
            cook_time=cook_time,
            total_time=total_time,
            total_minutes=parse_minutes(total_time) or parse_minutes(cook_time),
            yields=self.yields.value.strip() or None,
        )
        recipe.tags = generate_recipe_tags(recipe)

        await self.cog.publish_recipe(interaction, recipe)


class ManualRecipeModal(discord.ui.Modal, title="Add a Recipe · Details"):
    recipe_name = discord.ui.TextInput(
        label="Recipe Name",
        max_length=100,
    )
    ingredients = discord.ui.TextInput(
        label="Ingredients (one per line)",
        style=discord.TextStyle.paragraph,
        max_length=2000,
    )
    instructions = discord.ui.TextInput(
        label="Instructions",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=2000,
    )
    image_url = discord.ui.TextInput(
        label="Image URL",
        placeholder="https://... (optional)",
        required=False,
        max_length=300,
    )
    video_url = discord.ui.TextInput(
        label="Video URL",
        placeholder="https://www.tiktok.com/...",
        max_length=300,
    )

    def __init__(self, cog: "Recipe", prefill_url: str | None = None):
        super().__init__()
        self.cog = cog
        if prefill_url:
            self.video_url.default = prefill_url

    async def on_submit(self, interaction: discord.Interaction):
        url = self.video_url.value.strip()
        if not url.startswith(("http://", "https://")):
            await interaction.response.send_message(
                "❌ Video URL needs to start with http:// or https://",
                ephemeral=True,
            )
            return

        partial_recipe = dict(
            title=self.recipe_name.value.strip(),
            ingredients=[
                line.strip()
                for line in self.ingredients.value.splitlines()
                if line.strip()
            ],
            instructions=self.instructions.value.strip() or None,
            image_url=self.image_url.value.strip() or None,
            source_url=url,
            source_name="TikTok" if "tiktok.com" in url.lower() else None,
        )

        # Discord won't let a modal submission respond with another modal directly
        # (only slash commands and button/component clicks can open one), so we
        # bridge with a button click here to continue to the timing modal.
        await interaction.response.send_message(
            "Got it! Click below to add timing and servings.",
            view=ContinueToTimingView(self.cog, partial_recipe),
            ephemeral=True,
        )


class ContinueToTimingView(discord.ui.View):
    def __init__(self, cog: "Recipe", partial_recipe: dict):
        super().__init__(timeout=300)
        self.cog = cog
        self.partial_recipe = partial_recipe

    @discord.ui.button(label="Add Timing & Servings", style=discord.ButtonStyle.primary)
    async def continue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            ManualRecipeTimingModal(self.cog, self.partial_recipe)
        )
        self.stop()


class FixRecipeModal(discord.ui.Modal, title="Fix Recipe Details"):
    def __init__(self, cog: "Recipe", thread: discord.Thread, current: dict):
        super().__init__()
        self.cog = cog
        self.thread = thread
        self.current = current

        self.recipe_name = discord.ui.TextInput(label="Recipe Name", max_length=100)
        self.recipe_name.default = current["title"]

        self.prep_time = discord.ui.TextInput(label="Prep Time", required=False, max_length=50)
        self.prep_time.default = current.get("prep_time") or ""

        self.cook_time = discord.ui.TextInput(label="Cook Time", required=False, max_length=50)
        self.cook_time.default = current.get("cook_time") or ""

        self.total_time = discord.ui.TextInput(label="Total Time", required=False, max_length=50)
        self.total_time.default = current.get("total_time") or ""

        self.yields = discord.ui.TextInput(label="Servings", required=False, max_length=50)
        self.yields.default = current.get("yields") or ""

        for item in (self.recipe_name, self.prep_time, self.cook_time, self.total_time, self.yields):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        title = self.recipe_name.value.strip() or self.current["title"]
        prep_time = self.prep_time.value.strip() or None
        cook_time = self.cook_time.value.strip() or None
        total_time = self.total_time.value.strip() or None
        yields = self.yields.value.strip() or None

        recipe = RecipeData(
            title=title,
            ingredients=self.current["ingredients"],
            instructions=self.current["instructions"],
            prep_time=prep_time,
            cook_time=cook_time,
            total_time=total_time,
            total_minutes=parse_minutes(total_time) or parse_minutes(cook_time),
            yields=yields,
            image_url=self.current["image_url"],
            source_url=self.current["source_url"],
            source_name=self.current["source_name"],
        )
        recipe.tags = generate_recipe_tags(recipe)

        try:
            save_recipe(recipe, self.thread.id)

            if title != self.current["title"]:
                await self.thread.edit(name=title[:100])

            starter_message = await self.thread.fetch_message(self.thread.id)
            await starter_message.edit(embed=create_recipe_embed(recipe))

            await interaction.followup.send("✅ Recipe updated!", ephemeral=True)
        except (discord.HTTPException, sqlite3.Error) as error:
            await interaction.followup.send(
                f"❌ I couldn't update this recipe: {error}",
                ephemeral=True,
            )


class Recipe(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        recipe_forum_id = os.getenv("RECIPE_FORUM_ID")
        self.recipe_forum_id = int(recipe_forum_id) if recipe_forum_id else None

    async def publish_recipe(self, interaction: discord.Interaction, recipe: RecipeData):
        """Post a recipe to the forum and save it, regardless of where it came from."""
        guild = interaction.guild
        if guild is None:
            await interaction.followup.send(
                "❌ This command can only be used in a server."
            )
            return

        if self.recipe_forum_id is None:
            await interaction.followup.send(
                "❌ Recipe forum is not configured."
            )
            return

        channel = guild.get_channel(self.recipe_forum_id)

        if not isinstance(channel, discord.ForumChannel):
            await interaction.followup.send(
                "❌ Recipe channel is not a forum channel."
            )
            return

        thread = await create_recipe_post(channel, recipe)
        save_recipe(recipe, thread.id)

        await interaction.followup.send("✅ Recipe added!")

    @commands.Cog.listener()
    async def on_thread_update(self, before: discord.Thread, after: discord.Thread):
        if self.recipe_forum_id is None or after.parent_id != self.recipe_forum_id:
            return

        filtered_tags = keep_single_human_tag(after.applied_tags)
        if len(filtered_tags) != len(after.applied_tags):
            await after.edit(applied_tags=filtered_tags)

        status_names = {
            tag_info["discord_name"]: tag_key
            for tag_key, tag_info in DISCORD_TAGS.items()
            if tag_key in {"needs_review", "made_before", "make_again", "favorite"}
        }
        status = next(
            (status_names[tag.name] for tag in filtered_tags if tag.name in status_names),
            None,
        )
        if status:
            update_recipe_status(after.id, status)

    @app_commands.command(
        name="review",
        description="Add a dated note and status to a recipe thread",
    )
    @app_commands.describe(
        status="The recipe's current family status",
        made_recipe="Choose No if you are reviewing it without making it today",
    )
    @app_commands.choices(status=RECIPE_STATUS_CHOICES)
    async def review(
        self,
        interaction: discord.Interaction,
        status: app_commands.Choice[str],
        made_recipe: bool = True,
    ):
        channel = interaction.channel
        if (
            self.recipe_forum_id is None
            or not isinstance(channel, discord.Thread)
            or channel.parent_id != self.recipe_forum_id
        ):
            await interaction.response.send_message(
                "❌ Use this command inside a recipe thread.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(
            RecipeReviewModal(channel, status.value, made_recipe)
        )


    @app_commands.command(
        name="recipe",
        description="Import a recipe from a URL"
    )
    async def recipe(
        self,
        interaction: discord.Interaction,
        url: str
    ):
        existing = get_recipe_by_url(url)
        if existing:
            await interaction.response.send_message(
                f"📖 That recipe's already in the box: **{existing['title']}**\n"
                f"<#{existing['discord_thread_id']}>",
                ephemeral=True,
            )
            return

        if "tiktok.com" in url.lower():
            await interaction.response.send_modal(ManualRecipeModal(self, prefill_url=url))
            return

        await interaction.response.defer()

        try:
            recipe = scrape_recipe(url)
        except Exception as e:
            print(type(e))
            print(e)

            await interaction.followup.send(
                "❌ I couldn't import that recipe. "
                "The website may be blocking automated imports."
            )
            return

        await self.publish_recipe(interaction, recipe)

    @app_commands.command(
        name="random",
        description="Get a random recipe suggestion",
    )
    @app_commands.describe(tag="Optional: only suggest recipes with this tag")
    @app_commands.choices(tag=RECIPE_TAG_CHOICES)
    async def random_recipe(
        self,
        interaction: discord.Interaction,
        tag: app_commands.Choice[str] | None = None,
    ):
        recipe = get_random_recipe(tag.value if tag else None)

        if recipe is None:
            message = (
                f"🎲 No recipes tagged {tag.name} yet!"
                if tag
                else "🎲 No recipes saved yet — import one with /recipe!"
            )
            await interaction.response.send_message(message, ephemeral=True)
            return

        await interaction.response.send_message(
            f"🎲 How about **{recipe['title']}**?\n<#{recipe['discord_thread_id']}>"
        )

    @app_commands.command(
        name="fix",
        description="Correct this recipe's name, times, or servings (run inside its thread)",
    )
    async def fix(self, interaction: discord.Interaction):
        channel = interaction.channel
        if (
            self.recipe_forum_id is None
            or not isinstance(channel, discord.Thread)
            or channel.parent_id != self.recipe_forum_id
        ):
            await interaction.response.send_message(
                "❌ Use this command inside a recipe thread.",
                ephemeral=True,
            )
            return

        current = get_recipe_by_thread(channel.id)
        if current is None:
            await interaction.response.send_message(
                "❌ This recipe isn't in the database yet.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(FixRecipeModal(self, channel, current))


async def setup(bot):
    await bot.add_cog(Recipe(bot))
