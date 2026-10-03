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


# Real titles from the live Trader Joe's catalog that tripped up a naive
# "shortest title wins" matcher.
REAL_TJ_CATALOG = [
    {"name": "Marshmallow Eggs", "category": "Snacks & Sweets", "subcategory": "Candies & Cookies"},
    {"name": "Pasture Raised Large Brown Eggs", "category": "Dairy & Eggs", "subcategory": "Eggs"},
    {"name": "Fig Butter", "category": "For the Pantry", "subcategory": "Nut Butters & Fruit Spreads"},
    {"name": "Cultured Salted Butter", "category": "Dairy & Eggs", "subcategory": "Butter"},
    {"name": "Energy Bar Peanut Butter", "category": "Snacks & Sweets", "subcategory": "Bars, Jerky &… Surprises"},
    {"name": "Peanut Butter Creamy Salted", "category": "For the Pantry", "subcategory": "Nut Butters & Fruit Spreads"},
    {"name": "Egg Nog Greek Yogurt", "category": "Dairy & Eggs", "subcategory": "Yogurt, etc."},
    {"name": "Greek Lowfat Yogurt Plain", "category": "Dairy & Eggs", "subcategory": "Yogurt, etc."},
    {"name": "Shredded Mozzarella Cheese", "category": "Cheese", "subcategory": "Slices, Shreds, Crumbles"},
    {"name": "Crispy Garlic", "category": "Snacks & Sweets", "subcategory": "Chips, Crackers & Crunchy Bites"},
    {"name": "Orange Peach Mango Juice", "category": "Juices & More", "subcategory": None},
    {"name": "100% Orange Juice No Pulp", "category": "Juices & More", "subcategory": None},
    {"name": "Organic Milk A2/A2", "category": "Dairy & Eggs", "subcategory": "Milk & Cream"},
    {"name": "Organic Coconut Milk", "category": "For the Pantry", "subcategory": "Packaged Fish, Meat, Fruit & Veg"},
    {"name": "Petite Peas", "category": "From The Freezer", "subcategory": "Fruit & Vegetables"},
]


class RealCatalogTests(unittest.TestCase):
    def assertMatches(self, query, expected):
        match = best_tj_match(query, REAL_TJ_CATALOG)
        self.assertEqual(match.item["name"] if match else None, expected, query)

    def test_plain_staples_beat_flavored_and_candy_versions(self):
        self.assertMatches("eggs", "Pasture Raised Large Brown Eggs")
        self.assertMatches("butter", "Cultured Salted Butter")
        self.assertMatches("greek yogurt", "Greek Lowfat Yogurt Plain")
        self.assertMatches("orange juice", "100% Orange Juice No Pulp")
        self.assertMatches("milk", "Organic Milk A2/A2")

    def test_trailing_descriptors_and_cheese(self):
        self.assertMatches("peanut butter", "Peanut Butter Creamy Salted")
        self.assertMatches("shredded mozzarella", "Shredded Mozzarella Cheese")
        self.assertMatches("frozen peas", "Petite Peas")

    def test_snack_only_matches_are_rejected(self):
        self.assertMatches("garlic", None)


class RecipeLineTests(unittest.TestCase):
    def test_or_lines_match_either_option(self):
        products = [{"id": 1, "name": "Pickle"}, {"id": 2, "name": "Lettuce"}, {"id": 3, "name": "Linguine"}]
        self.assertEqual(best_product_match("1 tbs relish or pickles", products).item["id"], 1)
        self.assertEqual(best_product_match("Red or green leaf lettuce, for serving", products).item["id"], 2)
        self.assertEqual(best_product_match("1 pound linguine or other long pasta", products).item["id"], 3)
        self.assertEqual(normalize_item("Red or green leaf lettuce, for serving"), "green leaf lettuce")

    def test_hot_sauce_and_hyphens(self):
        self.assertEqual(normalize_item("½ teaspoon hot sauce"), "hot sauce")
        self.assertEqual(normalize_item("1 pound extra-large (16 to 20 count) shrimp, shelled"), "shrimp")
        self.assertEqual(normalize_item("¼ cup extra-virgin olive oil, plus more"), "virgin olive oil")

    def test_cheese_suffix(self):
        self.assertEqual(normalize_item("1 cup shredded cheddar cheese"), "cheddar")
        self.assertEqual(normalize_item("8 oz cream cheese, softened"), "cream cheese")


if __name__ == "__main__":
    unittest.main()
