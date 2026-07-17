import unittest

from models.recipe_card import Recipe
from services.recipe_tags import generate_recipe_tags


class RecipeTagTests(unittest.TestCase):
    def test_keyword_tags_are_not_duplicated(self):
        recipe = Recipe(title="Chicken Pasta", ingredients=["chicken breast", "penne"])

        tags = generate_recipe_tags(recipe)

        self.assertEqual(tags.count("chicken"), 1)
        self.assertEqual(tags.count("pasta"), 1)

    def test_broth_does_not_hide_an_actual_chicken_ingredient(self):
        recipe = Recipe(
            title="Chicken soup",
            ingredients=["chicken breast", "chicken broth"],
        )

        self.assertIn("chicken", generate_recipe_tags(recipe))

    def test_broth_alone_is_not_tagged_as_chicken(self):
        recipe = Recipe(title="Vegetable soup", ingredients=["chicken broth", "carrots"])

        self.assertNotIn("chicken", generate_recipe_tags(recipe))

    def test_detects_additional_text_based_tags(self):
        recipe = Recipe(
            title="Spicy One-Pot Breakfast Casserole",
            ingredients=["jalapeño", "eggs"],
            instructions="Cook in one pot.",
        )

        tags = generate_recipe_tags(recipe)

        self.assertTrue(
            {
                "breakfast",
                "one_pot",
                "vegetarian",
            }.issubset(tags)
        )

    def test_vegetarian_tag_is_omitted_for_meat_and_seafood(self):
        recipe = Recipe(title="Chicken and Shrimp Pasta", ingredients=[])

        self.assertNotIn("vegetarian", generate_recipe_tags(recipe))

    def test_desserts_are_tagged(self):
        for title in ["Chocolate Cake", "Apple Pie", "Sourdough Starter"]:
            with self.subTest(title=title):
                recipe = Recipe(title=title, ingredients=[])
                tags = generate_recipe_tags(recipe)
                self.assertEqual(
                    "dessert" in tags,
                    title != "Sourdough Starter",
                )

    def test_savory_dishes_sharing_dessert_words_are_not_tagged(self):
        savory_titles = [
            "Crab Cakes",
            "Shepherd's Pie",
            "Yorkshire Pudding",
            "Steak Tartare",
        ]
        for title in savory_titles:
            with self.subTest(title=title):
                recipe = Recipe(title=title, ingredients=["chicken breast, cut into pieces"])
                self.assertNotIn("dessert", generate_recipe_tags(recipe))

    def test_dessert_plurals_are_still_matched(self):
        recipe = Recipe(title="Chocolate Chip Cookies", ingredients=["cupcakes", "tarts"])

        self.assertIn("dessert", generate_recipe_tags(recipe))

    def test_word_boundaries_prevent_substring_false_positives(self):
        pancakes = Recipe(title="Fluffy Pancakes", ingredients=[])
        self.assertNotIn("dessert", generate_recipe_tags(pancakes))

        hamburgers = Recipe(title="Grilled Hamburgers", ingredients=["ground beef"])
        self.assertNotIn("pork", generate_recipe_tags(hamburgers))


if __name__ == "__main__":
    unittest.main()
