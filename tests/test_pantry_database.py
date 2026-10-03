import json
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from services.database import (
    forget_og_imported,
    get_all_recipes,
    get_imported_og_keys,
    get_new_tj_products,
    get_pantry_aliases,
    get_pantry_products,
    get_tj_catalog,
    initialize_database,
    record_og_imported,
    record_pantry_product,
    search_tj_products,
    set_pantry_alias,
    upsert_tj_products,
)


def _row(sku, name, price=1.99, is_new=False):
    return {"sku": sku, "name": name, "category": "Food", "subcategory": None, "price": price,
            "size": None, "image_url": None, "is_new": is_new}


class PantryDatabaseTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.db = Path(self._dir.name) / "recipes.db"
        initialize_database(self.db)

    def tearDown(self):
        self._dir.cleanup()

    def test_catalog_sync_tracks_new_price_changes_discontinued_and_returning(self):
        first = upsert_tj_products(
            [_row("1", "Mandarin Orange Chicken"), _row("2", "Pumpkin Bread"), _row("3", "Eggs")],
            datetime(2026, 9, 1),
            database_path=self.db,
        )
        self.assertEqual(first, {"added": 3, "price_changed": 0, "discontinued": 0, "returned_skus": []})

        second = upsert_tj_products(
            [_row("1", "Mandarin Orange Chicken", price=5.49), _row("3", "Eggs")],
            datetime(2026, 10, 1),
            database_path=self.db,
        )
        self.assertEqual(second["price_changed"], 1)
        self.assertEqual(second["discontinued"], 1)
        self.assertEqual([row["sku"] for row in get_tj_catalog(database_path=self.db)], ["3", "1"])

        third = upsert_tj_products(
            [_row("1", "Mandarin Orange Chicken", price=5.49), _row("2", "Pumpkin Bread"), _row("3", "Eggs")],
            datetime(2026, 11, 1),
            database_path=self.db,
        )
        self.assertEqual(third["returned_skus"], ["2"])
        self.assertEqual(third["discontinued"], 0)

    def test_search_requires_every_word(self):
        upsert_tj_products(
            [_row("1", "Organic Chicken Thighs"), _row("2", "Chicken Breast"), _row("3", "Organic Eggs")],
            datetime(2026, 9, 1),
            database_path=self.db,
        )
        self.assertEqual([row["sku"] for row in search_tj_products("organic chicken", database_path=self.db)], ["1"])

    def test_new_products(self):
        upsert_tj_products([_row("1", "Old Thing"), _row("2", "New Thing", is_new=True)], datetime(2026, 9, 1), database_path=self.db)
        self.assertEqual([row["sku"] for row in get_new_tj_products(database_path=self.db)], ["2"])

    def test_aliases_and_products(self):
        upsert_tj_products([_row("9", "Organic Large Brown Eggs")], datetime(2026, 9, 1), database_path=self.db)
        record_pantry_product(42, "Egg", "9", database_path=self.db)
        set_pantry_alias("egg", 42, "Sam", database_path=self.db)
        set_pantry_alias("brown egg", 42, database_path=self.db)
        set_pantry_alias("", 42, database_path=self.db)  # ignored

        self.assertEqual(get_pantry_aliases(database_path=self.db), {"egg": 42, "brown egg": 42})
        products = get_pantry_products(database_path=self.db)
        self.assertEqual(products[0]["tj_name"], "Organic Large Brown Eggs")

    def test_og_imported_round_trip(self):
        now = datetime(2026, 10, 3, 19)
        record_og_imported([("a", "123"), ("b", "")], "list-1", now, database_path=self.db)
        record_og_imported([("a", "123")], "list-1", now, database_path=self.db)  # duplicate ignored
        self.assertEqual(get_imported_og_keys(database_path=self.db), {("a", "123"), ("b", "")})

        forget_og_imported(["a"], database_path=self.db)
        self.assertEqual(get_imported_og_keys(database_path=self.db), {("b", "")})

    def test_get_all_recipes_with_tag_filter(self):
        connection = sqlite3.connect(self.db)
        connection.execute(
            "INSERT INTO recipes (id, title, source_url, ingredients_json, discord_thread_id) VALUES (1, 'Tacos', '', ?, 11)",
            (json.dumps(["1 lb ground beef"]),),
        )
        connection.execute(
            "INSERT INTO recipes (id, title, source_url, ingredients_json, discord_thread_id) VALUES (2, 'Salad', '', ?, 12)",
            (json.dumps(["lettuce"]),),
        )
        connection.execute("INSERT INTO recipe_tags (recipe_id, tag) VALUES (1, 'beef')")
        connection.commit()
        connection.close()

        self.assertEqual([recipe["title"] for recipe in get_all_recipes(database_path=self.db)], ["Salad", "Tacos"])
        beef = get_all_recipes("beef", database_path=self.db)
        self.assertEqual(beef, [{"title": "Tacos", "discord_thread_id": 11, "ingredients": ["1 lb ground beef"]}])


if __name__ == "__main__":
    unittest.main()
