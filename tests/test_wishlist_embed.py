import unittest

from services.wishlist_embed import BOUGHT_COLOR, WISHLIST_COLOR, build_wishlist_item_embed


class BuildWishlistItemEmbedTests(unittest.TestCase):
    def test_shows_title_and_links_to_url(self):
        embed = build_wishlist_item_embed(
            "Dish Drying Rack", "https://example.com/item", None, None, "Peyton"
        )
        self.assertIn("Dish Drying Rack", embed.title)
        self.assertEqual(embed.url, "https://example.com/item")

    def test_open_item_uses_wishlist_color_and_added_by_footer(self):
        embed = build_wishlist_item_embed(
            "Dish Drying Rack", "https://example.com/item", None, None, "Peyton"
        )
        self.assertEqual(embed.color.value, WISHLIST_COLOR)
        self.assertIn("Added by Peyton", embed.footer.text)

    def test_bought_item_uses_bought_color_and_bought_by_footer(self):
        embed = build_wishlist_item_embed(
            "Dish Drying Rack", "https://example.com/item", None, None, "Peyton", bought_by="Joe"
        )
        self.assertEqual(embed.color.value, BOUGHT_COLOR)
        self.assertIn("Bought by Joe", embed.footer.text)
        self.assertIn("✅", embed.title)

    def test_price_field_shown_when_present(self):
        embed = build_wishlist_item_embed(
            "Dish Drying Rack", "https://example.com/item", None, "24.99", "Peyton"
        )
        fields = {field.name: field.value for field in embed.fields}
        self.assertEqual(fields["Price"], "24.99")

    def test_no_price_field_when_absent(self):
        embed = build_wishlist_item_embed(
            "Dish Drying Rack", "https://example.com/item", None, None, "Peyton"
        )
        self.assertNotIn("Price", {field.name for field in embed.fields})

    def test_site_field_derived_from_url(self):
        embed = build_wishlist_item_embed(
            "Dish Drying Rack", "https://www.target.com/p/item", None, None, "Peyton"
        )
        fields = {field.name: field.value for field in embed.fields}
        self.assertEqual(fields["Site"], "target.com")

    def test_thumbnail_set_when_image_present(self):
        embed = build_wishlist_item_embed(
            "Dish Drying Rack", "https://example.com/item", "https://example.com/pic.jpg", None, "Peyton"
        )
        self.assertEqual(embed.thumbnail.url, "https://example.com/pic.jpg")

    def test_no_thumbnail_when_image_absent(self):
        embed = build_wishlist_item_embed(
            "Dish Drying Rack", "https://example.com/item", None, None, "Peyton"
        )
        self.assertEqual(embed.thumbnail.url, None)


if __name__ == "__main__":
    unittest.main()
