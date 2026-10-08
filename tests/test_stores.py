import unittest
from unittest.mock import patch

from config.stores import is_grocery_list, is_trader_joes, match_store, store_lists


class StoreTests(unittest.TestCase):
    def test_only_grocery_lists_feed_the_pantry(self):
        for name in ("Trader Joe's", "urban market", "Whole Foods", "Farmers Market", "Ideal Food Basket"):
            self.assertTrue(is_grocery_list(name), name)
        for name in ("CVS", "Marshalls", "Liquor Store", "Rosie Test"):
            self.assertFalse(is_grocery_list(name), name)

    def test_trader_joes_is_the_default(self):
        self.assertTrue(is_trader_joes(None))
        self.assertTrue(is_trader_joes("Trader Joe's"))
        self.assertFalse(is_trader_joes("Urban Market"))

    def test_match_store(self):
        self.assertEqual(match_store("urban market"), "Urban Market")
        self.assertEqual(match_store("trader joes"), "Trader Joe's")
        self.assertEqual(match_store("TJs"), "Trader Joe's")
        self.assertIsNone(match_store("grandma's"))

    def test_env_override_for_a_dev_bot(self):
        with patch.dict("os.environ", {"PANTRY_STORE_LISTS": "Rosie Test, Urban Market", "PANTRY_TJ_LIST": "Rosie Test"}):
            self.assertEqual(store_lists(), ["Rosie Test", "Urban Market"])
            self.assertTrue(is_grocery_list("Rosie Test"))
            self.assertTrue(is_trader_joes("Rosie Test"))
            self.assertFalse(is_grocery_list("Trader Joe's"))


if __name__ == "__main__":
    unittest.main()
