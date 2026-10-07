import unittest
from datetime import date

from services.pantry_embed import (
    autocomplete_order,
    build_sync_summary,
    chunk_lines,
    cook_this_week_field_value,
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


def _scored(title, thread, have, total, missing=(), uses_expiring=()):
    return {"title": title, "discord_thread_id": thread, "score": have / total, "have": have,
            "total": total, "missing": list(missing), "uses_expiring": list(uses_expiring)}


class CookThisWeekTests(unittest.TestCase):
    def test_picks_mostly_in_stock_or_expiring_recipes_up_to_three(self):
        scored = [
            _scored("Shawarma", 1, 4, 5, ["lemon"], ["Chicken thigh"]),
            _scored("Omelet", 2, 3, 3),
            _scored("Tacos", 3, 2, 3, ["salsa"]),
            _scored("Pad Thai", 4, 2, 3, ["peanut"]),
            _scored("Stew", 5, 1, 4, ["carrot", "potato", "beef"]),  # only 25% in stock
        ]
        self.assertEqual(
            cook_this_week_field_value(scored),
            "• <#1> — have 4/5 · ⏰ uses Chicken thigh\n• <#2> — have everything\n• <#3> — have 2/3",
        )

    def test_a_low_coverage_recipe_still_counts_if_it_uses_something_expiring(self):
        value = cook_this_week_field_value([_scored("Stew", 5, 1, 4, ["a", "b", "c"], ["Ground beef"])])
        self.assertEqual(value, "• <#5> — have 1/4 · ⏰ uses Ground beef")

    def test_nothing_worth_suggesting(self):
        self.assertIsNone(cook_this_week_field_value([_scored("Stew", 5, 1, 4, ["a", "b", "c"])]))
        self.assertIsNone(cook_this_week_field_value([]))


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


class ChunkLinesTests(unittest.TestCase):
    def test_a_whole_pantry_splits_into_messages_without_losing_or_cutting_lines(self):
        lines = [f"• Pantry item number {index} ×{index}" for index in range(400)]
        chunks = chunk_lines(lines)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 2000 for chunk in chunks))
        self.assertEqual("\n".join(chunks).split("\n"), lines)

    def test_short_list_is_one_message(self):
        self.assertEqual(chunk_lines(["a", "b"]), ["a\nb"])
        self.assertEqual(chunk_lines([]), [])


class AutocompleteOrderTests(unittest.TestCase):
    def test_prefix_matches_first_and_capped_at_25(self):
        rows = [{"name": name} for name in ["Eggplant Dip", "Egg", "Brown Eggs", "Scrambled egg bites"]]
        rows += [{"name": f"Egg thing {index:03}"} for index in range(40)]
        ordered = [row["name"] for row in autocomplete_order(rows, "egg")]
        self.assertEqual(len(ordered), 25)
        self.assertEqual(ordered[0], "Egg")
        self.assertNotIn("Brown Eggs", ordered)  # 25 better matches came first

    def test_word_start_beats_middle_of_word(self):
        rows = [{"name": "Veggie Burger"}, {"name": "Scrambled Egg Bites"}]
        self.assertEqual([row["name"] for row in autocomplete_order(rows, "egg")], ["Scrambled Egg Bites", "Veggie Burger"])


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
