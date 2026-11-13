import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from googleapiclient.errors import HttpError

from services import journal_export
from services.journal_export import describe_due, export_open_tasks, render_open_tasks

NY = ZoneInfo("America/New_York")
NOW = datetime(2026, 11, 12, 12, 0, tzinfo=NY)  # a Thursday


def at(day, hour=9, minute=0):
    return datetime(2026, 11, day, hour, minute, tzinfo=NY)


class DescribeDueTests(unittest.TestCase):
    def test_labels_and_statuses(self):
        self.assertEqual(describe_due(at(12, 15, 30), NOW), ("Today · 3:30 PM", "today"))
        self.assertEqual(describe_due(at(13, 9), NOW), ("Tomorrow · 9:00 AM", "soon"))
        self.assertEqual(describe_due(at(16, 12), NOW), ("Mon · 12:00 PM", "soon"))
        self.assertEqual(describe_due(at(20), NOW), ("Nov 20", "later"))
        self.assertEqual(describe_due(at(10, 18), NOW), ("Overdue · Tue Nov 10", "late"))
        self.assertEqual(describe_due(None, NOW), ("no time set", "none"))

    def test_earlier_today_is_overdue_but_later_today_is_not(self):
        self.assertEqual(describe_due(at(12, 8), NOW)[1], "late")
        self.assertEqual(describe_due(at(12, 18), NOW)[1], "today")

    def test_all_day_tasks_use_the_date(self):
        self.assertEqual(describe_due(date(2026, 11, 12), NOW), ("Today", "today"))
        self.assertEqual(describe_due(date(2026, 11, 11), NOW)[1], "late")


class RenderTests(unittest.TestCase):
    def test_orders_overdue_then_soonest_then_untimed(self):
        tasks = [
            {"name": "later", "due": at(20)},
            {"name": "untimed", "due": None},
            {"name": "late", "due": at(10)},
            {"name": "soon", "due": at(13)},
        ]
        text = render_open_tasks(tasks, NOW)
        order = [text.index(f">{name}<") for name in ("late", "soon", "later", "untimed")]
        self.assertEqual(order, sorted(order))
        self.assertIn("1 overdue", text)
        self.assertIn("has-late", text)

    def test_names_are_escaped(self):
        text = render_open_tasks([{"name": "<b>fix</b> & go", "due": at(13)}], NOW)
        self.assertIn("&lt;b&gt;fix&lt;/b&gt; &amp; go", text)
        self.assertNotIn("<b>", text)

    def test_empty_list_says_caught_up(self):
        text = render_open_tasks([], NOW)
        self.assertIn("all caught up", text)
        self.assertIn("Nothing waiting", text)

    def test_caps_the_list_and_counts_the_rest(self):
        tasks = [{"name": f"t{i}", "due": at(13)} for i in range(10)]
        text = render_open_tasks(tasks, NOW)
        self.assertEqual(text.count("<li "), journal_export.MAX_SHOWN)
        self.assertIn("+3 more", text)

    def test_widget_html_has_no_blank_lines(self):
        text = render_open_tasks([{"name": "a", "due": at(13)}], NOW)
        body = text.split("## 📌 Rosie tasks\n\n", 1)[1].strip()
        self.assertNotIn("\n\n", body)


class FetchAndExportTests(unittest.TestCase):
    rows = [
        {"task_name": "call vet", "event_id": "e1", "calendar_id": "c", "booked_at": "x", "booked_by": "A"},
        {"task_name": "deleted one", "event_id": "e2", "calendar_id": "c", "booked_at": "x", "booked_by": "A"},
        {"task_name": "flaky", "event_id": "e3", "calendar_id": "c", "booked_at": "x", "booked_by": "A"},
    ]

    @staticmethod
    def _http_error(status):
        response = MagicMock()
        response.status = status
        response.reason = "x"
        return HttpError(response, b"")

    def _get_event(self, event_id, calendar_id, service=None):
        if event_id == "e1":
            return {"summary": "call vet", "start": {"dateTime": "2026-11-13T09:00:00-05:00"}, "end": {"dateTime": "2026-11-13T09:30:00-05:00"}}
        if event_id == "e2":
            raise self._http_error(404)
        raise self._http_error(500)

    def test_deleted_events_drop_out_and_failures_keep_the_task(self):
        with patch.object(journal_export, "get_open_booked_tasks", return_value=self.rows), patch.object(
            journal_export, "get_event", side_effect=self._get_event
        ), patch.object(journal_export, "get_service", return_value=object()):
            tasks = journal_export.fetch_open_tasks()
        self.assertEqual([t["name"] for t in tasks], ["call vet", "flaky"])
        self.assertEqual(tasks[0]["due"], at(13, 9))
        self.assertIsNone(tasks[1]["due"])

    def test_no_open_tasks_means_no_calendar_call(self):
        with patch.object(journal_export, "get_open_booked_tasks", return_value=[]), patch.object(
            journal_export, "get_service", side_effect=AssertionError("should not be called")
        ):
            self.assertEqual(journal_export.fetch_open_tasks(), [])

    def test_export_writes_once_and_skips_when_unchanged(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(
            journal_export, "fetch_open_tasks", return_value=[{"name": "a", "due": at(13)}]
        ):
            self.assertTrue(export_open_tasks(folder, now=NOW))
            written = (Path(folder) / "Rosie Tasks.md").read_text(encoding="utf-8")
            self.assertIn("Rosie tasks", written)
            self.assertFalse(export_open_tasks(folder, now=NOW))
            self.assertFalse((Path(folder) / "Rosie Tasks.md.tmp").exists())

    def test_not_configured_does_nothing(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(journal_export.export_if_configured())


if __name__ == "__main__":
    unittest.main()
