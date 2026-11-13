import gzip
import json
import unittest
from unittest.mock import patch

import httpx

from services import scraper
from services.scraper import fetch_recipe_html, scrape_recipe

NYT_URL = "https://cooking.nytimes.com/recipes/1015819-chocolate-chip-cookies"

RECIPE_HTML = """<!DOCTYPE html><html><head><script type="application/ld+json">{data}</script>
</head><body></body></html>"""

RECIPE_JSON_LD = {
    "@context": "https://schema.org",
    "@type": "Recipe",
    "name": "Best Chocolate Chip Cookies",
    "recipeIngredient": ["2 cups cake flour (8 ½ ounces)", "1 teaspoon baking soda"],
    "recipeInstructions": [
        {"@type": "HowToStep", "text": "Sift the flours together."},
        {"@type": "HowToStep", "text": "Bake until golden."},
    ],
    "totalTime": "PT45M",
    "recipeYield": "18 cookies",
    "image": "https://static01.nyt.com/images/cookies.jpg",
}


def _page() -> str:
    # ensure_ascii=False so the page holds a real multi-byte UTF-8 character,
    # as NYT's does, rather than a `½` escape that decodes trivially.
    return RECIPE_HTML.format(data=json.dumps(RECIPE_JSON_LD, ensure_ascii=False))


def _gzipped_response(html: str) -> httpx.Response:
    """What NYT Cooking sends: a gzip body plus Content-Encoding: gzip, even
    though the request never offered Accept-Encoding."""
    return httpx.Response(
        200,
        headers={"content-encoding": "gzip", "content-type": "text/html; charset=utf-8"},
        content=gzip.compress(html.encode("utf-8")),
        request=httpx.Request("GET", NYT_URL),
    )


class FetchRecipeHtmlTests(unittest.TestCase):
    def test_decompresses_a_gzip_reply(self):
        # Regression: recipe_scrapers.scrape_me() used urllib, which doesn't
        # decompress, so NYT's gzip body crashed with UnicodeDecodeError
        # (0x8b = the second byte of the gzip header) on every import.
        html = _page()
        with patch.object(scraper.httpx, "get", return_value=_gzipped_response(html)):
            self.assertEqual(fetch_recipe_html(NYT_URL), html)

    def test_decodes_non_ascii_text_correctly(self):
        with patch.object(scraper.httpx, "get", return_value=_gzipped_response(_page())):
            self.assertIn("½", fetch_recipe_html(NYT_URL))

    def test_http_errors_raise_so_the_command_can_offer_manual_entry(self):
        blocked = httpx.Response(403, request=httpx.Request("GET", NYT_URL))
        with patch.object(scraper.httpx, "get", return_value=blocked):
            with self.assertRaises(httpx.HTTPStatusError):
                fetch_recipe_html(NYT_URL)

    def test_sends_the_librarys_headers_follows_redirects_and_times_out(self):
        with patch.object(scraper.httpx, "get", return_value=_gzipped_response(_page())) as get:
            fetch_recipe_html(NYT_URL)

        _, kwargs = get.call_args
        self.assertEqual(kwargs["headers"], scraper.SCRAPER_HEADERS)
        self.assertTrue(kwargs["follow_redirects"])
        self.assertEqual(kwargs["timeout"], scraper.FETCH_TIMEOUT_SECONDS)


class ScrapeRecipeTests(unittest.TestCase):
    def test_imports_a_nyt_recipe_from_a_gzip_reply(self):
        no_extra_times = {"prep_time": None, "cook_time": None, "total_time": None}
        with patch.object(scraper.httpx, "get", return_value=_gzipped_response(_page())), \
             patch.object(scraper, "fetch_nyt_times", return_value=no_extra_times):
            recipe = scrape_recipe(NYT_URL)

        self.assertEqual(recipe.title, "Best Chocolate Chip Cookies")
        self.assertEqual(len(recipe.ingredients), 2)
        self.assertIn("½", recipe.ingredients[0])
        self.assertIn("Sift the flours together.", recipe.instructions)
        self.assertEqual(recipe.yields, "18 cookies")
        self.assertEqual(recipe.total_minutes, 45)
        self.assertEqual(recipe.source_name, "New York Times Cooking")
        self.assertEqual(recipe.source_url, NYT_URL)

    def test_a_blocked_page_raises_rather_than_returning_an_empty_recipe(self):
        blocked = httpx.Response(403, request=httpx.Request("GET", NYT_URL))
        with patch.object(scraper.httpx, "get", return_value=blocked):
            with self.assertRaises(httpx.HTTPStatusError):
                scrape_recipe(NYT_URL)


if __name__ == "__main__":
    unittest.main()
