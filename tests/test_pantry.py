import unittest
from unittest.mock import AsyncMock, patch

from services import pantry
from services.pantry import (
    PantryState,
    apply_action,
    create_product,
    ensure_setup,
    expiring_items,
    in_pantry_ingredients,
    plan_put_away,
    put_away,
    recipe_consumption,
)
from services.pantry_parser import ADD, CONSUME, CONSUME_ALL, FREEZE, SPOIL, PantryAction


def _state(stock=None):
    products = [
        {"id": 1, "name": "Chicken thigh", "location_id": 10},
        {"id": 2, "name": "Egg", "location_id": 10},
        {"id": 3, "name": "Milk", "location_id": 10},
        {"id": 4, "name": "Salt", "location_id": 30},
    ]
    return PantryState(products, {}, stock if stock is not None else {1: 2, 2: 12, 3: 1, 4: 1})


def _grocy():
    grocy = AsyncMock()
    grocy.base_url = "http://grocy.test/api"
    grocy.get_objects.side_effect = lambda entity: {
        "locations": [{"id": 10, "name": "Fridge"}, {"id": 20, "name": "Freezer"}, {"id": 30, "name": "Pantry"}],
        "quantity_units": [{"id": 2, "name": "Piece"}],
        "product_groups": [],
    }[entity]
    grocy.create_object.return_value = 99
    grocy.add_stock.return_value = "tx-add"
    grocy.consume.return_value = "tx-consume"
    grocy.transfer.return_value = "tx-transfer"
    grocy.open_product.return_value = "tx-open"
    return grocy


class PantryTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        pantry._setup_cache.clear()
        # Never touch the real SQLite database or the network.
        patches = [
            patch("services.pantry.record_pantry_product"),
            patch("services.pantry.set_pantry_alias"),
            patch("services.pantry.get_tj_product", return_value=None),
            patch("services.pantry.get_tj_catalog", return_value=[]),
            patch("services.pantry.download_image", new=AsyncMock(return_value=None)),
        ]
        self.mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)


class SetupTests(PantryTestCase):
    async def test_creates_missing_locations_and_unit(self):
        grocy = AsyncMock()
        grocy.base_url = "http://grocy.test/api"
        grocy.get_objects.side_effect = lambda entity: {
            "locations": [{"id": 1, "name": "Fridge"}],
            "quantity_units": [],
            "product_groups": [{"id": 5, "name": "Cheese"}],
        }[entity]
        grocy.create_object.side_effect = [11, 12, 13]

        setup = await ensure_setup(grocy)

        self.assertEqual(setup["locations"], {"Fridge": 1, "Freezer": 11, "Pantry": 12})
        self.assertEqual(setup["unit_id"], 13)
        self.assertEqual(setup["groups"], {"Cheese": 5})
        grocy.create_object.assert_any_await("locations", {"name": "Freezer", "is_freezer": 1})


class CreateProductTests(PantryTestCase):
    async def test_meat_gets_fridge_shelf_life_and_tj_group(self):
        grocy = _grocy()
        grocy.create_object.side_effect = [7, 99]  # product group, then product
        state = _state()
        tj_item = {
            "sku": "055555", "name": "Ground Beef 85/15", "category": "Meat, Seafood & Plant-based",
            "subcategory": "Beef, Pork & Lamb", "price": 6.49, "image_url": None,
        }

        product = await create_product(grocy, state, "ground beef", tj_item, "Sam")

        self.assertEqual(product, {"id": 99, "name": "Ground beef", "location_id": 10})
        data = grocy.create_object.await_args_list[-1].args[1]
        self.assertEqual(data["default_best_before_days"], 3)
        self.assertEqual(data["default_best_before_days_after_freezing"], 120)
        self.assertEqual(data["product_group_id"], 7)
        self.assertIn(product, state.products)
        self.assertEqual(state.tj_skus[99], "055555")

    async def test_untracked_category_never_expires(self):
        grocy = _grocy()
        state = _state()
        await create_product(grocy, state, "cereal", None)
        data = grocy.create_object.await_args_list[-1].args[1]
        self.assertEqual(data["default_best_before_days"], -1)
        self.assertEqual(data["location_id"], 30)


