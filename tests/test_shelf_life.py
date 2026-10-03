import unittest

from config import shelf_life
from config.shelf_life import FREEZER, FRIDGE, PANTRY, guess_category, shelf_life_for


class ShelfLifeTests(unittest.TestCase):
    def test_meat_has_a_shelf_life(self):
        rule = shelf_life_for("Meat, Seafood & Plant-based", "Chicken & Turkey")
        self.assertEqual((rule["location"], rule["days"]), (FRIDGE, 2))

    def test_produce_is_off_until_enabled(self):
        self.assertEqual(shelf_life_for("Fresh Fruits & Veggies", "Veggies")["days"], -1)
        original = shelf_life.TRACK_PRODUCE
        shelf_life.TRACK_PRODUCE = True
        try:
            self.assertEqual(shelf_life_for("Fresh Fruits & Veggies", "Veggies")["days"], 5)
        finally:
            shelf_life.TRACK_PRODUCE = original

    def test_unknown_goes_to_pantry_and_never_expires(self):
        self.assertEqual(shelf_life_for(None, None), {"location": PANTRY, "days": -1, "freezer_days": -1})


class GuessCategoryTests(unittest.TestCase):
    def test_produce_missing_from_tjs_online_catalog(self):
        for words in (["broccoli"], ["lime"], ["cilantro"], ["celery"]):
            self.assertEqual(guess_category(words)[0], "Fresh Fruits & Veggies", words)

    def test_meat_by_head_or_cut(self):
        self.assertEqual(guess_category(["pork", "chop"]), ("Meat, Seafood & Plant-based", "Beef, Pork & Lamb"))
        self.assertEqual(guess_category(["chicken", "thigh"]), ("Meat, Seafood & Plant-based", "Chicken & Turkey"))
        self.assertEqual(guess_category(["salmon", "fillet"]), ("Meat, Seafood & Plant-based", "Fish & Seafood"))

    def test_only_the_head_noun_counts(self):
        self.assertEqual(guess_category(["chicken", "broth"]), (None, None))
        self.assertEqual(guess_category(["garlic", "powder"]), (None, None))

    def test_frozen(self):
        self.assertEqual(guess_category(["pea"], frozen=True), ("From The Freezer", None))
        self.assertEqual(shelf_life_for("From The Freezer", None)["location"], FREEZER)


if __name__ == "__main__":
    unittest.main()
