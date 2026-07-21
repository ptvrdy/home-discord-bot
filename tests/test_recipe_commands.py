import unittest

from commands.recipe_commands import (
    build_combined_recipe_title,
    combine_recipe_ingredients,
    merge_recipe_tags,
)


class MergeRecipeTagsTests(unittest.TestCase):
    def test_unions_fresh_and_existing_non_human_tags(self):
        merged = merge_recipe_tags(
            fresh_tags=["needs_review", "seafood"],
            existing_tags=["favorite", "dinner"],
            human_status="favorite",
        )

        self.assertEqual(merged[0], "favorite")
        self.assertEqual(set(merged), {"favorite", "seafood", "dinner"})

    def test_never_uses_the_fresh_needs_review_placeholder(self):
        merged = merge_recipe_tags(
            fresh_tags=["needs_review", "pasta"],
            existing_tags=[],
            human_status="favorite",
        )

        self.assertNotIn("needs_review", merged)
        self.assertIn("favorite", merged)

    def test_deduplicates_overlapping_tags(self):
        merged = merge_recipe_tags(
            fresh_tags=["needs_review", "beef", "quick"],
            existing_tags=["needs_review", "beef"],
            human_status="needs_review",
        )

        self.assertEqual(merged.count("beef"), 1)


class CombineRecipeIngredientsTests(unittest.TestCase):
    def test_dedupes_case_insensitively_across_recipes_keeping_first_wording(self):
        recipes = [
            {"title": "Tacos", "ingredients": ["Ground Beef", "Onion", "Taco Shells"]},
            {"title": "Chili", "ingredients": ["ground beef", "Kidney Beans"]},
        ]

        combined = combine_recipe_ingredients(recipes)

        self.assertEqual(
            combined, ["Ground Beef", "Onion", "Taco Shells", "Kidney Beans"]
        )

    def test_handles_a_single_recipe(self):
        recipes = [{"title": "Salad", "ingredients": ["lettuce", "tomato"]}]

        self.assertEqual(combine_recipe_ingredients(recipes), ["lettuce", "tomato"])

    def test_handles_no_recipes(self):
        self.assertEqual(combine_recipe_ingredients([]), [])


class BuildCombinedRecipeTitleTests(unittest.TestCase):
    def test_joins_titles_with_commas(self):
        recipes = [{"title": "Tacos"}, {"title": "Chili"}]

        self.assertEqual(build_combined_recipe_title(recipes), "Tacos, Chili")

    def test_truncates_when_over_the_limit(self):
        recipes = [{"title": "A" * 50}, {"title": "B" * 50}, {"title": "C" * 50}]

        title = build_combined_recipe_title(recipes, limit=100)

        self.assertEqual(len(title), 100)
        self.assertTrue(title.endswith("…"))


if __name__ == "__main__":
    unittest.main()
