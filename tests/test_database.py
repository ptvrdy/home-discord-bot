import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from models.recipe_card import Recipe
from services.database import (
    add_cooking_log,
    get_cooking_log_entries,
    get_journal_message_id,
    initialize_database,
    save_recipe,
    set_journal_message_id,
    update_recipe_status,
)


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
                    5,
                    "Peyton",
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
                    "SELECT activity, status, notes, rating, author_name FROM cooking_log WHERE recipe_id = ?",
                    (recipe_id,),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(status, "favorite")
            self.assertEqual(tags, [("favorite",), ("pasta",), ("vegetarian",)])
            self.assertEqual(
                log_entry, ("Made", "favorite", "Used extra basil.", 5, "Peyton")
            )

    def test_cooking_log_entries_are_returned_oldest_first(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            recipe = Recipe(title="Chili", ingredients=["beef", "beans"], source_url="https://example.com/chili")

            initialize_database(database_path)
            save_recipe(recipe, 555, database_path)
            add_cooking_log(
                555, datetime(2026, 1, 1, tzinfo=timezone.utc), "Made", "made_before",
                "First try.", None, 3, "Peyton", database_path,
            )
            add_cooking_log(
                555, datetime(2026, 2, 1, tzinfo=timezone.utc), "Made", "make_again",
                "Better second time.", "More cumin.", 5, "Husband", database_path,
            )

            entries = get_cooking_log_entries(555, database_path)

            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0]["author_name"], "Peyton")
            self.assertEqual(entries[1]["author_name"], "Husband")

    def test_journal_message_id_round_trips(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            recipe = Recipe(title="Chili", ingredients=["beef"], source_url="https://example.com/chili")

            initialize_database(database_path)
            save_recipe(recipe, 777, database_path)

            self.assertIsNone(get_journal_message_id(777, database_path))

            set_journal_message_id(777, 999888777, database_path)

            self.assertEqual(get_journal_message_id(777, database_path), 999888777)
