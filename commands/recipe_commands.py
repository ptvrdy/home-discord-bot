import os
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord
from discord import app_commands
from discord.ext import commands

from config.discord_tags import DISCORD_TAGS
from services.database import add_cooking_log, save_recipe, update_recipe_status
from services.forum import (
    create_recipe_post,
    keep_single_human_tag,
    tags_with_human_status,
)
from services.scraper import scrape_recipe


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
            add_cooking_log(
                self.thread.id,
                made_at,
                activity,
                self.status_key,
                self.notes.value,
                self.next_time.value,
                journal_message.id,
            )
        except (ValueError, discord.HTTPException) as error:
            await interaction.followup.send(
                f"❌ I couldn't update this recipe journal: {error}",
                ephemeral=True,
            )


class Recipe(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_thread_update(self, before: discord.Thread, after: discord.Thread):
        recipe_forum_id = os.getenv("RECIPE_FORUM_ID")
        if recipe_forum_id is None or after.parent_id != int(recipe_forum_id):
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
        recipe_forum_id = os.getenv("RECIPE_FORUM_ID")
        channel = interaction.channel
        if (
            recipe_forum_id is None
            or not isinstance(channel, discord.Thread)
            or channel.parent_id != int(recipe_forum_id)
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
        await interaction.response.defer()

        try:
            recipe = scrape_recipe(url)

            guild = interaction.guild

            if guild is None:
                await interaction.followup.send(
                    "❌ This command can only be used in a server."
                )
                return

            forum_id = int(os.environ["RECIPE_FORUM_ID"])
            # TODO add config to import settings for each channel ID so they are centralized

            channel = guild.get_channel(forum_id)

            if not isinstance(channel, discord.ForumChannel):
                await interaction.followup.send(
                    "❌ Recipe channel is not a forum channel."
                )
                return

            thread = await create_recipe_post(
                channel,
                recipe,
            )
            save_recipe(recipe, thread.id)

            await interaction.followup.send(
                "✅ Recipe added!"
            )

        except Exception as e:
            print(type(e))
            print(e)

            await interaction.followup.send(
                "❌ I couldn't import that recipe. "
                "The website may be blocking automated imports."
            )
            
async def setup(bot):
    await bot.add_cog(Recipe(bot))
