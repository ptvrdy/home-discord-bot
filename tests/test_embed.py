import unittest

from models.recipe_card import Recipe
from unittest.mock import patch

from services.embed import INGREDIENT_FIELD_LIMIT, _truncate_ingredient_lines, create_recipe_embed


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

    def test_ingredients_fit_within_discord_field_limit(self):
        ingredients = ["A very long ingredient " * 20 for _ in range(20)]

        ingredient_text = _truncate_ingredient_lines(ingredients)

        self.assertLessEqual(len(ingredient_text), INGREDIENT_FIELD_LIMIT)
        self.assertTrue(ingredient_text.endswith("…"))


if __name__ == "__main__":
    unittest.main()
