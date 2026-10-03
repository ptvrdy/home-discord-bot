import unittest
from datetime import date

from services.pantry_embed import (
    build_sync_summary,
    build_what_can_i_make_embed,
    expiring_field_value,
    score_recipes,
)

PRODUCTS = [
    {"id": 1, "name": "Chicken thigh"},
    {"id": 2, "name": "Egg"},
    {"id": 3, "name": "Spinach"},
    {"id": 4, "name": "Feta"},
]


class ScoreRecipesTests(unittest.TestCase):
    def test_ranks_by_share_in_stock_ignoring_staples(self):
        recipes = [
            {"title": "Spinach Omelet", "discord_thread_id": 1,
             "ingredients": ["3 eggs", "1 cup spinach", "2 oz feta", "salt", "black pepper", "1 tbsp olive oil"]},
            {"title": "Chicken Shawarma", "discord_thread_id": 2,
             "ingredients": ["2 lbs chicken thighs", "1 cup yogurt", "2 lemons", "1 tsp cumin"]},
            {"title": "Beef Stew", "discord_thread_id": 3, "ingredients": ["2 lbs beef chuck", "4 carrots"]},
        ]
        stock = {1: 2, 2: 12, 3: 1}  # no feta

        scored = score_recipes(recipes, PRODUCTS, {}, stock)

        self.assertEqual([result["title"] for result in scored], ["Spinach Omelet", "Chicken Shawarma"])
        omelet = scored[0]
        self.assertEqual((omelet["have"], omelet["total"]), (2, 3))
        self.assertEqual(omelet["missing"], ["feta"])

    def test_expiring_bonus_breaks_ties(self):
        recipes = [
            {"title": "A", "discord_thread_id": 1, "ingredients": ["eggs", "bacon"]},
            {"title": "B", "discord_thread_id": 2, "ingredients": ["chicken thighs", "rice noodles"]},
        ]
        scored = score_recipes(recipes, PRODUCTS, {}, {1: 1, 2: 1}, expiring_ids={1})
        self.assertEqual(scored[0]["title"], "B")
        self.assertEqual(scored[0]["uses_expiring"], ["Chicken thigh"])

    def test_embed_lists_suggestions_with_thread_links(self):
        embed = build_what_can_i_make_embed(
            [{"title": "Omelet", "discord_thread_id": 55, "score": 1, "have": 3, "total": 3, "missing": [], "uses_expiring": []}]
        )
        self.assertIn("<#55>", embed.description)
        self.assertIn("you have everything", embed.description)

    def test_empty_embed(self):
        self.assertIn("/put_away", build_what_can_i_make_embed([]).description)


class ExpiringFieldTests(unittest.TestCase):
    def test_formats_days(self):
        today = date(2026, 10, 3)
        text = expiring_field_value(
            [
                {"name": "Ground beef", "amount": 1, "best_before_date": "2026-10-01", "overdue": True},
                {"name": "Chicken thigh", "amount": 2, "best_before_date": "2026-10-04", "overdue": False},
            ],
            today,
        )
        self.assertEqual(text, "🔴 Ground beef — 2d overdue\n🟠 2× Chicken thigh — tomorrow")

    def test_nothing_expiring(self):
        self.assertIsNone(expiring_field_value([], date(2026, 10, 3)))


class SyncSummaryTests(unittest.TestCase):
    def test_mentions_returning_and_new(self):
        text = build_sync_summary(
            {"added": 5, "price_changed": 2, "discontinued": 1, "returned_skus": ["9"]},
            2519,
            ["Pumpkin bread"],
            [{"name": "Ube Mochi"}],
        )
        self.assertIn("2,519", text)
        self.assertIn("Back at TJ's", text)
        self.assertIn("Ube Mochi", text)


if __name__ == "__main__":
    unittest.main()
