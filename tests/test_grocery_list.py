import unittest
from unittest.mock import AsyncMock

from services.grocery_list import (
    add_recipe_ingredients,
    find_existing_locations,
    get_grocery_lists,
    get_list_contents,
    prioritize_ingredients,
    remove_items,
)


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

    async def test_add_recipe_ingredients_readds_crossed_off_items(self):
        client = AsyncMock()
        client.get_list_items.return_value = {
            "list": {"items": [{"id": "1", "value": "Sugar", "crossedOff": True}]}
        }

        result = await add_recipe_ingredients(
            "list-1", ["Sugar"], "Cookies", client=client,
        )

        # Crossed off means "bought it," not "keep skipping this forever."
        self.assertEqual(result["added"], ["Sugar"])
        self.assertEqual(result["skipped"], [])
        client.add_item_to_list.assert_awaited_once_with(
            "list-1", "Sugar", auto_category=True, note="Cookies"
        )

    async def test_add_recipe_ingredients_readds_items_crossed_off_via_timestamp_field(self):
        # The real server response appears to flag crossed-off items with a
        # "crossedOffAt" timestamp rather than the "crossedOff" boolean the
        # library's own default-False normalizer expects.
        client = AsyncMock()
        client.get_list_items.return_value = {
            "list": {"items": [{"id": "1", "value": "Sugar", "crossedOffAt": 1737072000}]}
        }

        result = await add_recipe_ingredients(
            "list-1", ["Sugar"], "Cookies", client=client,
        )

        self.assertEqual(result["added"], ["Sugar"])
        self.assertEqual(result["skipped"], [])

    async def test_add_recipe_ingredients_handles_empty_existing_list(self):
        client = AsyncMock()
        client.get_list_items.return_value = {"list": {"items": []}}

        result = await add_recipe_ingredients(
            "list-1", ["flour", "sugar"], "Cookies", client=client,
        )

        self.assertEqual(result["added"], ["flour", "sugar"])
        self.assertEqual(result["skipped"], [])
        self.assertEqual(client.add_item_to_list.await_count, 2)

    async def test_add_recipe_ingredients_captures_new_item_ids_via_refetch(self):
        client = AsyncMock()
        client.get_list_items.side_effect = [
            {"list": {"items": []}},  # pre-check: list is empty
            {  # post-add refetch: newly-added items now present with real IDs
                "list": {
                    "items": [
                        {"id": "item-1", "value": "flour"},
                        {"id": "item-2", "value": "sugar"},
                    ]
                }
            },
        ]

        result = await add_recipe_ingredients(
            "list-1", ["flour", "sugar"], "Cookies", client=client,
        )

        self.assertEqual(result["added"], ["flour", "sugar"])
        self.assertEqual(set(result["added_item_ids"]), {"item-1", "item-2"})

    async def test_add_recipe_ingredients_skips_refetch_when_nothing_added(self):
        client = AsyncMock()
        client.get_list_items.return_value = {
            "list": {"items": [{"id": "1", "value": "flour"}]}
        }

        result = await add_recipe_ingredients(
            "list-1", ["flour"], "Cookies", client=client,
        )

        self.assertEqual(result["added"], [])
        self.assertEqual(result["added_item_ids"], [])
        # Only the pre-check call, no wasted refetch since nothing was added.
        self.assertEqual(client.get_list_items.await_count, 1)

    async def test_remove_items_removes_each_id(self):
        client = AsyncMock()

        await remove_items("list-1", ["item-1", "item-2"], client=client)

        client.login.assert_awaited_once()
        self.assertEqual(client.remove_item_from_list.await_count, 2)
        client.remove_item_from_list.assert_any_await("list-1", "item-1")
        client.remove_item_from_list.assert_any_await("list-1", "item-2")

    async def test_get_list_contents_splits_active_and_crossed_off(self):
        client = AsyncMock()
        client.get_list_items.return_value = {
            "list": {
                "items": [
                    {"id": "1", "value": "Milk"},
                    {"id": "2", "value": "Eggs", "crossedOff": True},
                    {"id": "3", "name": "Bread", "crossedOffAt": 1737072000},
                ]
            }
        }

        contents = await get_list_contents("list-1", client=client)

        client.login.assert_awaited_once()
        self.assertEqual(contents["active"], ["Milk"])
        self.assertEqual(set(contents["crossed_off"]), {"Eggs", "Bread"})

    async def test_get_list_contents_handles_empty_list(self):
        client = AsyncMock()
        client.get_list_items.return_value = {"list": {"items": []}}

        contents = await get_list_contents("list-1", client=client)

        self.assertEqual(contents, {"active": [], "crossed_off": []})

    async def test_find_existing_locations_checks_across_multiple_lists(self):
        client = AsyncMock()
        client.get_my_lists.return_value = {
            "shoppingLists": [
                {"id": "cvs", "name": "CVS"},
                {"id": "wf", "name": "Whole Foods"},
            ]
        }
        client.get_list_items.side_effect = [
            {"list": {"items": [{"id": "1", "value": "Milk"}]}},
            {"list": {"items": [{"id": "2", "value": "Flour"}]}},
        ]

        locations = await find_existing_locations(["flour", "eggs"], client=client)

        self.assertEqual(locations, {"flour": "Whole Foods"})

    async def test_find_existing_locations_ignores_crossed_off_items(self):
        client = AsyncMock()
        client.get_my_lists.return_value = {
            "shoppingLists": [{"id": "cvs", "name": "CVS"}]
        }
        client.get_list_items.return_value = {
            "list": {"items": [{"id": "1", "value": "Milk", "crossedOff": True}]}
        }

        locations = await find_existing_locations(["milk"], client=client)

        self.assertEqual(locations, {})

    async def test_find_existing_locations_stops_checking_once_everything_is_found(self):
        client = AsyncMock()
        client.get_my_lists.return_value = {
            "shoppingLists": [
                {"id": "cvs", "name": "CVS"},
                {"id": "wf", "name": "Whole Foods"},
                {"id": "tj", "name": "Trader Joe's"},
            ]
        }
        client.get_list_items.return_value = {
            "list": {"items": [{"id": "1", "value": "Milk"}]}
        }

        await find_existing_locations(["milk"], client=client)

        # Found on the first list checked; no need to check the other two.
        self.assertEqual(client.get_list_items.await_count, 1)

    async def test_find_existing_locations_returns_empty_when_nothing_matches(self):
        client = AsyncMock()
        client.get_my_lists.return_value = {
            "shoppingLists": [{"id": "cvs", "name": "CVS"}]
        }
        client.get_list_items.return_value = {"list": {"items": []}}

        locations = await find_existing_locations(["flour"], client=client)

        self.assertEqual(locations, {})


