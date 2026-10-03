import unittest
from datetime import date
from unittest.mock import AsyncMock, MagicMock

from services.recalls import fetch_recent_recalls, format_recall_alert, match_recalls

FRIED_RICE_RECALL = {
    "recall_number": "F-1234-2026",
    "report_date": "20260401",
    "classification": "Class II",
    "product_description": "Item 5650233 Trader Joe's Vegetable Fried Rice, net wt. 1lb per bag. Retail bag UPC 00521482.",
    "reason_for_recall": "Foreign objects are glass varying in size.",
}


class MatchRecallsTests(unittest.TestCase):
    def test_matches_by_sku_embedded_in_upc(self):
        matches = match_recalls([FRIED_RICE_RECALL], [{"name": "Fried rice", "tj_name": None, "tj_sku": "052148"}])
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["product"], "Fried rice")

    def test_matches_by_full_tj_name(self):
        matches = match_recalls(
            [FRIED_RICE_RECALL],
            [{"name": "Fried rice", "tj_name": "Vegetable Fried Rice", "tj_sku": "999999"}],
        )
        self.assertEqual(len(matches), 1)

    def test_generic_names_alone_do_not_alert(self):
        matches = match_recalls([FRIED_RICE_RECALL], [{"name": "Rice", "tj_name": None, "tj_sku": None}])
        self.assertEqual(matches, [])

    def test_format(self):
        match = match_recalls([FRIED_RICE_RECALL], [{"name": "Fried rice", "tj_name": None, "tj_sku": "052148"}])[0]
        text = format_recall_alert(match)
        self.assertIn("Fried rice", text)
        self.assertIn("2026-04-01", text)
        self.assertIn("glass", text)


class FetchRecallsTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_matches_is_empty_not_an_error(self):
        client = AsyncMock()
        client.get.return_value = MagicMock(status_code=404)
        self.assertEqual(await fetch_recent_recalls(date(2026, 10, 3), client=client), [])
        params = client.get.await_args.kwargs["params"]
        self.assertIn("Trader Joe's", params["search"])
        self.assertIn("[20260804 TO 20261003]", params["search"])


if __name__ == "__main__":
    unittest.main()
