import unittest

from models.recipe_card import Recipe
from unittest.mock import patch

from services.embed import (
    INGREDIENT_FIELD_LIMIT,
    INSTRUCTIONS_DESCRIPTION_LIMIT,
    _truncate_ingredient_lines,
    build_help_embed,
    build_instructions_embed,
    build_stats_embed,
    create_recipe_embed,
)


class RecipeEmbedTests(unittest.TestCase):
    def test_embed_uses_compact_recipe_box_layout(self):
        recipe = Recipe(
            title="Tomato Pasta",
            ingredients=["200g pasta", "1 cup tomatoes"],
            prep_time="10 minutes",
            total_time="25 minutes",
            yields="4 servings",
            source_name="Example Kitchen",
            source_url="https://example.com/recipe",
            image_url="https://example.com/tomato-pasta.jpg",
            tags=["pasta", "quick"],
        )

        with patch("services.embed.should_use_thumbnail", return_value=False):
            embed = create_recipe_embed(recipe)
        fields = {field.name: field.value for field in embed.fields}

        self.assertEqual(embed.title, "🍒 Tomato Pasta")
        self.assertEqual(embed.image.url, "https://example.com/tomato-pasta.jpg")
        self.assertIn("🏷️ Categories", fields)
        self.assertIn("⏱️ Time", fields)
        self.assertIn("🧺 Ingredients", fields)
        self.assertNotIn("Image", fields)
        self.assertNotIn("📖 Instructions", fields)
        normalized_description = embed.description.replace("\xa0", " ")
        self.assertIn("4 servings", normalized_description)
        self.assertIn("25 minutes", normalized_description)

    def test_ingredients_fit_within_discord_field_limit(self):
        ingredients = ["A very long ingredient " * 20 for _ in range(20)]

        ingredient_text = _truncate_ingredient_lines(ingredients)

        self.assertLessEqual(len(ingredient_text), INGREDIENT_FIELD_LIMIT)
        self.assertTrue(ingredient_text.endswith("…"))

    def test_no_instructions_embed_when_recipe_has_none(self):
        recipe = Recipe(title="Mystery Dish", ingredients=["???"])

        self.assertIsNone(build_instructions_embed(recipe))

    def test_instructions_embed_numbers_each_step(self):
        recipe = Recipe(
            title="Eggs",
            ingredients=["eggs"],
            instructions="Crack the eggs.\nWhisk well.\nCook on low heat.",
        )

        embed = build_instructions_embed(recipe)

        self.assertEqual(embed.title, "📖 Instructions")
        self.assertIn("**Step 1.** Crack the eggs.", embed.description)
        self.assertIn("**Step 2.** Whisk well.", embed.description)
        self.assertIn("**Step 3.** Cook on low heat.", embed.description)

    def test_instructions_embed_drops_trailing_steps_when_it_would_overflow(self):
        recipe = Recipe(
            title="Marathon Recipe",
            ingredients=["patience"],
            instructions="\n".join(f"Step text {i} " * 50 for i in range(50)),
        )

        embed = build_instructions_embed(recipe)

        self.assertLessEqual(len(embed.description), INSTRUCTIONS_DESCRIPTION_LIMIT)
        self.assertIn("**Step 1.**", embed.description)
        self.assertNotIn("**Step 50.**", embed.description)

    def test_stats_embed_shows_box_size_and_backlog(self):
        stats = {
            "total_recipes": 12,
            "needs_review_count": 4,
            "top_rated": [],
            "most_cooked": [],
            "by_author": [],
        }

        embed = build_stats_embed(stats)
        fields = {field.name: field.value for field in embed.fields}

        self.assertEqual(embed.title, "📊 Cooking Stats")
        normalized = fields["🍒 Recipe Box"].replace("\xa0", " ")
        self.assertIn("12 recipes", normalized)
        self.assertIn("4 need review", normalized)
        self.assertNotIn("Top Rated", fields)
        self.assertNotIn("Most Cooked", fields)
        self.assertNotIn("Reviews Logged", fields)

    def test_stats_embed_shows_ratings_and_authors_when_present(self):
        stats = {
            "total_recipes": 2,
            "needs_review_count": 1,
            "top_rated": [{"title": "Chili", "discord_thread_id": 1, "avg_rating": 4.5, "times_rated": 2}],
            "most_cooked": [{"title": "Chili", "discord_thread_id": 1, "times_made": 2}],
            "by_author": [{"author_name": "Peyton", "entry_count": 2}, {"author_name": "Husband", "entry_count": 1}],
        }

        embed = build_stats_embed(stats)
        fields = {field.name: field.value for field in embed.fields}

        self.assertIn("4.5", fields["Top Rated"])
        self.assertIn("Chili", fields["Top Rated"])
        self.assertIn("2x", fields["Most Cooked"])
        self.assertIn("Peyton: 2", fields["Reviews Logged"])
        self.assertIn("Husband: 1", fields["Reviews Logged"])

    def test_help_embed_lists_every_command_group(self):
        embed = build_help_embed()
        fields = {field.name: field.value for field in embed.fields}

        for group in (
            "📥 Import", "🏷️ Organize & Fix", "🔍 Find", "⭐ Review & Stats",
            "🛒 Grocery Shopping", "🧹 Household Chores", "⚙️ Admin",
        ):
            self.assertIn(group, fields)

        self.assertIn("/recipe", fields["📥 Import"])
        self.assertIn("/shopping_list", fields["🛒 Grocery Shopping"])
        self.assertIn("/combine_recipes", fields["🛒 Grocery Shopping"])
        self.assertIn("/meal_plan", fields["🛒 Grocery Shopping"])
        self.assertIn("/grocery_list", fields["🛒 Grocery Shopping"])
        self.assertIn("/done", fields["🧹 Household Chores"])
        self.assertLessEqual(
            sum(len(name) + len(value) for name, value in fields.items()), 6000
        )


if __name__ == "__main__":
    unittest.main()
