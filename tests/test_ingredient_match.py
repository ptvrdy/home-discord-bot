import unittest

from services.ingredient_match import (
    best_product_match,
    best_tj_match,
    display_name,
    match_score,
    normalize_item,
    parse_quantity,
)


PRODUCTS = [
    {"id": 1, "name": "Chicken thigh"},
    {"id": 2, "name": "Onion"},
    {"id": 3, "name": "Garlic"},
    {"id": 4, "name": "Egg"},
    {"id": 5, "name": "Chicken breast"},
    {"id": 6, "name": "Oat milk"},
    {"id": 7, "name": "Olive oil"},
]


class NormalizeItemTests(unittest.TestCase):
    def test_strips_amounts_units_prep_words_and_parentheticals(self):
        self.assertEqual(normalize_item("2 lbs boneless, skinless chicken thighs (about 6)"), "chicken thigh")

    def test_drops_trailing_prep_after_comma(self):
        self.assertEqual(normalize_item("1 yellow onion, diced"), "yellow onion")

    def test_singularizes(self):
        self.assertEqual(normalize_item("3 large eggs"), "egg")
        self.assertEqual(normalize_item("2 tomatoes"), "tomato")
        self.assertEqual(normalize_item("berries"), "berry")

    def test_applies_synonyms(self):
        self.assertEqual(normalize_item("4 scallions, sliced"), "green onion")

    def test_nothing_meaningful_returns_empty(self):
        self.assertEqual(normalize_item("2 cups"), "")


class ParseQuantityTests(unittest.TestCase):
    def test_count_without_unit(self):
        self.assertEqual(parse_quantity("3 large eggs"), (3.0, None))

    def test_amount_with_unit(self):
        number, unit = parse_quantity("2 lbs chicken thighs")
        self.assertEqual(number, 2.0)
        self.assertIsNotNone(unit)

    def test_fractions(self):
        self.assertEqual(parse_quantity("1/2 cup milk")[0], 0.5)
        self.assertEqual(parse_quantity("1 1/2 cups flour")[0], 1.5)
        self.assertEqual(parse_quantity("1 ½ tbsp olive oil")[0], 1.5)

    def test_word_numbers(self):
        self.assertEqual(parse_quantity("two avocados"), (2.0, None))

    def test_no_quantity(self):
        self.assertEqual(parse_quantity("salt to taste"), (None, None))


class MatchingTests(unittest.TestCase):
    def test_head_nouns_must_agree(self):
        self.assertEqual(match_score("1 tsp garlic powder", "Garlic"), 0.0)
        self.assertEqual(match_score("chicken thighs", "Chicken breast"), 0.0)

    def test_exact_generic_match_scores_one(self):
        self.assertEqual(match_score("2 lbs boneless chicken thighs", "Chicken thigh"), 1.0)

    def test_more_generic_product_still_matches_specific_ingredient(self):
        self.assertGreater(match_score("1 red onion", "Onion"), 0.6)

    def test_best_product_match_prefers_the_right_product(self):
        self.assertEqual(best_product_match("boneless chicken thighs", PRODUCTS).item["id"], 1)
        self.assertEqual(best_product_match("3 large eggs", PRODUCTS).item["id"], 4)
        self.assertEqual(best_product_match("2 tbsp extra virgin olive oil", PRODUCTS).item["id"], 7)
        self.assertIsNone(best_product_match("1 tsp garlic powder", PRODUCTS))

    def test_partial_match_is_low_confidence(self):
        match = best_product_match("milk", PRODUCTS)
        self.assertEqual(match.item["id"], 6)
        self.assertLess(match.score, 0.6)

    def test_learned_alias_wins(self):
        match = best_product_match("milk", PRODUCTS, aliases={"milk": 6})
        self.assertEqual(match.score, 1.0)
        self.assertEqual(match.item["id"], 6)

    def test_best_tj_match_needs_every_query_word(self):
        catalog = [
            {"name": "Organic Boneless Skinless Chicken Thighs"},
            {"name": "Chicken Thigh Kebabs"},
            {"name": "Organic Large Brown Eggs"},
            {"name": "Egg White Salad"},
        ]
        self.assertEqual(best_tj_match("chicken thighs", catalog).item["name"], "Organic Boneless Skinless Chicken Thighs")
        self.assertEqual(best_tj_match("eggs", catalog).item["name"], "Organic Large Brown Eggs")
        self.assertIsNone(best_tj_match("pork chops", catalog))

    def test_display_name(self):
        self.assertEqual(display_name("2 lbs boneless chicken thighs"), "Chicken thigh")


if __name__ == "__main__":
    unittest.main()
