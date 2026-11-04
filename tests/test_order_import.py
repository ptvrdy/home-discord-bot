import unittest
from pathlib import Path

from services.order_import import clean_title, parse_order_text

FIXTURE = Path(__file__).parent / "fixtures" / "shipt_target_order.txt"


class CleanTitleTests(unittest.TestCase):
    def test_real_target_names(self):
        cases = {
            "Fleischmann&#39;s RapidRise Yeast - 0.25oz/3ct: Gluten-Free, Instant": "Fleischmann's RapidRise Yeast",
            "Golden Sweet Whole Kernel Corn - 15.25oz - Good &#38; Gather&#8482;": "Golden Sweet Whole Kernel Corn",
            "Bounty Select-A-Size Paper Towels - 12 Triple Rolls - 2-Ply - 123 Sheets": "Bounty Select-A-Size Paper Towels",
            "Kikkoman Less Sodium Soy Sauce 10 fl oz: Keto Certified, Vegan": "Kikkoman Less Sodium Soy Sauce",
            "Yough! Farmer's Vegetable Pizza - 13.8 oz": "Yough! Farmer's Vegetable Pizza",
            "Just Bare Lightly Breaded Chicken Breast Bites - Frozen - 24oz": "Just Bare Lightly Breaded Chicken Breast Bites Frozen",
        }
        for raw, expected in cases.items():
            self.assertEqual(clean_title(raw), expected, raw)

    def test_numbers_inside_a_name_are_kept(self):
        # "9g" is the fiber per can, not the package size.
        self.assertEqual(
            clean_title("OLIPOP 9g Fiber Prebiotic Soda Crisp Apple - 4pk/ 12 fl oz Cans"),
            "OLIPOP 9g Fiber Prebiotic Soda Crisp Apple",
        )
        self.assertEqual(
            clean_title("Good Culture 2% Milkfat Simply Cottage Cheese - 16oz: Keto Certified"),
            "Good Culture 2% Milkfat Simply Cottage Cheese",
        )


class ParseOrderTests(unittest.TestCase):
    def setUp(self):
        self.items = parse_order_text(FIXTURE.read_text(encoding="utf-8"))
        self.by_title = {item.title: item for item in self.items}

    def test_every_item_once_with_price_and_quantity(self):
        self.assertEqual(len(self.items), 23)
        self.assertTrue(all(item.received for item in self.items))
        corn = self.by_title["Golden Sweet Whole Kernel Corn"]
        self.assertEqual((corn.price, corn.quantity), (0.59, 2))
        self.assertEqual(self.by_title["Bounty Select-A-Size Paper Towels"].price, 29.99)

    def test_substitutions_are_noted_on_the_item_received(self):
        replaced = {item.title: clean_title(item.replaced) for item in self.items if item.replaced}
        self.assertEqual(replaced, {
            "Buldak Spicy Chicken Carbonara Ramen Noodles": "Buldak Spicy Chicken Stir Fried Ramen Noodles",
            "Kikkoman Less Sodium Soy Sauce": "Kikkoman Soy Sauce",
            "Thomas' Light Multigrain English Muffins": "Thomas' Whole Wheat English Muffins",
        })
        self.assertNotIn("Kikkoman Soy Sauce", self.by_title)  # the original isn't imported

    def test_frozen(self):
        frozen = sorted(item.title for item in self.items if item.frozen)
        self.assertEqual(frozen, [
            "Amylu Foods Chicken Sausage Maple Breakfast Frozen Patties",
            "Just Bare Lightly Breaded Chicken Breast Bites Frozen",
            "Organic Frozen Broccoli Florets",
        ])

    def test_unpriced_item_with_nothing_before_it_is_kept_but_not_received(self):
        items = parse_order_text("Mystery Item - 5oz\n\nApples\n$1.00 unit price\nQty 3\n")
        self.assertEqual([(item.title, item.received) for item in items], [("Mystery Item", False), ("Apples", True)])
        self.assertEqual(items[1].quantity, 3)

    def test_nothing_recognizable(self):
        self.assertEqual(parse_order_text(""), [])


if __name__ == "__main__":
    unittest.main()
