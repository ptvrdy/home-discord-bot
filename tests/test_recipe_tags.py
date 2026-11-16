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
            }.issubset(tags)
        )

    def test_vegetarian_is_retired_and_never_generated(self):
        # It was removed from the forum (Discord's 20-tag cap), so a stored tag
        # nobody can see or filter by would only be dead data.
        recipe = Recipe(title="Garden Salad", ingredients=["lettuce", "tomato"])

        self.assertNotIn("vegetarian", generate_recipe_tags(recipe))

    def test_thanksgiving_is_tagged_for_unmistakable_dishes(self):
        for title in ["Thanksgiving Stuffing", "Classic Roast Turkey", "Homemade Cranberry Sauce",
                      "Green Bean Casserole", "Grandma's Pumpkin Pie"]:
            with self.subTest(title=title):
                recipe = Recipe(title=title, ingredients=[])
                self.assertIn("thanksgiving", generate_recipe_tags(recipe))

    def test_thanksgiving_is_not_tagged_for_everyday_turkey_or_pumpkin_dishes(self):
        for title, ingredients in [
            ("Ground Turkey Tacos", ["ground turkey"]),
            ("Turkey Burgers", ["turkey"]),
            ("Pumpkin Muffins", ["pumpkin pie spice", "flour"]),
            ("Stuffed Peppers", ["peppers", "rice"]),
        ]:
            with self.subTest(title=title):
                recipe = Recipe(title=title, ingredients=ingredients)
                self.assertNotIn("thanksgiving", generate_recipe_tags(recipe))

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
