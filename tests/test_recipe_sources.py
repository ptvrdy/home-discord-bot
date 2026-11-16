import unittest

from services.recipe_sources import SourceFix, looks_like_url, plan_source_fix, unlabelled_sites

YOUTUBE = "https://www.youtube.com/watch?v=okZl55RUJbI"


class LooksLikeUrlTests(unittest.TestCase):
    def test_http_and_https(self):
        self.assertTrue(looks_like_url("https://example.com"))
        self.assertTrue(looks_like_url("  HTTP://example.com"))

    def test_not_urls(self):
        for text in ["Handwritten from Sarah", "youtube.com/watch", "", None, "ftp://x"]:
            with self.subTest(text=text):
                self.assertFalse(looks_like_url(text))


class PlanSourceFixTests(unittest.TestCase):
    def test_a_saved_youtube_link_with_no_name_gets_labelled_youtube(self):
        # "From **the original recipe**" -> "From **YouTube**"
        self.assertEqual(plan_source_fix(YOUTUBE, None), SourceFix("YouTube", YOUTUBE))

    def test_a_blank_name_counts_as_no_name(self):
        self.assertEqual(plan_source_fix(YOUTUBE, "  "), SourceFix("YouTube", YOUTUBE))

    def test_a_link_stuck_in_the_name_slot_is_moved_to_the_link_slot(self):
        # The real "Easy Corn on the Cob" case: the raw URL was the card's "source".
        self.assertEqual(plan_source_fix("", YOUTUBE), SourceFix("YouTube", YOUTUBE))
        self.assertEqual(plan_source_fix(None, YOUTUBE), SourceFix("YouTube", YOUTUBE))

    def test_a_link_in_the_name_slot_keeps_an_existing_real_link(self):
        other = "https://youtu.be/abc"
        self.assertEqual(plan_source_fix(other, YOUTUBE), SourceFix("YouTube", other))

    def test_an_unrecognised_site_in_the_name_slot_still_gets_its_link_restored(self):
        site = "https://www.somenewblog.example/tuna-salad/"
        self.assertEqual(plan_source_fix("", site), SourceFix(None, site))

    def test_a_name_someone_chose_is_never_overwritten(self):
        for name in ["Hand-entered", "Handwritten from Sarah", "TikTok", "New York Times Cooking", "YouTube"]:
            with self.subTest(name=name):
                self.assertIsNone(plan_source_fix(YOUTUBE, name))

    def test_a_link_from_an_unknown_site_with_no_name_is_left_alone(self):
        self.assertIsNone(plan_source_fix("https://www.somenewblog.example/tuna-salad/", None))

    def test_nothing_to_fix(self):
        self.assertIsNone(plan_source_fix("", None))
        self.assertIsNone(plan_source_fix("", ""))

    def test_running_it_again_on_its_own_result_changes_nothing(self):
        # Idempotent: /fix_sources can be re-run safely.
        for url, name in [(YOUTUBE, None), ("", YOUTUBE), ("https://example.com/x", "https://example.com/x")]:
            with self.subTest(url=url, name=name):
                fix = plan_source_fix(url, name)
                self.assertIsNone(plan_source_fix(fix.source_url, fix.source_name))


class UnlabelledSitesTests(unittest.TestCase):
    def test_groups_unknown_sites_busiest_first_and_skips_the_rest(self):
        rows = [
            {"title": "A", "source_url": "https://www.foo.com/a", "source_name": None},
            {"title": "B", "source_url": "https://bar.org/b", "source_name": ""},
            {"title": "C", "source_url": "https://foo.com/c", "source_name": None},
            {"title": "D", "source_url": YOUTUBE, "source_name": None},  # known site
            {"title": "E", "source_url": "https://baz.com/e", "source_name": "Hand-entered"},  # named
            {"title": "F", "source_url": "", "source_name": None},  # no link
        ]
        self.assertEqual(unlabelled_sites(rows), {"foo.com": ["A", "C"], "bar.org": ["B"]})


if __name__ == "__main__":
    unittest.main()
