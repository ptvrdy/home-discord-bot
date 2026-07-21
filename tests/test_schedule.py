import unittest
from datetime import date, datetime, timezone, timedelta

from services.schedule import (
    deduplicate_events,
    format_event_sources,
    get_week_start,
    normalize_event,
)


class GetWeekStartTests(unittest.TestCase):
    def test_monday_returns_itself(self):
        monday = date(2026, 7, 20)
        self.assertEqual(get_week_start(monday), monday)

    def test_wednesday_returns_that_weeks_monday(self):
        wednesday = date(2026, 7, 22)
        self.assertEqual(get_week_start(wednesday), date(2026, 7, 20))

    def test_sunday_returns_that_weeks_monday_not_next(self):
        sunday = date(2026, 7, 26)
        self.assertEqual(get_week_start(sunday), date(2026, 7, 20))


class NormalizeEventTests(unittest.TestCase):
    def test_timed_event_parses_as_aware_datetime(self):
        raw = {
            "summary": "Vet Appointment",
            "start": {"dateTime": "2026-07-23T09:00:00-04:00"},
            "end": {"dateTime": "2026-07-23T10:00:00-04:00"},
        }

        event = normalize_event(raw, "Personal")

        self.assertEqual(event["name"], "Vet Appointment")
        self.assertFalse(event["all_day"])
        self.assertIsInstance(event["start"], datetime)
        self.assertEqual(event["source"], "Personal")

    def test_all_day_event_parses_as_plain_date(self):
        raw = {
            "summary": "Anniversary",
            "start": {"date": "2026-07-25"},
            "end": {"date": "2026-07-26"},
        }

        event = normalize_event(raw, "Family")

        self.assertTrue(event["all_day"])
        self.assertEqual(event["start"], date(2026, 7, 25))
        self.assertNotIsInstance(event["start"], datetime)

    def test_missing_summary_falls_back_to_placeholder(self):
        raw = {"start": {"date": "2026-07-25"}, "end": {"date": "2026-07-26"}}

        event = normalize_event(raw, "Family")

        self.assertEqual(event["name"], "(untitled event)")

    def test_captures_the_calendar_event_link(self):
        raw = {
            "summary": "Vet Appointment",
            "start": {"date": "2026-07-25"},
            "end": {"date": "2026-07-26"},
            "htmlLink": "https://www.google.com/calendar/event?eid=abc123",
        }

        event = normalize_event(raw, "Personal")

        self.assertEqual(event["url"], "https://www.google.com/calendar/event?eid=abc123")

    def test_url_is_none_when_not_present(self):
        raw = {"start": {"date": "2026-07-25"}, "end": {"date": "2026-07-26"}}

        event = normalize_event(raw, "Family")

        self.assertIsNone(event["url"])


class DeduplicateEventsTests(unittest.TestCase):
    def test_merges_identical_events_from_two_calendars(self):
        start = datetime(2026, 7, 27, 19, 0, tzinfo=timezone.utc)
        end = datetime(2026, 7, 27, 21, 0, tzinfo=timezone.utc)
        events = [
            {"name": "Minecraft Mondays", "start": start, "end": end, "all_day": False, "source": "Family"},
            {"name": "Minecraft Mondays", "start": start, "end": end, "all_day": False, "source": "Discord (Gaming)"},
        ]

        result = deduplicate_events(events)

        self.assertEqual(len(result), 1)
        self.assertEqual(set(result[0]["sources"]), {"Family", "Discord (Gaming)"})
        self.assertNotIn("source", result[0])

    def test_matches_across_different_utc_offsets_for_the_same_instant(self):
        # Same instant, expressed with different offsets - as could happen if
        # two calendars are in different timezones.
        events = [
            {
                "name": "Family Dinner",
                "start": datetime(2026, 7, 27, 18, 0, tzinfo=timezone(timedelta(hours=-4))),
                "end": datetime(2026, 7, 27, 19, 0, tzinfo=timezone(timedelta(hours=-4))),
                "all_day": False,
                "source": "Personal",
            },
            {
                "name": "Family Dinner",
                "start": datetime(2026, 7, 27, 22, 0, tzinfo=timezone.utc),
                "end": datetime(2026, 7, 27, 23, 0, tzinfo=timezone.utc),
                "all_day": False,
                "source": "Family",
            },
        ]

        result = deduplicate_events(events)

        self.assertEqual(len(result), 1)
        self.assertEqual(set(result[0]["sources"]), {"Personal", "Family"})

    def test_matches_name_case_insensitively(self):
        start = date(2026, 7, 27)
        end = date(2026, 7, 28)
        events = [
            {"name": "Movie Night", "start": start, "end": end, "all_day": True, "source": "Family"},
            {"name": "movie night", "start": start, "end": end, "all_day": True, "source": "Discord (Gaming)"},
        ]

        result = deduplicate_events(events)

        self.assertEqual(len(result), 1)

    def test_keeps_distinct_events_from_the_same_calendar_separate(self):
        events = [
            {
                "name": "BG3 Night",
                "start": date(2026, 7, 27),
                "end": date(2026, 7, 28),
                "all_day": True,
                "source": "Discord (Gaming)",
            },
            {
                "name": "Movie Night",
                "start": date(2026, 7, 28),
                "end": date(2026, 7, 29),
                "all_day": True,
                "source": "Discord (Gaming)",
            },
        ]

        result = deduplicate_events(events)

        self.assertEqual(len(result), 2)

    def test_preserves_first_seen_order(self):
        events = [
            {"name": "A", "start": date(2026, 7, 27), "end": date(2026, 7, 28), "all_day": True, "source": "Family"},
            {"name": "B", "start": date(2026, 7, 28), "end": date(2026, 7, 29), "all_day": True, "source": "Family"},
        ]

        result = deduplicate_events(events)

        self.assertEqual([e["name"] for e in result], ["A", "B"])

    def test_sorts_sources_by_the_given_priority_order(self):
        start = date(2026, 7, 27)
        end = date(2026, 7, 28)
        events = [
            {"name": "Trip", "start": start, "end": end, "all_day": True, "source": "Family"},
            {"name": "Trip", "start": start, "end": end, "all_day": True, "source": "Personal"},
        ]

        result = deduplicate_events(events, source_order=["Personal", "Partner", "Family", "Discord (Gaming)"])

        self.assertEqual(result[0]["sources"], ["Personal", "Family"])

    def test_sorts_sources_alphabetically_when_no_order_given(self):
        start = date(2026, 7, 27)
        end = date(2026, 7, 28)
        events = [
            {"name": "Trip", "start": start, "end": end, "all_day": True, "source": "Family"},
            {"name": "Trip", "start": start, "end": end, "all_day": True, "source": "Discord (Gaming)"},
        ]

        result = deduplicate_events(events)

        self.assertEqual(result[0]["sources"], ["Discord (Gaming)", "Family"])


class FormatEventSourcesTests(unittest.TestCase):
    def test_joins_sources_with_a_dot(self):
        self.assertEqual(format_event_sources(["Personal", "Family"]), "📅 Personal · Family")

    def test_single_source(self):
        self.assertEqual(format_event_sources(["Family"]), "📅 Family")


if __name__ == "__main__":
    unittest.main()
