import unittest
from datetime import date, datetime, timedelta, timezone

from services.this_week_embed import build_this_week_embed


MONDAY = date(2026, 7, 20)
NOW = datetime(2026, 7, 21, 9, 0, tzinfo=timezone.utc)


def _timed_event(name, day, hour, sources=("Family",), url=None):
    return {
        "name": name,
        "start": datetime(day.year, day.month, day.day, hour, 0, tzinfo=timezone.utc),
        "end": datetime(day.year, day.month, day.day, hour + 1, 0, tzinfo=timezone.utc),
        "all_day": False,
        "sources": list(sources),
        "url": url,
    }


def _all_day_event(name, day, sources=("Family",), url=None):
    # Google's all-day "end" is exclusive - a single-day event's end is the
    # following day, matching how services.schedule.is_office_day expects it.
    return {
        "name": name,
        "start": day,
        "end": day + timedelta(days=1),
        "all_day": True,
        "sources": list(sources),
        "url": url,
    }


def _chore(**overrides):
    chore = {
        "name": "Mop",
        "threshold_days": 14,
        "last_done_at": None,
        "last_done_by": None,
        "nudge_sent_at": None,
    }
    chore.update(overrides)
    return chore


class BuildThisWeekEmbedTests(unittest.TestCase):
    def test_creates_one_field_per_day_of_the_week(self):
        embed = build_this_week_embed(MONDAY, [], [], NOW)

        day_field_names = [field.name for field in embed.fields][:7]
        self.assertEqual(
            day_field_names,
            [
                "Monday, Jul 20", "Tuesday, Jul 21", "Wednesday, Jul 22",
                "Thursday, Jul 23", "Friday, Jul 24", "Saturday, Jul 25", "Sunday, Jul 26",
            ],
        )

    def test_empty_day_shows_nothing_scheduled(self):
        embed = build_this_week_embed(MONDAY, [], [], NOW)

        monday_field = next(f for f in embed.fields if f.name == "Monday, Jul 20")
        self.assertIn("Nothing scheduled", monday_field.value)

    def test_events_are_placed_on_the_correct_day(self):
        event = _timed_event("Vet Appointment", date(2026, 7, 22), 9)

        embed = build_this_week_embed(MONDAY, [event], [], NOW)

        wednesday_field = next(f for f in embed.fields if f.name == "Wednesday, Jul 22")
        self.assertIn("Vet Appointment", wednesday_field.value)
        monday_field = next(f for f in embed.fields if f.name == "Monday, Jul 20")
        self.assertIn("Nothing scheduled", monday_field.value)

    def test_events_outside_the_week_are_dropped(self):
        event = _timed_event("Next Week Thing", date(2026, 7, 27), 9)

        embed = build_this_week_embed(MONDAY, [event], [], NOW)

        for field in embed.fields[:7]:
            self.assertNotIn("Next Week Thing", field.value)

    def test_all_day_events_sort_before_timed_events(self):
        events = [
            _timed_event("Morning Meeting", date(2026, 7, 20), 8),
            _all_day_event("Anniversary", date(2026, 7, 20)),
        ]

        embed = build_this_week_embed(MONDAY, events, [], NOW)

        monday_field = next(f for f in embed.fields if f.name == "Monday, Jul 20")
        self.assertLess(
            monday_field.value.index("Anniversary"),
            monday_field.value.index("Morning Meeting"),
        )

    def test_event_line_includes_source_tag(self):
        event = _timed_event("Family Dinner", date(2026, 7, 20), 18, sources=("Personal", "Family"))

        embed = build_this_week_embed(MONDAY, [event], [], NOW)

        monday_field = next(f for f in embed.fields if f.name == "Monday, Jul 20")
        self.assertIn("📅 Personal · Family", monday_field.value)

    def test_event_name_links_to_calendar_when_url_present(self):
        event = _timed_event(
            "Vet Appointment", date(2026, 7, 20), 9, url="https://www.google.com/calendar/event?eid=abc123"
        )

        embed = build_this_week_embed(MONDAY, [event], [], NOW)

        monday_field = next(f for f in embed.fields if f.name == "Monday, Jul 20")
        self.assertIn("[Vet Appointment ↗](https://www.google.com/calendar/event?eid=abc123)", monday_field.value)

    def test_event_name_is_plain_text_without_a_url(self):
        event = _timed_event("Vet Appointment", date(2026, 7, 20), 9, url=None)

        embed = build_this_week_embed(MONDAY, [event], [], NOW)

        monday_field = next(f for f in embed.fields if f.name == "Monday, Jul 20")
        self.assertIn("**Vet Appointment**", monday_field.value)
        self.assertNotIn("↗", monday_field.value)

    def test_overdue_chores_get_their_own_field(self):
        chores = [_chore(name="Mop", last_done_at=None)]

        embed = build_this_week_embed(MONDAY, [], chores, NOW)

        overdue_field = next(f for f in embed.fields if f.name == "🧹 Chores Overdue")
        self.assertIn("Mop", overdue_field.value)

    def test_upcoming_chores_get_their_own_field(self):
        last_done = (NOW - timedelta(days=12)).isoformat()
        chores = [_chore(name="Mop", threshold_days=14, last_done_at=last_done)]

        embed = build_this_week_embed(MONDAY, [], chores, NOW)

        upcoming_field = next(f for f in embed.fields if f.name == "🧹 Coming Up")
        self.assertIn("Mop", upcoming_field.value)

    def test_all_caught_up_when_no_overdue_or_upcoming_chores(self):
        last_done = (NOW - timedelta(days=1)).isoformat()
        chores = [_chore(name="Mop", threshold_days=14, last_done_at=last_done)]

        embed = build_this_week_embed(MONDAY, [], chores, NOW)

        chores_field = next(f for f in embed.fields if f.name == "🧹 Chores")
        self.assertIn("All caught up", chores_field.value)

    def test_no_chore_field_when_there_are_no_chores_at_all(self):
        embed = build_this_week_embed(MONDAY, [], [], NOW)

        chore_field_names = {f.name for f in embed.fields} & {
            "🧹 Chores Overdue", "🧹 Coming Up", "🧹 Chores",
        }
        self.assertEqual(chore_field_names, set())

    def test_calendar_error_shown_when_provided(self):
        embed = build_this_week_embed(MONDAY, [], [], NOW, calendar_error="503 Service Unavailable")

        error_field = next(f for f in embed.fields if f.name == "⚠️ Calendar Error")
        self.assertIn("503", error_field.value)

    def test_no_calendar_error_field_when_not_provided(self):
        embed = build_this_week_embed(MONDAY, [], [], NOW)

        self.assertNotIn("⚠️ Calendar Error", {f.name for f in embed.fields})

    def test_no_office_status_line_when_names_not_provided(self):
        embed = build_this_week_embed(MONDAY, [], [], NOW)

        monday_field = next(f for f in embed.fields if f.name == "Monday, Jul 20")
        self.assertNotIn("🏢", monday_field.value)
        self.assertNotIn("🏠", monday_field.value)

    def test_both_home_shows_combined_home_line(self):
        embed = build_this_week_embed(
            MONDAY, [], [], NOW, personal_name="Peyton", partner_name="Joe"
        )

        monday_field = next(f for f in embed.fields if f.name == "Monday, Jul 20")
        self.assertIn("🏠 Peyton & Joe", monday_field.value)

    def test_both_office_shows_combined_office_line(self):
        events = [_all_day_event("Peyton office day", MONDAY), _all_day_event("Joe office day", MONDAY)]

        embed = build_this_week_embed(
            MONDAY, events, [], NOW, personal_name="Peyton", partner_name="Joe"
        )

        monday_field = next(f for f in embed.fields if f.name == "Monday, Jul 20")
        self.assertIn("🏢 Peyton & Joe", monday_field.value)

    def test_mixed_status_shows_both_people_on_the_same_line(self):
        events = [_all_day_event("Peyton office day", MONDAY)]

        embed = build_this_week_embed(
            MONDAY, events, [], NOW, personal_name="Peyton", partner_name="Joe"
        )

        monday_field = next(f for f in embed.fields if f.name == "Monday, Jul 20")
        self.assertIn("🏢 Peyton", monday_field.value)
        self.assertIn("🏠 Joe", monday_field.value)
        status_line = monday_field.value.splitlines()[0]
        self.assertIn("🏢 Peyton", status_line)
        self.assertIn("🏠 Joe", status_line)

    def test_office_day_marker_event_is_not_shown_as_a_regular_event(self):
        events = [_all_day_event("Peyton office day", MONDAY)]

        embed = build_this_week_embed(
            MONDAY, events, [], NOW, personal_name="Peyton", partner_name="Joe"
        )

        monday_field = next(f for f in embed.fields if f.name == "Monday, Jul 20")
        self.assertNotIn("**Peyton office day**", monday_field.value)

    def test_nothing_scheduled_still_shows_alongside_office_status(self):
        embed = build_this_week_embed(
            MONDAY, [], [], NOW, personal_name="Peyton", partner_name="Joe"
        )

        monday_field = next(f for f in embed.fields if f.name == "Monday, Jul 20")
        self.assertIn("Nothing scheduled", monday_field.value)

    def test_regular_events_still_show_alongside_office_status(self):
        events = [
            _all_day_event("Peyton office day", MONDAY),
            _timed_event("Vet Appointment", MONDAY, 9),
        ]

        embed = build_this_week_embed(
            MONDAY, events, [], NOW, personal_name="Peyton", partner_name="Joe"
        )

        monday_field = next(f for f in embed.fields if f.name == "Monday, Jul 20")
        self.assertIn("🏢 Peyton", monday_field.value)
        self.assertIn("Vet Appointment", monday_field.value)

    def test_trash_recycling_compost_line_shows_on_tuesday(self):
        embed = build_this_week_embed(MONDAY, [], [], NOW)

        tuesday_field = next(f for f in embed.fields if f.name == "Tuesday, Jul 21")
        self.assertIn("🗑️", tuesday_field.value)
        self.assertIn("♻️", tuesday_field.value)
        self.assertIn("🌱", tuesday_field.value)

    def test_large_items_line_shows_on_thursday_and_saturday(self):
        embed = build_this_week_embed(MONDAY, [], [], NOW)

        thursday_field = next(f for f in embed.fields if f.name == "Thursday, Jul 23")
        saturday_field = next(f for f in embed.fields if f.name == "Saturday, Jul 25")
        for field in (thursday_field, saturday_field):
            self.assertIn("🗑️", field.value)
            self.assertIn("🛋️", field.value)

    def test_no_waste_line_on_days_without_pickup(self):
        embed = build_this_week_embed(MONDAY, [], [], NOW)

        for name in ("Monday, Jul 20", "Wednesday, Jul 22", "Friday, Jul 24", "Sunday, Jul 26"):
            field = next(f for f in embed.fields if f.name == name)
            self.assertNotIn("🗑️", field.value)

    def test_waste_line_appears_alongside_office_status_and_events(self):
        event = _timed_event("Trash reminder call", date(2026, 7, 21), 9)

        embed = build_this_week_embed(
            MONDAY, [event], [], NOW, personal_name="Peyton", partner_name="Joe"
        )

        tuesday_field = next(f for f in embed.fields if f.name == "Tuesday, Jul 21")
        self.assertIn("🏠 Peyton", tuesday_field.value)
        self.assertIn("🗑️", tuesday_field.value)
        self.assertIn("Trash reminder call", tuesday_field.value)

    def test_no_blank_line_between_office_status_and_events(self):
        events = [
            _all_day_event("Peyton office day", MONDAY),
            _timed_event("Vet Appointment", MONDAY, 9),
        ]

        embed = build_this_week_embed(
            MONDAY, events, [], NOW, personal_name="Peyton", partner_name="Joe"
        )

        monday_field = next(f for f in embed.fields if f.name == "Monday, Jul 20")
        self.assertNotIn("\n\n", monday_field.value)


if __name__ == "__main__":
    unittest.main()
