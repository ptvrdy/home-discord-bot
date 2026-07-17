import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord
from discord import app_commands
from discord.ext import commands

from config.discord_tags import DISCORD_TAGS
from models.recipe_card import Recipe as RecipeData
from services.database import add_cooking_log, save_recipe, update_recipe_status
from services.forum import (
    create_recipe_post,
    keep_single_human_tag,
    tags_with_human_status,
)
from services.recipe_tags import generate_recipe_tags
from services.scraper import scrape_recipe
from services.time_parser import parse_minutes


RECIPE_STATUS_CHOICES = [
    app_commands.Choice(name="📝 Needs Review", value="needs_review"),
    app_commands.Choice(name="✅ Made Before", value="made_before"),
    app_commands.Choice(name="🔁 Make Again", value="make_again"),
    app_commands.Choice(name="⭐ Favorite", value="favorite"),
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
        self.add_item(self.notes)
        self.add_item(self.next_time)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=False)

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
                timezone = ZoneInfo("America/New_York")
            made_at = datetime.now(timezone)
            made_on = f"{made_at.strftime('%B')} {made_at.day}, {made_at.year}"
            activity = "Made" if self.made_recipe else "Reviewed"
            status_name = DISCORD_TAGS[self.status_key]["discord_name"]
            journal_entry = (
                "### 🍒 Recipe Journal\n"
                f"**{activity}:** {made_on}\n"
                f"**Status:** {status_name}"
            )
            if self.notes.value:
                journal_entry += f"\n**Notes:** {self.notes.value}"
            if self.next_time.value:
                journal_entry += f"\n**Next time:** {self.next_time.value}"

            journal_message = await interaction.followup.send(journal_entry, wait=True)

            try:
                add_cooking_log(
                    self.thread.id,
                    made_at,
                    activity,
                    self.status_key,
                    self.notes.value,
                    self.next_time.value,
                    journal_message.id,
                )
            except sqlite3.Error as error:
                await interaction.followup.send(
                    f"⚠️ Posted the journal entry, but couldn't save it to the database: {error}",
                    ephemeral=True,
                )
        except (ValueError, discord.HTTPException) as error:
            await interaction.followup.send(
                f"❌ I couldn't update this recipe journal: {error}",
                ephemeral=True,
            )


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

        await interaction.response.send_modal(
            ManualRecipeTimingModal(self.cog, partial_recipe)
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


async def setup(bot):
    await bot.add_cog(Recipe(bot))
