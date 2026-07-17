import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from models.recipe_card import Recipe
from services.database import add_cooking_log, initialize_database, save_recipe, update_recipe_status


class DatabaseTests(unittest.TestCase):
    def test_saves_a_recipe_tags_status_and_cooking_log(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            recipe = Recipe(
                title="Tomato Pasta",
                ingredients=["pasta", "tomatoes"],
                instructions="Cook and serve.",
                source_url="https://example.com/tomato-pasta",
                tags=["needs_review", "pasta", "vegetarian"],
            )

            initialize_database(database_path)
            recipe_id = save_recipe(recipe, 12345, database_path)
            self.assertGreater(recipe_id, 0)
            self.assertTrue(update_recipe_status(12345, "favorite", database_path))
            self.assertTrue(
                add_cooking_log(
                    12345,
                    datetime(2026, 7, 17, tzinfo=timezone.utc),
                    "Made",
                    "favorite",
                    "Used extra basil.",
                    "Add more garlic.",
                    67890,
                    database_path,
                )
            )

            connection = sqlite3.connect(database_path)
            try:
                status = connection.execute(
                    "SELECT human_status FROM recipes WHERE id = ?", (recipe_id,)
                ).fetchone()[0]
                tags = connection.execute(
                    "SELECT tag FROM recipe_tags WHERE recipe_id = ? ORDER BY tag", (recipe_id,)
                ).fetchall()
                log_entry = connection.execute(
                    "SELECT activity, status, notes FROM cooking_log WHERE recipe_id = ?",
                    (recipe_id,),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(status, "favorite")
            self.assertEqual(tags, [("favorite",), ("pasta",), ("vegetarian",)])
            self.assertEqual(log_entry, ("Made", "favorite", "Used extra basil."))
