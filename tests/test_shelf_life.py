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


class ExportTests(unittest.TestCase):
    def test_export_matches_shelf_life_for(self):
        # The Grocy plugin applies the exported rules first-match-wins; that
        # has to give the same answer as Rosie's own lookup for every rule.
        for rule in shelf_life.rules_for_export():
            expected = shelf_life_for(rule["category"], rule["subcategory"])
            self.assertEqual((rule["location"], rule["days"], rule["freezer_days"]),
                             (expected["location"], expected["days"], expected["freezer_days"]))

    def test_export_respects_the_produce_switch(self):
        produce = lambda: next(r for r in shelf_life.rules_for_export() if r["category"] == "Fresh Fruits & Veggies")
        self.assertEqual(produce()["days"], -1)
        original = shelf_life.TRACK_PRODUCE
        shelf_life.TRACK_PRODUCE = True
        try:
            self.assertEqual(produce()["days"], 5)
        finally:
            shelf_life.TRACK_PRODUCE = original

    def test_published_for_the_plugin(self):
        import json
        from unittest.mock import patch
        from services import pantry

        with patch("services.pantry.set_state") as set_state:
            pantry.publish_shelf_life_rules()
        key, value = set_state.call_args.args
        self.assertEqual(key, "shelf_life_rules")  # the plugin reads exactly this key
        self.assertEqual(json.loads(value), shelf_life.rules_for_export())


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