class PrioritizeIngredientsTests(unittest.TestCase):
    def test_returns_everything_unchanged_when_under_the_limit(self):
        ingredients = ["flour", "chicken thighs", "sugar"]

        self.assertEqual(prioritize_ingredients(ingredients, limit=5), ingredients)

    def test_drops_pantry_staples_first_when_over_the_limit(self):
        ingredients = ["chicken thighs", "flour", "heavy cream", "sugar", "salmon fillets"]

        result = prioritize_ingredients(ingredients, limit=3)

        self.assertEqual(len(result), 3)
        self.assertEqual(
            set(result),
            {"chicken thighs", "heavy cream", "salmon fillets"},
        )

    def test_preserves_original_relative_order_among_kept_items(self):
        ingredients = ["flour", "chicken thighs", "sugar", "heavy cream", "salt"]

        result = prioritize_ingredients(ingredients, limit=2)

        # "chicken thighs" appears before "heavy cream" in the original list.
        self.assertEqual(result, ["chicken thighs", "heavy cream"])

    def test_word_boundaries_avoid_false_positive_staple_matches(self):
        ingredients = ["watermelon", "water", "chicken breast"]

        result = prioritize_ingredients(ingredients, limit=2)

        # "watermelon" should not be treated as the pantry staple "water".
        self.assertEqual(set(result), {"watermelon", "chicken breast"})

    def test_falls_back_to_staples_if_that_is_all_that_is_left(self):
        ingredients = ["flour", "sugar", "salt", "baking soda"]

        result = prioritize_ingredients(ingredients, limit=2)

        self.assertEqual(len(result), 2)

    def test_drops_by_universality_not_by_recipe_position(self):
        # flour/sugar appear FIRST in the recipe (as they typically do in
        # baking recipes) but should still be dropped before less-universal
        # staples like cinnamon and honey that appear later.
        ingredients = [
            "flour", "sugar", "brown sugar", "baking soda", "baking powder",
            "salt", "vanilla extract", "cinnamon", "honey", "corn starch",
            "heavy cream", "strawberries",
        ]

        result = prioritize_ingredients(ingredients, limit=7)

        self.assertIn("heavy cream", result)
        self.assertIn("strawberries", result)
        for staple in ("flour", "sugar", "salt", "corn starch"):
            self.assertNotIn(staple, result)


if __name__ == "__main__":
    unittest.main()
