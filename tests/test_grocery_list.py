import unittest
from unittest.mock import AsyncMock

from services.grocery_list import add_recipe_ingredients, get_grocery_lists


class GroceryListTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_grocery_lists_maps_id_and_name(self):
        client = AsyncMock()
        client.get_my_lists.return_value = {
            "shoppingLists": [
                {"id": "abc123", "name": "Ideal Food Basket"},
                {"id": "def456", "name": "Trader Joe's"},
            ]
        }

        lists = await get_grocery_lists(client=client)

        client.login.assert_awaited_once()
        self.assertEqual(
            lists,
            [
                {"id": "abc123", "name": "Ideal Food Basket"},
                {"id": "def456", "name": "Trader Joe's"},
            ],
        )

    async def test_add_recipe_ingredients_skips_items_already_on_the_list(self):
        client = AsyncMock()
        client.get_list_items.return_value = {
            "list": {"items": [{"id": "1", "value": "Onion"}, {"id": "2", "name": "garlic"}]}
        }

        result = await add_recipe_ingredients(
            "list-1",
            ["Onion", "Garlic", "Ground Beef"],
            "Beef Tacos",
            client=client,
        )

        self.assertEqual(result["added"], ["Ground Beef"])
        self.assertEqual(result["skipped"], ["Onion", "Garlic"])
        client.add_item_to_list.assert_awaited_once_with(
            "list-1", "Ground Beef", auto_category=True, note="Beef Tacos"
        )

    async def test_add_recipe_ingredients_matches_existing_items_case_insensitively(self):
        client = AsyncMock()
        client.get_list_items.return_value = {
            "list": {"items": [{"id": "1", "value": "GROUND BEEF"}]}
        }

        result = await add_recipe_ingredients(
            "list-1", ["ground beef"], "Beef Tacos", client=client,
        )

        self.assertEqual(result["added"], [])
        self.assertEqual(result["skipped"], ["ground beef"])
        client.add_item_to_list.assert_not_awaited()

    async def test_add_recipe_ingredients_handles_empty_existing_list(self):
        client = AsyncMock()
        client.get_list_items.return_value = {"list": {"items": []}}

        result = await add_recipe_ingredients(
            "list-1", ["flour", "sugar"], "Cookies", client=client,
        )

        self.assertEqual(result["added"], ["flour", "sugar"])
        self.assertEqual(result["skipped"], [])
        self.assertEqual(client.add_item_to_list.await_count, 2)


if __name__ == "__main__":
    unittest.main()
