import unittest

from services.wishlist_scraper import FALLBACK_TITLE_LIMIT, get_site_name, parse_wishlist_metadata


class ParseWishlistMetadataTests(unittest.TestCase):
    def test_prefers_og_title(self):
        html = """
        <html><head>
            <title>Fallback Title</title>
            <meta property="og:title" content="Nice Dish Rack">
        </head></html>
        """
        result = parse_wishlist_metadata(html, "https://example.com/item")
        self.assertEqual(result["title"], "Nice Dish Rack")

    def test_falls_back_to_html_title_tag(self):
        html = "<html><head><title>Plain Page Title</title></head></html>"
        result = parse_wishlist_metadata(html, "https://example.com/item")
        self.assertEqual(result["title"], "Plain Page Title")

    def test_falls_back_to_site_and_path_when_no_title_at_all(self):
        html = "<html><head></head></html>"
        result = parse_wishlist_metadata(html, "https://www.example.com/products/dish-rack")
        self.assertEqual(result["title"], "example.com — dish-rack")

    def test_fallback_title_is_never_the_full_raw_url(self):
        # A long tracking-parameter URL (like a real-world Etsy search-result
        # link) must not become the embed title as-is - Discord rejects
        # embed titles over 256 characters, which left /want hanging forever
        # with no error surfaced.
        long_url = (
            "https://www.etsy.com/listing/4427242551/modern-perpetual-wall-calendar-1970s"
            "?ls=s&ga_order=most_relevant&ga_search_type=all&ga_view_type=gallery"
            "&ga_search_query=perpetual+ring+wall+calendar+yellow&ref=sr_gallery-1-3"
        )
        html = "<html><head></head></html>"
        result = parse_wishlist_metadata(html, long_url)
        self.assertLessEqual(len(result["title"]), FALLBACK_TITLE_LIMIT)
        self.assertNotIn("ga_search_query", result["title"])

    def test_extracts_og_image(self):
        html = '<html><head><meta property="og:image" content="https://example.com/pic.jpg"></head></html>'
        result = parse_wishlist_metadata(html, "https://example.com/item")
        self.assertEqual(result["image_url"], "https://example.com/pic.jpg")

    def test_no_image_when_absent(self):
        html = "<html><head></head></html>"
        result = parse_wishlist_metadata(html, "https://example.com/item")
        self.assertIsNone(result["image_url"])

    def test_extracts_price(self):
        html = '<html><head><meta property="product:price:amount" content="24.99"></head></html>'
        result = parse_wishlist_metadata(html, "https://example.com/item")
        self.assertEqual(result["price"], "24.99")

    def test_no_price_when_absent(self):
        html = "<html><head></head></html>"
        result = parse_wishlist_metadata(html, "https://example.com/item")
        self.assertIsNone(result["price"])


class GetSiteNameTests(unittest.TestCase):
    def test_strips_www_prefix(self):
        self.assertEqual(get_site_name("https://www.target.com/p/dish-rack"), "target.com")

    def test_leaves_bare_domain_untouched(self):
        self.assertEqual(get_site_name("https://example.com/thing"), "example.com")


if __name__ == "__main__":
    unittest.main()
