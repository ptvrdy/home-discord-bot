import unittest
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

from services.google_calendar import (
    check_calendar_access,
    get_configured_calendars,
    get_week_events,
    list_events,
)


class GetConfiguredCalendarsTests(unittest.TestCase):
    def test_returns_only_calendars_with_an_id_set(self):
        env = {"PEYTON_CALENDAR_ID": "me@example.com", "FAMILY_CALENDAR_ID": "fam@group.calendar.google.com"}
        with patch.dict("os.environ", env, clear=True):
            self.assertEqual(
                get_configured_calendars(),
                {"Peyton": "me@example.com", "Family": "fam@group.calendar.google.com"},
            )

    def test_returns_empty_when_nothing_configured(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(get_configured_calendars(), {})

    def test_supports_all_four_configured_calendars(self):
        env = {
            "PEYTON_CALENDAR_ID": "peyton@example.com",
            "PARTNER_CALENDAR_ID": "partner@example.com",
            "FAMILY_CALENDAR_ID": "fam@group.calendar.google.com",
            "DISCORD_CALENDAR_ID": "gaming@group.calendar.google.com",
        }
        with patch.dict("os.environ", env, clear=True):
            self.assertEqual(
                get_configured_calendars(),
                {
                    "Peyton": "peyton@example.com",
                    "Partner": "partner@example.com",
                    "Family": "fam@group.calendar.google.com",
                    "Discord (Gaming)": "gaming@group.calendar.google.com",
                },
            )


class CheckCalendarAccessTests(unittest.TestCase):
    def test_reports_ok_for_each_reachable_calendar(self):
        env = {"PEYTON_CALENDAR_ID": "me@example.com", "FAMILY_CALENDAR_ID": "fam@group.calendar.google.com"}
        service = MagicMock()
        service.calendars().get().execute.side_effect = [
            {"summary": "Peyton's Calendar"},
            {"summary": "Household"},
        ]

        with patch.dict("os.environ", env, clear=True):
            results = check_calendar_access(service=service)

        self.assertEqual(results["Peyton"], {"ok": True, "summary": "Peyton's Calendar"})
        self.assertEqual(results["Family"], {"ok": True, "summary": "Household"})

    def test_reports_error_for_an_unreachable_calendar(self):
        env = {"PEYTON_CALENDAR_ID": "me@example.com"}
        service = MagicMock()
        service.calendars().get().execute.side_effect = Exception("404 not shared with service account")

        with patch.dict("os.environ", env, clear=True):
            results = check_calendar_access(service=service)

        self.assertFalse(results["Peyton"]["ok"])
        self.assertIn("not shared", results["Peyton"]["error"])

    def test_falls_back_to_the_calendar_id_when_summary_is_missing(self):
        env = {"PEYTON_CALENDAR_ID": "me@example.com"}
        service = MagicMock()
        service.calendars().get().execute.return_value = {}

        with patch.dict("os.environ", env, clear=True):
            results = check_calendar_access(service=service)

        self.assertEqual(results["Peyton"], {"ok": True, "summary": "me@example.com"})


class ListEventsTests(unittest.TestCase):
    def test_calls_the_api_with_expected_params_and_returns_items(self):
        service = MagicMock()
        service.events().list().execute.return_value = {
            "items": [{"summary": "Vet Appointment"}]
        }
        time_min = datetime(2026, 7, 20, tzinfo=timezone.utc)
        time_max = datetime(2026, 7, 27, tzinfo=timezone.utc)

        items = list_events("me@example.com", time_min, time_max, service=service)

        self.assertEqual(items, [{"summary": "Vet Appointment"}])
        service.events().list.assert_any_call(
            calendarId="me@example.com",
            timeMin=time_min.isoformat(),
            timeMax=time_max.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        )

    def test_returns_empty_list_when_no_items_key(self):
        service = MagicMock()
        service.events().list().execute.return_value = {}

        items = list_events(
            "me@example.com",
            datetime(2026, 7, 20, tzinfo=timezone.utc),
            datetime(2026, 7, 27, tzinfo=timezone.utc),
            service=service,
        )

        self.assertEqual(items, [])


class GetWeekEventsTests(unittest.TestCase):
    def test_fetches_and_dedupes_across_configured_calendars(self):
        env = {"PEYTON_CALENDAR_ID": "peyton@example.com", "FAMILY_CALENDAR_ID": "fam@group.calendar.google.com"}
        service = MagicMock()
        shared_event = {
            "summary": "Family Dinner",
            "status": "confirmed",
            "start": {"dateTime": "2026-07-27T18:00:00-04:00"},
            "end": {"dateTime": "2026-07-27T19:00:00-04:00"},
        }
        service.events().list().execute.side_effect = [
            {"items": [shared_event]},
            {"items": [shared_event]},
        ]

        with patch.dict("os.environ", env, clear=True):
            events = get_week_events(date(2026, 7, 20), service=service)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["name"], "Family Dinner")
        self.assertEqual(set(events[0]["sources"]), {"Peyton", "Family"})

    def test_skips_cancelled_events(self):
        env = {"PEYTON_CALENDAR_ID": "peyton@example.com"}
        service = MagicMock()
        service.events().list().execute.return_value = {
            "items": [
                {
                    "summary": "Cancelled Thing",
                    "status": "cancelled",
                    "start": {"date": "2026-07-21"},
                    "end": {"date": "2026-07-22"},
                }
            ]
        }

        with patch.dict("os.environ", env, clear=True):
            events = get_week_events(date(2026, 7, 20), service=service)

        self.assertEqual(events, [])

    def test_returns_empty_when_no_calendars_configured(self):
        service = MagicMock()

        with patch.dict("os.environ", {}, clear=True):
            events = get_week_events(date(2026, 7, 20), service=service)

        self.assertEqual(events, [])
        service.events.assert_not_called()


if __name__ == "__main__":
    unittest.main()
