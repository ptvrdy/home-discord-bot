import gzip
import json
import unittest
from unittest.mock import patch

import httpx

from services import scraper
from services.scraper import fetch_recipe_html, get_source_name, scrape_recipe

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


class GetSourceNameTests(unittest.TestCase):
    def test_youtube_links_in_every_common_form(self):
        for url in [
            "https://www.youtube.com/watch?v=okZl55RUJbI",
            "https://youtube.com/watch?v=abc",
            "https://m.youtube.com/watch?v=abc",
            "https://music.youtube.com/watch?v=abc",
            "https://youtu.be/okZl55RUJbI",
            "https://www.youtube.com/shorts/abc123",
        ]:
            with self.subTest(url=url):
                self.assertEqual(get_source_name(url), "YouTube")

    def test_tiktok_including_short_links(self):
        self.assertEqual(get_source_name("https://www.tiktok.com/@chef/video/1"), "TikTok")
        self.assertEqual(get_source_name("https://vm.tiktok.com/ZMabc/"), "TikTok")

    def test_the_recipe_sites_it_already_knew_still_work_with_or_without_www(self):
        self.assertEqual(get_source_name("https://cooking.nytimes.com/recipes/1"), "New York Times Cooking")
        self.assertEqual(get_source_name("https://www.allrecipes.com/recipe/1"), "AllRecipes")
        self.assertEqual(get_source_name("https://allrecipes.com/recipe/1"), "AllRecipes")
        self.assertEqual(get_source_name("https://www.seriouseats.com/x"), "Serious Eats")

    def test_the_food_blogs_from_the_household_recipe_box(self):
        for url, name in [
            ("https://www.organizeyourselfskinny.com/tuna-salad/", "Organize Yourself Skinny"),
            ("https://sallysbakingaddiction.com/sandwich-bread/", "Sally's Baking Addiction"),
            ("https://www.damndelicious.net/quinoa-chili/", "Damn Delicious"),
            ("https://thecountrycook.net/marry-me-chicken/", "The Country Cook"),
            ("https://www.thetoastykitchen.com/brown-gravy/", "The Toasty Kitchen"),
        ]:
            with self.subTest(url=url):
                self.assertEqual(get_source_name(url), name)

    def test_unknown_sites_have_no_name(self):
        self.assertIsNone(get_source_name("https://www.somenewblog.example/tuna-salad/"))

    def test_a_lookalike_domain_is_not_mistaken_for_youtube(self):
        for url in ["https://notyoutube.com/watch", "https://youtube.com.evil.example/watch", "https://example.com/youtube.com"]:
            with self.subTest(url=url):
                self.assertIsNone(get_source_name(url))

    def test_the_rest_of_nytimes_is_not_nyt_cooking(self):
        self.assertIsNone(get_source_name("https://www.nytimes.com/2026/some-article"))

    def test_junk_input(self):
        self.assertIsNone(get_source_name(""))
        self.assertIsNone(get_source_name("not a url"))
        self.assertIsNone(get_source_name("youtube.com/watch?v=abc"))  # no scheme


if __name__ == "__main__":
    unittest.main()
