import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from commands import meal_plan_commands, recipe_commands
from commands.recipe_commands import (
    AddInstructionsModal,
    FixRecipeImageModal,
    FixRecipeModal,
    Recipe,
    RecipeTagView,
)

FORUM_ID = 100
THREAD_ID = 555

RECIPE = {
    "title": "Tomato Pasta",
    "ingredients": ["pasta", "tomatoes"],
    "human_status": "favorite",
}


def _cog():
    cog = object.__new__(Recipe)
    cog.bot = MagicMock()
    cog.recipe_forum_id = FORUM_ID
    return cog


def _interaction(in_recipe_thread=True):
    interaction = MagicMock()
    if in_recipe_thread:
        channel = MagicMock(spec=discord.Thread)
        channel.id = THREAD_ID
        channel.parent_id = FORUM_ID
    else:
        channel = MagicMock(spec=discord.TextChannel)
    interaction.channel = channel
    interaction.response.send_message = AsyncMock()
    interaction.response.send_modal = AsyncMock()
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


def _choice(value):
    choice = MagicMock()
    choice.value = value
    return choice


class FixCommandTests(unittest.IsolatedAsyncioTestCase):
    async def _fix(self, what, interaction=None):
        interaction = interaction or _interaction()
        with patch.object(recipe_commands, "get_recipe_by_thread", return_value=RECIPE), \
             patch.object(recipe_commands, "get_recipe_tags", return_value=["pasta"]):
            await Recipe.fix.callback(_cog(), interaction, what)
        return interaction

    async def test_each_choice_opens_the_form_the_old_command_did(self):
        for value, expected in [
            (None, FixRecipeModal),  # plain /fix still means name, times, servings
            ("details", FixRecipeModal),
            ("image", FixRecipeImageModal),
            ("instructions", AddInstructionsModal),
        ]:
            with self.subTest(what=value):
                interaction = await self._fix(_choice(value) if value else None)
                modal = interaction.response.send_modal.await_args.args[0]
                self.assertIsInstance(modal, expected)

    async def test_the_tags_choice_shows_the_checkbox_menu_with_current_tags(self):
        interaction = await self._fix(_choice("tags"))
        interaction.response.send_modal.assert_not_awaited()
        kwargs = interaction.response.send_message.await_args.kwargs
        self.assertIsInstance(kwargs["view"], RecipeTagView)
        self.assertTrue(kwargs["ephemeral"])

    async def test_outside_a_recipe_thread_every_choice_refuses(self):
        for value in (None, "image", "instructions", "tags"):
            with self.subTest(what=value):
                interaction = await self._fix(_choice(value) if value else None, _interaction(False))
                interaction.response.send_modal.assert_not_awaited()
                self.assertIn("inside a recipe thread", interaction.response.send_message.await_args.args[0])

    async def test_a_recipe_missing_from_the_database_is_reported(self):
        interaction = _interaction()
        with patch.object(recipe_commands, "get_recipe_by_thread", return_value=None):
            await Recipe.fix.callback(_cog(), interaction, _choice("tags"))
        self.assertIn("isn't in the database", interaction.response.send_message.await_args.args[0])

    def test_the_old_separate_commands_are_gone(self):
        names = {command.name for command in Recipe.__cog_app_commands__}
        self.assertTrue({"fix", "shopping_list"} <= names)
        self.assertFalse(names & {"fix_image", "add_instructions", "tags", "combine_recipes"})


LISTS = [{"id": "1", "name": "Costco"}]
PASTA = {"title": "Tomato Pasta", "ingredients": ["pasta", "tomatoes"]}
SOUP = {"title": "Lentil Soup", "ingredients": ["lentils", "tomatoes"]}


class ShoppingListCommandTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, interaction, *titles, by_title=None, thread_recipe=None):
        padded = list(titles) + [None] * (5 - len(titles))
        recipes = by_title or {}
        with patch.object(recipe_commands, "get_recipe_by_title", side_effect=lambda t: recipes.get(t)), \
             patch.object(recipe_commands, "get_recipe_by_thread", return_value=thread_recipe), \
             patch.object(recipe_commands, "get_grocery_lists", AsyncMock(return_value=LISTS)), \
             patch.object(recipe_commands, "GroceryListView") as view:
            await Recipe.shopping_list.callback(_cog(), interaction, *padded)
        return view

    async def test_with_nothing_filled_in_it_uses_the_recipe_thread_it_was_run_in(self):
        interaction = _interaction()
        view = await self._run(interaction, thread_recipe=PASTA)
        view.assert_called_once_with("Tomato Pasta", ["pasta", "tomatoes"], LISTS)  # not run through "combine"
        self.assertEqual(interaction.followup.send.await_args.args[0], "Which list should this go on?")

    async def test_naming_several_recipes_combines_them(self):
        interaction = _interaction(in_recipe_thread=False)
        view = await self._run(interaction, "Tomato Pasta", "Lentil Soup",
                               by_title={"Tomato Pasta": PASTA, "Lentil Soup": SOUP})
        title, ingredients, lists = view.call_args.args
        self.assertEqual(lists, LISTS)
        self.assertIn("Tomato Pasta", title)
        self.assertIn("Lentil Soup", title)
        self.assertEqual(len([i for i in ingredients if "tomato" in str(i).lower()]), 1)  # de-duplicated
        self.assertIn("Combined 2 recipe(s)", interaction.followup.send.await_args.args[0])

    async def test_one_named_recipe_works_from_any_channel_and_beats_the_thread(self):
        interaction = _interaction()  # inside some recipe thread, but a different recipe is named
        view = await self._run(interaction, "Lentil Soup", by_title={"Lentil Soup": SOUP}, thread_recipe=PASTA)
        view.assert_called_once_with("Lentil Soup", ["lentils", "tomatoes"], LISTS)

    async def test_the_same_recipe_named_twice_is_not_doubled(self):
        interaction = _interaction(in_recipe_thread=False)
        view = await self._run(interaction, "Tomato Pasta", "Tomato Pasta", by_title={"Tomato Pasta": PASTA})
        view.assert_called_once_with("Tomato Pasta", ["pasta", "tomatoes"], LISTS)

    async def test_a_title_that_matches_nothing_says_so_and_does_not_continue(self):
        interaction = _interaction(in_recipe_thread=False)
        view = await self._run(interaction, "Nope", by_title={})
        view.assert_not_called()
        self.assertIn('"Nope"', interaction.response.send_message.await_args.args[0])

    async def test_nothing_named_and_not_in_a_thread_explains_both_ways_to_use_it(self):
        interaction = _interaction(in_recipe_thread=False)
        view = await self._run(interaction)
        view.assert_not_called()
        message = interaction.response.send_message.await_args.args[0]
        self.assertIn("recipe thread", message)
        self.assertIn("pick a recipe", message)

    async def test_a_thread_recipe_missing_from_the_database_is_reported(self):
        interaction = _interaction()
        view = await self._run(interaction, thread_recipe=None)
        view.assert_not_called()
        self.assertIn("isn't in the database", interaction.response.send_message.await_args.args[0])


def _row(title, thread_id, ingredients):
    return {"title": title, "discord_thread_id": thread_id, "ingredients": ingredients}


class SuggestRecipeCommandTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, count, rows, tag=None):
        interaction = _interaction(in_recipe_thread=False)
        with patch.object(recipe_commands, "get_random_recipes", return_value=rows) as pick,              patch.object(recipe_commands, "get_grocery_lists", AsyncMock(return_value=LISTS)),              patch.object(recipe_commands, "GroceryListView") as view:
            await Recipe.suggest_recipe.callback(_cog(), interaction, count, tag)
        return interaction, pick, view

    async def test_the_default_is_one_recipe_posted_publicly_with_a_link(self):
        interaction, pick, view = await self._run(1, [_row("Tomato Pasta", 7, ["pasta"])])
        pick.assert_called_once_with(1, None)
        view.assert_not_called()
        interaction.response.defer.assert_not_awaited()
        text = interaction.response.send_message.await_args.args[0]
        self.assertIn("Tomato Pasta", text)
        self.assertIn("<#7>", text)
        self.assertNotIn("ephemeral", interaction.response.send_message.await_args.kwargs)

    async def test_two_or_more_offers_the_combined_shopping_list(self):
        rows = [_row("Tomato Pasta", 7, ["pasta", "tomatoes"]), _row("Lentil Soup", 8, ["lentils", "tomatoes"])]
        interaction, _, view = await self._run(2, rows)
        title, ingredients, lists = view.call_args.args
        self.assertEqual(lists, LISTS)
        self.assertEqual(len([i for i in ingredients if "tomato" in str(i).lower()]), 1)
        text = interaction.followup.send.await_args.args[0]
        self.assertIn("<#7>", text)
        self.assertIn("<#8>", text)

    async def test_the_tag_filter_is_passed_through_and_an_empty_result_says_so(self):
        tag = SimpleNamespace(value="beef", name="🥩 Beef")
        interaction, pick, view = await self._run(3, [], tag)
        pick.assert_called_once_with(3, "beef")
        view.assert_not_called()
        self.assertIn("No recipes tagged", interaction.response.send_message.await_args.args[0])

    def test_the_old_random_and_meal_plan_suggesters_are_gone(self):
        names = {command.name for command in Recipe.__cog_app_commands__}
        self.assertIn("suggest_recipe", names)
        self.assertFalse(names & {"random", "meal_plan"})


class MealPlanCommandNamesTests(unittest.TestCase):
    def test_meal_plan_adds_and_meal_plan_clear_clears(self):
        names = {command.name for command in meal_plan_commands.MealPlan.__cog_app_commands__}
        self.assertEqual(names, {"meal_plan", "meal_plan_clear"})


if __name__ == "__main__":
    unittest.main()
