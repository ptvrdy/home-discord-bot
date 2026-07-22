import unittest
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

from services.google_calendar import (
    check_calendar_access,
    create_event,
    default_write_calendar_id,
    get_configured_calendars,
    get_week_events,
    list_events,
)


class GetConfiguredCalendarsTests(unittest.TestCase):
    def test_returns_only_calendars_with_an_id_set(self):
        env = {"PERSONAL_CALENDAR_ID": "me@example.com", "FAMILY_CALENDAR_ID": "fam@group.calendar.google.com"}
        with patch.dict("os.environ", env, clear=True):
            self.assertEqual(
                get_configured_calendars(),
                {"Personal": "me@example.com", "Family": "fam@group.calendar.google.com"},
            )

    def test_returns_empty_when_nothing_configured(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(get_configured_calendars(), {})

    def test_supports_all_four_configured_calendars(self):
        env = {
            "PERSONAL_CALENDAR_ID": "me@example.com",
            "PARTNER_CALENDAR_ID": "partner@example.com",
            "FAMILY_CALENDAR_ID": "fam@group.calendar.google.com",
            "DISCORD_CALENDAR_ID": "gaming@group.calendar.google.com",
        }
        with patch.dict("os.environ", env, clear=True):
            self.assertEqual(
                get_configured_calendars(),
                {
                    "Personal": "me@example.com",
                    "Partner": "partner@example.com",
                    "Family": "fam@group.calendar.google.com",
                    "Discord (Gaming)": "gaming@group.calendar.google.com",
                },
            )


class CheckCalendarAccessTests(unittest.TestCase):
    def test_reports_ok_for_each_reachable_calendar(self):
        env = {"PERSONAL_CALENDAR_ID": "me@example.com", "FAMILY_CALENDAR_ID": "fam@group.calendar.google.com"}
        service = MagicMock()
        service.calendars().get().execute.side_effect = [
            {"summary": "Personal Calendar"},
            {"summary": "Household"},
        ]

        with patch.dict("os.environ", env, clear=True):
            results = check_calendar_access(service=service)

        self.assertEqual(results["Personal"], {"ok": True, "summary": "Personal Calendar"})
        self.assertEqual(results["Family"], {"ok": True, "summary": "Household"})

    def test_reports_error_for_an_unreachable_calendar(self):
        env = {"PERSONAL_CALENDAR_ID": "me@example.com"}
        service = MagicMock()
        service.calendars().get().execute.side_effect = Exception("404 not shared with service account")

        with patch.dict("os.environ", env, clear=True):
            results = check_calendar_access(service=service)

        self.assertFalse(results["Personal"]["ok"])
        self.assertIn("not shared", results["Personal"]["error"])

    def test_falls_back_to_the_calendar_id_when_summary_is_missing(self):
        env = {"PERSONAL_CALENDAR_ID": "me@example.com"}
        service = MagicMock()
        service.calendars().get().execute.return_value = {}

        with patch.dict("os.environ", env, clear=True):
            results = check_calendar_access(service=service)

        self.assertEqual(results["Personal"], {"ok": True, "summary": "me@example.com"})


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
        env = {"PERSONAL_CALENDAR_ID": "me@example.com", "FAMILY_CALENDAR_ID": "fam@group.calendar.google.com"}
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
        self.assertEqual(set(events[0]["sources"]), {"Personal", "Family"})

    def test_skips_cancelled_events(self):
        env = {"PERSONAL_CALENDAR_ID": "me@example.com"}
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


class DefaultWriteCalendarIdTests(unittest.TestCase):
    def test_prefers_explicit_override(self):
        env = {"TASK_CALENDAR_ID": "override@example.com", "FAMILY_CALENDAR_ID": "fam@example.com"}
        with patch.dict("os.environ", env, clear=True):
            self.assertEqual(default_write_calendar_id(), "override@example.com")

    def test_falls_back_to_family_calendar(self):
        env = {"PERSONAL_CALENDAR_ID": "me@example.com", "FAMILY_CALENDAR_ID": "fam@example.com"}
        with patch.dict("os.environ", env, clear=True):
            self.assertEqual(default_write_calendar_id(), "fam@example.com")

    def test_falls_back_to_whatever_is_configured_when_no_family_calendar(self):
        env = {"PERSONAL_CALENDAR_ID": "me@example.com"}
        with patch.dict("os.environ", env, clear=True):
            self.assertEqual(default_write_calendar_id(), "me@example.com")

    def test_raises_when_nothing_is_configured(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(RuntimeError):
                default_write_calendar_id()


class CreateEventTests(unittest.TestCase):
    def test_inserts_an_event_on_the_given_calendar(self):
        service = MagicMock()
        service.events().insert().execute.return_value = {"id": "abc123"}
        start = datetime(2026, 7, 23, 17, 0, tzinfo=timezone.utc)
        end = datetime(2026, 7, 23, 17, 30, tzinfo=timezone.utc)

        result = create_event("call vet", start, end, calendar_id="fam@example.com", service=service)

        self.assertEqual(result, {"id": "abc123"})
        service.events().insert.assert_any_call(
            calendarId="fam@example.com",
            body={
                "summary": "call vet",
                "start": {"dateTime": start.isoformat()},
                "end": {"dateTime": end.isoformat()},
            },
        )

    def test_uses_default_write_calendar_when_not_specified(self):
        env = {"FAMILY_CALENDAR_ID": "fam@example.com"}
        service = MagicMock()
        service.events().insert().execute.return_value = {"id": "abc123"}
        start = datetime(2026, 7, 23, 17, 0, tzinfo=timezone.utc)
        end = datetime(2026, 7, 23, 17, 30, tzinfo=timezone.utc)

        with patch.dict("os.environ", env, clear=True):
            create_event("call vet", start, end, service=service)

        service.events().insert.assert_any_call(
            calendarId="fam@example.com",
            body={
                "summary": "call vet",
                "start": {"dateTime": start.isoformat()},
                "end": {"dateTime": end.isoformat()},
            },
        )


if __name__ == "__main__":
    unittest.main()