class ApplyActionTests(PantryTestCase):
    async def test_consume_specific_amount(self):
        grocy, state = _grocy(), _state()
        result = await apply_action(grocy, state, PantryAction(CONSUME, "eggs", 4), state.product(2))
        grocy.consume.assert_awaited_once_with(2, 4, spoiled=False)
        self.assertEqual(result.line, "➖ 4 Egg (8 left)")
        self.assertEqual(result.transaction_id, "tx-consume")
        self.assertIsNone(result.ran_out)

    async def test_consume_all_reports_ran_out(self):
        grocy, state = _grocy(), _state()
        result = await apply_action(grocy, state, PantryAction(CONSUME_ALL, "chicken"), state.product(1))
        grocy.consume.assert_awaited_once_with(1, 2, spoiled=False)
        self.assertEqual(result.ran_out, "Chicken thigh")

    async def test_consume_more_than_on_hand_is_capped(self):
        grocy, state = _grocy(), _state()
        await apply_action(grocy, state, PantryAction(CONSUME, "milk", 3), state.product(3))
        grocy.consume.assert_awaited_once_with(3, 1, spoiled=False)

    async def test_spoil_marks_spoiled(self):
        grocy, state = _grocy(), _state()
        await apply_action(grocy, state, PantryAction(SPOIL, "chicken"), state.product(1))
        grocy.consume.assert_awaited_once_with(1, 2, spoiled=True)

    async def test_nothing_on_hand(self):
        grocy, state = _grocy(), _state(stock={})
        result = await apply_action(grocy, state, PantryAction(CONSUME_ALL, "milk"), state.product(3))
        grocy.consume.assert_not_awaited()
        self.assertEqual(result.ran_out, "Milk")

    async def test_freeze_transfers_to_freezer(self):
        grocy, state = _grocy(), _state()
        result = await apply_action(grocy, state, PantryAction(FREEZE, "chicken"), state.product(1))
        grocy.transfer.assert_awaited_once_with(1, 2, 10, 20)
        self.assertEqual(result.transaction_id, "tx-transfer")

    async def test_add_unknown_item_creates_a_product(self):
        grocy, state = _grocy(), _state()
        result = await apply_action(grocy, state, PantryAction(ADD, "bananas", 3), None)
        grocy.add_stock.assert_awaited_once_with(99, 3, price=None)
        self.assertEqual(result.line, "🛒 +3 Banana (3 on hand)")

    async def test_unknown_item_for_consume(self):
        result = await apply_action(_grocy(), _state(), PantryAction(CONSUME, "caviar"), None)
        self.assertIn("don't have", result.line)


class PutAwayTests(PantryTestCase):
    async def test_plans_and_puts_away_known_and_new_items(self):
        grocy, state = _grocy(), _state()
        catalog = [{"sku": "1", "name": "Organic Bananas", "category": "Fresh Fruits & Veggies", "subcategory": "Fruits", "price": 0.29, "image_url": None}]
        crossed_off = [
            {"item_id": "a", "crossed_off_at": "t1", "list_id": "L", "text": "eggs"},
            {"item_id": "b", "crossed_off_at": "t1", "list_id": "L", "text": "bananas"},
        ]

        plan = plan_put_away(crossed_off, state, catalog)
        self.assertEqual(plan[0].product["id"], 2)
        self.assertIsNone(plan[1].product)
        self.assertEqual(plan[1].tj_item["sku"], "1")
        self.assertEqual(plan[1].label(), "bananas → new: Organic Bananas")

        lines, transactions = await put_away(grocy, state, plan, "Sam")
        self.assertEqual(lines, ["• Egg", "• Banana _(new)_"])
        self.assertEqual(transactions, ["tx-add", "tx-add"])
        self.assertEqual(state.amount(2), 13)
        grocy.add_stock.assert_any_await(99, 1, price=0.29)


class RecipeTests(PantryTestCase):
    def test_recipe_consumption_uses_counts_and_skips_missing(self):
        state = _state()
        rows = recipe_consumption(
            ["2 lbs boneless chicken thighs", "3 large eggs", "1 cup heavy cream", "kosher salt"],
            state,
        )
        self.assertEqual(
            [(row["product"]["name"], row["amount"]) for row in rows],
            [("Chicken thigh", 1), ("Egg", 3.0), ("Salt", 1)],
        )

    def test_in_pantry_ingredients(self):
        state = _state(stock={2: 6})
        self.assertEqual(in_pantry_ingredients(["3 Eggs", "1 cup milk"], state), {"3 eggs"})


class ExpiringItemsTests(unittest.TestCase):
    def test_flattens_dedupes_and_sorts(self):
        volatile = {
            "due_products": [
                {"product_id": 1, "amount": 2, "best_before_date": "2026-10-05", "product": {"name": "Chicken thigh"}},
            ],
            "overdue_products": [
                {"product_id": 2, "amount": 1, "best_before_date": "2026-10-02", "product": {"name": "Ground beef"}},
            ],
            "expired_products": [
                {"product_id": 2, "amount": 1, "best_before_date": "2026-10-02", "product": {"name": "Ground beef"}},
            ],
        }
        items = expiring_items(volatile)
        self.assertEqual([item["name"] for item in items], ["Ground beef", "Chicken thigh"])
        self.assertTrue(items[0]["overdue"])
        self.assertFalse(items[1]["overdue"])


if __name__ == "__main__":
    unittest.main()
