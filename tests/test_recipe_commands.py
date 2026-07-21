import unittest

from commands.recipe_commands import merge_recipe_tags


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


if __name__ == "__main__":
    unittest.main()
