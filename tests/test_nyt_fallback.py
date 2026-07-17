import unittest

from services.nyt_fallback import extract_nyt_times, is_nyt_cooking_url


class NytFallbackTests(unittest.TestCase):
    def test_extracts_iso_durations_from_json(self):
        html = '''
        <script type="application/ld+json">
          {"@type": "Recipe", "prepTime": "PT15M", "cookTime": "PT1H", "totalTime": "PT1H15M"}
        </script>
        '''

        self.assertEqual(
            extract_nyt_times(html),
            {
                "prep_time": "15 minutes",
                "cook_time": "1 hour",
                "total_time": "1 hour 15 minutes",
            },
        )

    def test_extracts_visible_time_labels_when_json_has_no_times(self):
        html = "<div>Prep Time: 15 minutes Cook Time: 1 hour Total Time: 1 hour 15 minutes</div>"

        self.assertEqual(
            extract_nyt_times(html),
            {
                "prep_time": "15 minutes",
                "cook_time": "1 hour",
                "total_time": "1 hour 15 minutes",
            },
        )

    def test_recognizes_only_nyt_cooking_hosts(self):
        self.assertTrue(is_nyt_cooking_url("https://cooking.nytimes.com/recipes/123"))
        self.assertFalse(is_nyt_cooking_url("https://www.nytimes.com/recipes/123"))


if __name__ == "__main__":
    unittest.main()
