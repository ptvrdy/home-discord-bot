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
    get_cooking_stats,
    get_journal_message_id,
    get_random_recipe,
    get_recipe_by_thread,
    get_recipe_by_url,
    get_recipe_tags,
    get_recipes_needing_review,
    save_recipe,
    search_recipes,
    set_journal_message_id,
    set_recipe_tags,
    update_recipe_status,
)
from services.embed import build_help_embed, build_stats_embed, create_recipe_embed
from services.forum import (
    HUMAN_TAGS,
    create_recipe_post,
    diagnose_tags,
    get_matching_tags,
    keep_single_human_tag,
    normalize_tag_name,
    tags_with_human_status,
)
from services.grocery_list import (
    add_recipe_ingredients,
    find_existing_locations,
    get_grocery_lists,
    get_list_contents,
    prioritize_ingredients,
    remove_items,
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

SEARCH_RESULT_LIMIT = 10
NEEDS_REVIEW_LIMIT = 25
GROCERY_VIEW_LIMIT = 50


def merge_recipe_tags(fresh_tags: list[str], existing_tags: list[str], human_status: str) -> list[str]:
    """Combine freshly auto-detected tags with whatever's already stored, so a
    correction (like /fix) can add newly-relevant tags without silently
    dropping ones a person manually added via /tags."""
    fresh_non_human = {tag for tag in fresh_tags if tag not in HUMAN_TAGS}
    existing_non_human = {tag for tag in existing_tags if tag not in HUMAN_TAGS}
    return [human_status] + sorted(fresh_non_human | existing_non_human)


class RecipeReviewModal(discord.ui.Modal):
    def __init__(
        self,
        thread: discord.Thread,
        status_key: str,
    ):
        super().__init__(title="Add to Recipe Journal")
        self.thread = thread
        self.status_key = status_key

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
            # Made Before / Make Again / Favorite only make sense if you made
            # it; only "Needs Review" can mean you revisited it without cooking.
            activity = "Made" if self.status_key != "needs_review" else "Reviewed"

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
        fresh_tags = generate_recipe_tags(recipe)
        existing_tags = get_recipe_tags(self.thread.id)
        # Union freshly auto-detected tags with whatever's already stored,
        # using the recipe's actual current status (never generate_recipe_tags'
        # placeholder "needs_review"), so /fix can add newly-relevant tags
        # without dropping a manually-added one (via /tags) or reverting a
        # ⭐ Favorite back to 📝 Needs Review.
        recipe.tags = merge_recipe_tags(fresh_tags, existing_tags, self.current["human_status"])

        try:
            save_recipe(recipe, self.thread.id)

            if title != self.current["title"]:
                await self.thread.edit(name=title[:100])

            parent = self.thread.parent
            if isinstance(parent, discord.ForumChannel):
                await self.thread.edit(applied_tags=get_matching_tags(parent, recipe.tags))

            starter_message = await self.thread.fetch_message(self.thread.id)
            await starter_message.edit(embed=create_recipe_embed(recipe))

            await interaction.followup.send("✅ Recipe updated!", ephemeral=True)
        except (discord.HTTPException, sqlite3.Error) as error:
            await interaction.followup.send(
                f"❌ I couldn't update this recipe: {error}",
                ephemeral=True,
            )


class RecipeTagSelect(discord.ui.Select):
    def __init__(self, thread: discord.Thread, human_status: str, current_tags: list[str]):
        options = [
            discord.SelectOption(
                label=tag_info["discord_name"],
                value=tag_key,
                default=tag_key in current_tags,
            )
            for tag_key, tag_info in DISCORD_TAGS.items()
            if tag_key not in HUMAN_TAGS
        ]
        super().__init__(
            placeholder="Choose every tag that applies...",
            min_values=0,
            max_values=len(options),
            options=options,
        )
        self.thread = thread
        self.human_status = human_status

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        selected_tags = list(self.values)
        set_recipe_tags(self.thread.id, selected_tags)

        parent = self.thread.parent
        if isinstance(parent, discord.ForumChannel):
            full_tags = [self.human_status, *selected_tags]
            await self.thread.edit(applied_tags=get_matching_tags(parent, full_tags))

        selected_names = ", ".join(
            DISCORD_TAGS[tag]["discord_name"] for tag in selected_tags
        ) or "none"
        await interaction.followup.send(f"✅ Tags updated: {selected_names}", ephemeral=True)


class RecipeTagView(discord.ui.View):
    def __init__(self, thread: discord.Thread, human_status: str, current_tags: list[str]):
        super().__init__(timeout=300)
        self.add_item(RecipeTagSelect(thread, human_status, current_tags))


class GroceryListSelect(discord.ui.Select):
    def __init__(self, recipe_title: str, ingredients: list[str], lists: list[dict]):
        options = [
            discord.SelectOption(label=grocery_list["name"], value=grocery_list["id"])
            for grocery_list in lists[:25]
        ]
        super().__init__(
            placeholder="Which store list should this go on?",
            min_values=1,
            max_values=1,
            options=options,
        )
        self.recipe_title = recipe_title
        self.ingredients = ingredients

    async def callback(self, interaction: discord.Interaction):
        list_id = self.values[0]
        list_name = next(option.label for option in self.options if option.value == list_id)

        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            locations = await find_existing_locations(self.ingredients)
        except Exception as error:
            await interaction.followup.send(
                f"❌ I couldn't check your other lists: {error}",
                ephemeral=True,
            )
            return

        content = f"Tap to uncheck anything you already have, then **Add Selected** for **{list_name}**:"
        if len(self.ingredients) > 24:
            content += f"\n_(showing the first 24 of {len(self.ingredients)} ingredients)_"

        await interaction.followup.send(
            content,
            view=IngredientToggleView(list_id, list_name, self.recipe_title, self.ingredients, locations),
            ephemeral=True,
        )


class GroceryListView(discord.ui.View):
    def __init__(self, recipe_title: str, ingredients: list[str], lists: list[dict]):
        super().__init__(timeout=300)
        self.add_item(GroceryListSelect(recipe_title, ingredients, lists))


class IngredientToggleButton(discord.ui.Button):
    def __init__(self, ingredient: str, location: str | None = None):
        self.ingredient = ingredient
        self.location = location
        # Default unchecked if it's already sitting on some list - active
        # opt-in to add a likely-duplicate rather than a silent skip.
        self.checked = location is None
        super().__init__(label=self._label(), style=self._style())

    def _label(self) -> str:
        base = f"{'✅' if self.checked else '⬜'} {self.ingredient}"
        if self.location:
            base += f" (on {self.location})"
        return base[:80]

    def _style(self) -> discord.ButtonStyle:
        return discord.ButtonStyle.success if self.checked else discord.ButtonStyle.secondary

    async def callback(self, interaction: discord.Interaction):
        # Editing this same message in place (not sending a new one) keeps the
        # buttons at a fixed position on screen - toggling never resizes or
        # reflows the message, unlike a Select dropdown's collapsing list.
        self.checked = not self.checked
        self.style = self._style()
        self.label = self._label()
        await interaction.response.edit_message(view=self.view)


class ConfirmGroceryButton(discord.ui.Button):
    def __init__(self, list_id: str, list_name: str, recipe_title: str):
        super().__init__(label="Add Selected", style=discord.ButtonStyle.primary)
        self.list_id = list_id
        self.list_name = list_name
        self.recipe_title = recipe_title

    async def callback(self, interaction: discord.Interaction):
        selected_ingredients = [
            child.ingredient
            for child in self.view.children
            if isinstance(child, IngredientToggleButton) and child.checked
        ]

        if not selected_ingredients:
            await interaction.response.edit_message(
                content="Nothing selected — nothing added.", view=None
            )
            return

        # This message already exists (it's what the button is attached to),
        # so deferring here means "I'll update this same message," which is
        # exactly what edit_original_response below does once the slow
        # OurGroceries call finishes.
        await interaction.response.defer()

        try:
            result = await add_recipe_ingredients(self.list_id, selected_ingredients, self.recipe_title)
        except Exception as error:
            await interaction.edit_original_response(
                content=f"❌ I couldn't update OurGroceries: {error}", view=None
            )
            return

        lines = [f"🛒 Added to **{self.list_name}**:"]
        lines += [f"• {item}" for item in result["added"]] or ["_(nothing new - already on the list)_"]
        if result["skipped"]:
            lines.append(f"_Already there: {', '.join(result['skipped'])}_")

        undo_view = None
        if result["added_item_ids"]:
            undo_view = UndoAddView(self.list_id, self.list_name, result["added_item_ids"])

        await interaction.edit_original_response(content="\n".join(lines), view=undo_view)


class UndoAddButton(discord.ui.Button):
    def __init__(self, list_id: str, list_name: str, item_ids: list[str]):
        super().__init__(label="Undo", style=discord.ButtonStyle.danger)
        self.list_id = list_id
        self.list_name = list_name
        self.item_ids = item_ids

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()

        try:
            await remove_items(self.list_id, self.item_ids)
        except Exception as error:
            await interaction.edit_original_response(
                content=f"❌ I couldn't undo that: {error}", view=None
            )
            return

        await interaction.edit_original_response(
            content=f"↩️ Removed those items from **{self.list_name}**.",
            view=None,
        )


class UndoAddView(discord.ui.View):
    def __init__(self, list_id: str, list_name: str, item_ids: list[str]):
        super().__init__(timeout=300)
        self.add_item(UndoAddButton(list_id, list_name, item_ids))


class IngredientToggleView(discord.ui.View):
    def __init__(
        self,
        list_id: str,
        list_name: str,
        recipe_title: str,
        ingredients: list[str],
        locations: dict[str, str] | None = None,
    ):
        super().__init__(timeout=300)
        locations = locations or {}
        for ingredient in prioritize_ingredients(ingredients, limit=24):
            location = locations.get(ingredient.strip().lower())
            self.add_item(IngredientToggleButton(ingredient, location))
        self.add_item(ConfirmGroceryButton(list_id, list_name, recipe_title))


class ViewGroceryListSelect(discord.ui.Select):
    def __init__(self, lists: list[dict]):
        options = [
            discord.SelectOption(label=grocery_list["name"], value=grocery_list["id"])
            for grocery_list in lists[:25]
        ]
        super().__init__(
            placeholder="Which list do you want to see?",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        list_id = self.values[0]
        list_name = next(option.label for option in self.options if option.value == list_id)

        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            contents = await get_list_contents(list_id)
        except Exception as error:
            await interaction.followup.send(
                f"❌ I couldn't load that list: {error}",
                ephemeral=True,
            )
            return

        active = contents["active"]
        crossed_off_count = len(contents["crossed_off"])

        if not active:
            body = "_(nothing on this list right now)_"
        else:
            shown = active[:GROCERY_VIEW_LIMIT]
            body = "\n".join(f"• {item}" for item in shown)
            if len(active) > GROCERY_VIEW_LIMIT:
                body += f"\n_(showing the first {GROCERY_VIEW_LIMIT} of {len(active)})_"

        lines = [f"🛒 **{list_name}**", body]
        if crossed_off_count:
            lines.append(f"_{crossed_off_count} item(s) already crossed off_")

        await interaction.followup.send("\n".join(lines), ephemeral=True)


class ViewGroceryListView(discord.ui.View):
    def __init__(self, lists: list[dict]):
        super().__init__(timeout=300)
        self.add_item(ViewGroceryListSelect(lists))


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
            normalize_tag_name(tag_info["discord_name"]): tag_key
            for tag_key, tag_info in DISCORD_TAGS.items()
            if tag_key in HUMAN_TAGS
        }
        status = next(
            (
                status_names[normalize_tag_name(tag.name)]
                for tag in filtered_tags
                if normalize_tag_name(tag.name) in status_names
            ),
            None,
        )
        if status:
            update_recipe_status(after.id, status)

    @app_commands.command(
        name="review",
        description="Add a dated note and status to a recipe thread",
    )
    @app_commands.describe(status="The recipe's current family status")
    @app_commands.choices(status=RECIPE_STATUS_CHOICES)
    async def review(
        self,
        interaction: discord.Interaction,
        status: app_commands.Choice[str],
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
            RecipeReviewModal(channel, status.value)
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
        name="find_ingredient",
        description="Search recipes by title or ingredient",
    )
    @app_commands.describe(query="Text to search for, e.g. an ingredient or dish name")
    async def find_ingredient(self, interaction: discord.Interaction, query: str):
        results = search_recipes(query, limit=SEARCH_RESULT_LIMIT)

        if not results:
            await interaction.response.send_message(
                f'🔍 No recipes found matching "{query}".',
                ephemeral=True,
            )
            return

        lines = [f'🔍 Found {len(results)} recipe(s) matching "{query}":']
        lines += [
            f"• **{result['title']}** — <#{result['discord_thread_id']}>"
            for result in results
        ]
        if len(results) == SEARCH_RESULT_LIMIT:
            lines.append(
                f"_(showing the first {SEARCH_RESULT_LIMIT} matches — "
                "try a more specific search to narrow it down)_"
            )

        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @app_commands.command(
        name="needs_review",
        description="List recipes still marked Needs Review",
    )
    async def needs_review(self, interaction: discord.Interaction):
        results = get_recipes_needing_review(limit=NEEDS_REVIEW_LIMIT)

        if not results:
            await interaction.response.send_message("📝 Nothing needs review right now!")
            return

        lines = [f"📝 {len(results)} recipe(s) still need review:"]
        lines += [
            f"• **{result['title']}** — <#{result['discord_thread_id']}>"
            for result in results
        ]
        if len(results) == NEEDS_REVIEW_LIMIT:
            lines.append(f"_(showing the first {NEEDS_REVIEW_LIMIT} — there may be more)_")

        await interaction.response.send_message("\n".join(lines))

    @app_commands.command(
        name="cooking_stats",
        description="See household cooking stats: top rated, most cooked, and who's been busy",
    )
    async def cooking_stats(self, interaction: discord.Interaction):
        stats = get_cooking_stats()
        await interaction.response.send_message(embed=build_stats_embed(stats))

    @app_commands.command(
        name="shopping_list",
        description="Add this recipe's ingredients to an OurGroceries list (run inside its thread)",
    )
    async def shopping_list(self, interaction: discord.Interaction):
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

        recipe = get_recipe_by_thread(channel.id)
        if recipe is None:
            await interaction.response.send_message(
                "❌ This recipe isn't in the database yet.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            lists = await get_grocery_lists()
        except Exception as error:
            await interaction.followup.send(
                f"❌ I couldn't connect to OurGroceries: {error}",
                ephemeral=True,
            )
            return

        if not lists:
            await interaction.followup.send(
                "❌ No OurGroceries lists found on that account.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            "Which list should this go on?",
            view=GroceryListView(recipe["title"], recipe["ingredients"], lists),
            ephemeral=True,
        )

    @app_commands.command(
        name="grocery_list",
        description="See what's currently on one of your OurGroceries lists",
    )
    async def grocery_list_view(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            lists = await get_grocery_lists()
        except Exception as error:
            await interaction.followup.send(
                f"❌ I couldn't connect to OurGroceries: {error}",
                ephemeral=True,
            )
            return

        if not lists:
            await interaction.followup.send(
                "❌ No OurGroceries lists found on that account.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            "Which list?",
            view=ViewGroceryListView(lists),
            ephemeral=True,
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

    @app_commands.command(
        name="check_setup",
        description="Verify every configured tag actually matches a tag on the recipe forum",
    )
    async def check_setup(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "❌ This command can only be used in a server.",
                ephemeral=True,
            )
            return

        if self.recipe_forum_id is None:
            await interaction.response.send_message(
                "❌ Recipe forum is not configured.",
                ephemeral=True,
            )
            return

        channel = guild.get_channel(self.recipe_forum_id)
        if not isinstance(channel, discord.ForumChannel):
            await interaction.response.send_message(
                "❌ Recipe channel is not a forum channel.",
                ephemeral=True,
            )
            return

        result = diagnose_tags([tag.name for tag in channel.available_tags])

        lines = [f"✅ {len(result['ok'])} tag(s) match exactly."]

        if result["mismatched"]:
            lines.append(
                f"⚠️ {len(result['mismatched'])} tag(s) match only approximately "
                "(they still work, but the text differs slightly - worth tidying up):"
            )
            lines += [f"  • configured `{a}` vs. forum `{b}`" for a, b in result["mismatched"]]

        if result["missing"]:
            lines.append(
                f"❌ {len(result['missing'])} tag(s) are missing from the forum entirely "
                "(these will never get applied):"
            )
            lines += [f"  • {name}" for name in result["missing"]]

        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @app_commands.command(
        name="tags",
        description="Manually choose which tags apply to this recipe (run inside its thread)",
    )
    async def tags(self, interaction: discord.Interaction):
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

        current_tags = get_recipe_tags(channel.id)
        await interaction.response.send_message(
            "Select every tag that applies:",
            view=RecipeTagView(channel, current["human_status"], current_tags),
            ephemeral=True,
        )

    @app_commands.command(
        name="help",
        description="List every command Rosie supports",
    )
    async def help_command(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=build_help_embed(), ephemeral=True)


async def setup(bot):
    await bot.add_cog(Recipe(bot))
