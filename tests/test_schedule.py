import unittest
from datetime import date, datetime, time, timezone, timedelta

from services.schedule import (
    candidate_slots,
    deduplicate_events,
    find_slots,
    format_day_label,
    format_event_sources,
    format_time,
    get_week_start,
    has_conflict,
    is_office_day,
    normalize_event,
    office_days_in_week,
    office_event_name,
    parse_clock_time,
    parse_task_request,
    previous_week_start,
    resolve_day,
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


class PreviousWeekStartTests(unittest.TestCase):
    def test_sunday_returns_the_monday_of_the_week_that_just_ended(self):
        # This is the exact bug: the automatic weekly digest runs Sunday
        # night, and used to recap two weeks back instead of one because
        # get_week_start(sunday) - 7 days skips an extra week.
        sunday = date(2026, 8, 23)
        self.assertEqual(previous_week_start(sunday), date(2026, 8, 17))

    def test_monday_returns_the_prior_full_week(self):
        monday = date(2026, 8, 24)
        self.assertEqual(previous_week_start(monday), date(2026, 8, 17))

    def test_wednesday_returns_the_prior_full_week(self):
        wednesday = date(2026, 8, 26)
        self.assertEqual(previous_week_start(wednesday), date(2026, 8, 17))

    def test_saturday_returns_the_prior_full_week(self):
        saturday = date(2026, 8, 29)
        self.assertEqual(previous_week_start(saturday), date(2026, 8, 17))


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

    def test_no_household_tz_leaves_the_original_offset_alone(self):
        raw = {"start": {"dateTime": "2026-07-20T13:30:00Z"}, "end": {"dateTime": "2026-07-20T15:00:00Z"}}

        event = normalize_event(raw, "Family")

        self.assertEqual(event["start"].hour, 13)

    def test_household_tz_converts_from_utc_to_local_hour(self):
        # Google returns timed events in UTC (trailing "Z"), regardless of
        # the calendar's own configured display timezone - 13:30 UTC is
        # actually 9:30am in America/New_York (UTC-4 in summer).
        raw = {"start": {"dateTime": "2026-07-20T13:30:00Z"}, "end": {"dateTime": "2026-07-20T15:00:00Z"}}
        household_tz = timezone(timedelta(hours=-4))

        event = normalize_event(raw, "Family", household_tz=household_tz)

        self.assertEqual(event["start"], datetime(2026, 7, 20, 9, 30, tzinfo=household_tz))
        self.assertEqual(event["end"], datetime(2026, 7, 20, 11, 0, tzinfo=household_tz))

    def test_household_tz_does_not_affect_all_day_events(self):
        raw = {"start": {"date": "2026-07-25"}, "end": {"date": "2026-07-26"}}
        household_tz = timezone(timedelta(hours=-4))

        event = normalize_event(raw, "Family", household_tz=household_tz)

        self.assertEqual(event["start"], date(2026, 7, 25))

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


class FormatTimeTests(unittest.TestCase):
    def test_morning_time(self):
        self.assertEqual(format_time(datetime(2026, 7, 20, 9, 5)), "9:05 AM")

    def test_noon(self):
        self.assertEqual(format_time(datetime(2026, 7, 20, 12, 0)), "12:00 PM")

    def test_midnight(self):
        self.assertEqual(format_time(datetime(2026, 7, 20, 0, 0)), "12:00 AM")

    def test_afternoon_time(self):
        self.assertEqual(format_time(datetime(2026, 7, 20, 17, 30)), "5:30 PM")

    def test_ten_and_eleven_oclock(self):
        self.assertEqual(format_time(datetime(2026, 7, 20, 10, 0)), "10:00 AM")
        self.assertEqual(format_time(datetime(2026, 7, 20, 23, 0)), "11:00 PM")


class FormatDayLabelTests(unittest.TestCase):
    def test_formats_weekday_and_date(self):
        self.assertEqual(format_day_label(date(2026, 7, 23)), "Thursday, Jul 23")


class ParseTaskRequestTests(unittest.TestCase):
    def test_name_only(self):
        self.assertEqual(
            parse_task_request("call vet"), {"name": "call vet", "day": None, "time": None}
        )

    def test_name_and_day(self):
        self.assertEqual(
            parse_task_request("call vet thursday"),
            {"name": "call vet", "day": "thursday", "time": None},
        )

    def test_name_day_and_time_pm(self):
        self.assertEqual(
            parse_task_request("call vet thursday at 5pm"),
            {"name": "call vet", "day": "thursday", "time": time(17, 0)},
        )

    def test_name_day_and_time_am_with_minutes(self):
        self.assertEqual(
            parse_task_request("clean shower saturday at 9:30am"),
            {"name": "clean shower", "day": "saturday", "time": time(9, 30)},
        )

    def test_is_case_insensitive(self):
        self.assertEqual(
            parse_task_request("Call Vet THURSDAY AT 5PM"),
            {"name": "Call Vet", "day": "thursday", "time": time(17, 0)},
        )

    def test_noon_and_midnight(self):
        self.assertEqual(parse_task_request("wake up at 12am")["time"], time(0, 0))
        self.assertEqual(parse_task_request("lunch at 12pm")["time"], time(12, 0))

    def test_multi_word_task_name_preserved(self):
        parsed = parse_task_request("wipe out the fridge thursday")
        self.assertEqual(parsed["name"], "wipe out the fridge")
        self.assertEqual(parsed["day"], "thursday")

    def test_today_keyword(self):
        self.assertEqual(
            parse_task_request("clean shower drain today at 5pm"),
            {"name": "clean shower drain", "day": "today", "time": time(17, 0)},
        )

    def test_today_without_time(self):
        self.assertEqual(
            parse_task_request("call vet today"),
            {"name": "call vet", "day": "today", "time": None},
        )

    def test_next_weekday(self):
        self.assertEqual(
            parse_task_request("clean shower drain next monday at 4pm"),
            {"name": "clean shower drain", "day": "next monday", "time": time(16, 0)},
        )

    def test_next_weekday_without_time(self):
        self.assertEqual(
            parse_task_request("call vet next thursday"),
            {"name": "call vet", "day": "next thursday", "time": None},
        )

    def test_next_is_case_insensitive(self):
        self.assertEqual(
            parse_task_request("call vet NEXT Monday at 5PM"),
            {"name": "call vet", "day": "next monday", "time": time(17, 0)},
        )


class ParseClockTimeTests(unittest.TestCase):
    def test_pm_time(self):
        self.assertEqual(parse_clock_time("5pm"), time(17, 0))

    def test_am_time_with_minutes(self):
        self.assertEqual(parse_clock_time("9:30am"), time(9, 30))

    def test_is_case_insensitive(self):
        self.assertEqual(parse_clock_time("5PM"), time(17, 0))

    def test_tolerates_surrounding_whitespace(self):
        self.assertEqual(parse_clock_time("  5pm  "), time(17, 0))

    def test_noon_and_midnight(self):
        self.assertEqual(parse_clock_time("12am"), time(0, 0))
        self.assertEqual(parse_clock_time("12pm"), time(12, 0))

    def test_returns_none_for_garbage(self):
        self.assertIsNone(parse_clock_time("whenever"))

    def test_returns_none_when_embedded_in_a_sentence(self):
        # Must be the whole string, not embedded like parse_task_request allows.
        self.assertIsNone(parse_clock_time("call vet at 5pm"))


class ResolveDayTests(unittest.TestCase):
    def test_none_when_no_day_name(self):
        self.assertIsNone(resolve_day(None, date(2026, 7, 21)))

    def test_resolves_to_this_weeks_matching_day(self):
        tuesday = date(2026, 7, 21)
        self.assertEqual(resolve_day("thursday", tuesday), date(2026, 7, 23))

    def test_rolls_forward_to_next_week_when_the_day_already_passed(self):
        # "today" is Thursday; asking for Monday must mean the UPCOMING
        # Monday, not this week's (already past) one - that's the actual
        # bug being fixed here (it used to return the past date).
        thursday = date(2026, 7, 23)
        self.assertEqual(resolve_day("monday", thursday), date(2026, 7, 27))

    def test_plain_weekday_on_that_same_day_means_today(self):
        monday = date(2026, 7, 20)
        self.assertEqual(resolve_day("monday", monday), monday)

    def test_case_insensitive(self):
        self.assertEqual(resolve_day("THURSDAY", date(2026, 7, 21)), date(2026, 7, 23))

    def test_today_keyword_returns_today(self):
        self.assertEqual(resolve_day("today", date(2026, 7, 23)), date(2026, 7, 23))

    def test_today_keyword_is_case_insensitive(self):
        self.assertEqual(resolve_day("TODAY", date(2026, 7, 23)), date(2026, 7, 23))

    def test_next_weekday_still_upcoming_this_week_matches_plain(self):
        # "next thursday" said on a Tuesday, with Thursday still ahead this
        # week, means the same thing as plain "thursday".
        tuesday = date(2026, 7, 21)
        self.assertEqual(resolve_day("next thursday", tuesday), date(2026, 7, 23))

    def test_next_weekday_on_that_same_day_skips_to_next_week(self):
        # Unlike plain "monday" (which means today when today is Monday),
        # "next monday" must skip today and mean the following week.
        monday = date(2026, 7, 20)
        self.assertEqual(resolve_day("next monday", monday), date(2026, 7, 27))

    def test_next_weekday_already_passed_this_week_rolls_forward(self):
        thursday = date(2026, 7, 23)
        self.assertEqual(resolve_day("next monday", thursday), date(2026, 7, 27))

    def test_next_is_case_insensitive(self):
        self.assertEqual(resolve_day("NEXT Monday", date(2026, 7, 20)), date(2026, 7, 27))


HOUSEHOLD_TZ = timezone(timedelta(hours=-4))  # fixed-offset stand-in; avoids depending on tzdata
WEEK_START = date(2026, 7, 20)  # Monday


def _timed_event_for_slots(day, hour, minute, duration_minutes, all_day=False):
    start = datetime(day.year, day.month, day.day, hour, minute, tzinfo=HOUSEHOLD_TZ)
    end = start + timedelta(minutes=duration_minutes)
    return {"name": "Busy", "start": start if not all_day else day, "end": end if not all_day else day, "all_day": all_day}


class CandidateSlotsTests(unittest.TestCase):
    def test_yields_a_slot_when_the_day_is_completely_free(self):
        slots = list(candidate_slots([], WEEK_START, 30, HOUSEHOLD_TZ, day=WEEK_START))

        self.assertTrue(slots)
        first_start, first_end = slots[0]
        self.assertEqual(first_start, datetime(2026, 7, 20, 9, 0, tzinfo=HOUSEHOLD_TZ))
        self.assertEqual(first_end, datetime(2026, 7, 20, 9, 30, tzinfo=HOUSEHOLD_TZ))

    def test_stays_within_the_9am_to_8pm_window(self):
        slots = list(candidate_slots([], WEEK_START, 30, HOUSEHOLD_TZ, day=WEEK_START))

        for start, end in slots:
            self.assertGreaterEqual(start.time(), time(9, 0))
            self.assertLessEqual(end.time(), time(20, 0))

    def test_skips_slots_overlapping_a_busy_event(self):
        busy = [_timed_event_for_slots(WEEK_START, 9, 0, 60)]  # busy 9:00-10:00

        slots = list(candidate_slots(busy, WEEK_START, 30, HOUSEHOLD_TZ, day=WEEK_START))

        for start, end in slots:
            self.assertNotEqual(start.hour, 9)

    def test_all_day_events_do_not_block_scheduling(self):
        busy = [_timed_event_for_slots(WEEK_START, 0, 0, 0, all_day=True)]

        slots = list(candidate_slots(busy, WEEK_START, 30, HOUSEHOLD_TZ, day=WEEK_START))

        self.assertTrue(slots)
        first_start, _ = slots[0]
        self.assertEqual(first_start, datetime(2026, 7, 20, 9, 0, tzinfo=HOUSEHOLD_TZ))

    def test_extra_busy_intervals_are_respected(self):
        held = (
            datetime(2026, 7, 20, 9, 0, tzinfo=HOUSEHOLD_TZ),
            datetime(2026, 7, 20, 10, 0, tzinfo=HOUSEHOLD_TZ),
        )

        slots = list(candidate_slots([], WEEK_START, 30, HOUSEHOLD_TZ, day=WEEK_START, extra_busy=[held]))

        for start, end in slots:
            self.assertNotEqual(start.hour, 9)

    def test_without_a_day_it_walks_the_whole_week(self):
        slots = list(candidate_slots([], WEEK_START, 30, HOUSEHOLD_TZ))

        days_seen = {start.date() for start, _ in slots}
        self.assertEqual(days_seen, {WEEK_START + timedelta(days=i) for i in range(7)})

    def test_no_slots_when_the_day_is_fully_booked(self):
        # Busy for the entire 9am-8pm window.
        busy = [_timed_event_for_slots(WEEK_START, 9, 0, 11 * 60)]

        slots = list(candidate_slots(busy, WEEK_START, 30, HOUSEHOLD_TZ, day=WEEK_START))

        self.assertEqual(slots, [])

    def test_now_excludes_earlier_days_entirely(self):
        # "now" is Wednesday - Monday and Tuesday should never be proposed.
        wednesday = WEEK_START + timedelta(days=2)
        now = datetime(2026, 7, 22, 10, 0, tzinfo=HOUSEHOLD_TZ)

        slots = list(candidate_slots([], WEEK_START, 30, HOUSEHOLD_TZ, now=now))

        days_seen = {start.date() for start, _ in slots}
        self.assertNotIn(WEEK_START, days_seen)
        self.assertNotIn(WEEK_START + timedelta(days=1), days_seen)
        self.assertIn(wednesday, days_seen)

    def test_now_excludes_earlier_times_today(self):
        now = datetime(2026, 7, 20, 14, 5, tzinfo=HOUSEHOLD_TZ)

        slots = list(candidate_slots([], WEEK_START, 30, HOUSEHOLD_TZ, day=WEEK_START, now=now))

        for start, _ in slots:
            self.assertGreaterEqual(start, now)

    def test_now_rounds_up_to_the_next_slot_granularity(self):
        now = datetime(2026, 7, 20, 14, 5, tzinfo=HOUSEHOLD_TZ)

        slots = list(candidate_slots([], WEEK_START, 30, HOUSEHOLD_TZ, day=WEEK_START, now=now))

        self.assertEqual(slots[0][0], datetime(2026, 7, 20, 14, 30, tzinfo=HOUSEHOLD_TZ))

    def test_no_now_filter_behaves_as_before(self):
        slots = list(candidate_slots([], WEEK_START, 30, HOUSEHOLD_TZ, day=WEEK_START, now=None))

        self.assertEqual(slots[0][0], datetime(2026, 7, 20, 9, 0, tzinfo=HOUSEHOLD_TZ))


class FindSlotsTests(unittest.TestCase):
    def test_returns_requested_count(self):
        slots = find_slots([], WEEK_START, 30, HOUSEHOLD_TZ, day=WEEK_START, count=3)

        self.assertEqual(len(slots), 3)

    def test_excludes_a_specific_slot(self):
        first_choice = find_slots([], WEEK_START, 30, HOUSEHOLD_TZ, day=WEEK_START, count=1)[0]

        alternatives = find_slots(
            [], WEEK_START, 30, HOUSEHOLD_TZ, day=WEEK_START, count=3, exclude=first_choice
        )

        self.assertNotIn(first_choice, alternatives)

    def test_returns_empty_list_when_nothing_available(self):
        busy = [_timed_event_for_slots(WEEK_START, 9, 0, 11 * 60)]

        slots = find_slots(busy, WEEK_START, 30, HOUSEHOLD_TZ, day=WEEK_START, count=1)

        self.assertEqual(slots, [])

    def test_multiple_slots_with_no_day_spread_across_different_days(self):
        slots = find_slots([], WEEK_START, 30, HOUSEHOLD_TZ, day=None, count=3)

        days_seen = {start.date() for start, _ in slots}
        # 3 alternatives across a fully-free week should land on 3 different days,
        # not all clustered into Monday afternoon.
        self.assertEqual(len(days_seen), 3)

    def test_single_slot_with_no_day_still_picks_the_earliest(self):
        slots = find_slots([], WEEK_START, 30, HOUSEHOLD_TZ, day=None, count=1)

        self.assertEqual(slots[0][0], datetime(2026, 7, 20, 9, 0, tzinfo=HOUSEHOLD_TZ))

    def test_day_spread_falls_back_to_repeating_days_once_exhausted(self):
        # Only Monday and Tuesday have any availability - the 3rd and 4th
        # alternatives must reuse those days rather than coming up empty.
        busy = [
            _timed_event_for_slots(WEEK_START + timedelta(days=i), 9, 0, 11 * 60)
            for i in range(2, 7)
        ]

        slots = find_slots(busy, WEEK_START, 30, HOUSEHOLD_TZ, day=None, count=4)

        self.assertEqual(len(slots), 4)
        days_seen = {start.date() for start, _ in slots}
        self.assertEqual(days_seen, {WEEK_START, WEEK_START + timedelta(days=1)})

    def test_now_is_respected_when_spreading_across_days(self):
        now = datetime(2026, 7, 22, 10, 0, tzinfo=HOUSEHOLD_TZ)  # Wednesday

        slots = find_slots([], WEEK_START, 30, HOUSEHOLD_TZ, day=None, count=3, now=now)

        for start, _ in slots:
            self.assertGreaterEqual(start.date(), WEEK_START + timedelta(days=2))


def _office_event(person_name, day, num_days=1):
    return {
        "name": office_event_name(person_name),
        "start": day,
        "end": day + timedelta(days=num_days),
        "all_day": True,
        "sources": ["Family"],
    }


def _plain_event(name, day):
    return {"name": name, "start": day, "end": day + timedelta(days=1), "all_day": True, "sources": ["Family"]}


class OfficeEventNameTests(unittest.TestCase):
    def test_builds_the_expected_title(self):
        self.assertEqual(office_event_name("Peyton"), "Peyton office day")


class IsOfficeDayTests(unittest.TestCase):
    def test_true_when_matching_event_covers_the_day(self):
        events = [_office_event("Peyton", WEEK_START)]

        self.assertTrue(is_office_day(events, WEEK_START, "Peyton"))

    def test_matches_case_insensitively(self):
        events = [{"name": "PEYTON OFFICE DAY", "start": WEEK_START, "end": WEEK_START + timedelta(days=1), "all_day": True}]

        self.assertTrue(is_office_day(events, WEEK_START, "Peyton"))

    def test_false_for_a_different_day(self):
        events = [_office_event("Peyton", WEEK_START)]

        self.assertFalse(is_office_day(events, WEEK_START + timedelta(days=1), "Peyton"))

    def test_false_for_a_different_person(self):
        events = [_office_event("Peyton", WEEK_START)]

        self.assertFalse(is_office_day(events, WEEK_START, "Joe"))

    def test_ignores_unrelated_events(self):
        events = [_plain_event("Vet Appointment", WEEK_START)]

        self.assertFalse(is_office_day(events, WEEK_START, "Peyton"))

    def test_true_for_a_multi_day_office_event(self):
        events = [_office_event("Peyton", WEEK_START, num_days=3)]

        self.assertTrue(is_office_day(events, WEEK_START + timedelta(days=2), "Peyton"))
        self.assertFalse(is_office_day(events, WEEK_START + timedelta(days=3), "Peyton"))


class OfficeDaysInWeekTests(unittest.TestCase):
    def test_includes_days_for_any_listed_person(self):
        events = [
            _office_event("Peyton", WEEK_START),
            _office_event("Joe", WEEK_START + timedelta(days=2)),
        ]

        result = office_days_in_week(events, WEEK_START, ["Peyton", "Joe"])

        self.assertEqual(result, {WEEK_START, WEEK_START + timedelta(days=2)})

    def test_empty_when_nobody_has_an_office_day(self):
        result = office_days_in_week([], WEEK_START, ["Peyton", "Joe"])

        self.assertEqual(result, set())


class OfficeDayWindowNarrowingTests(unittest.TestCase):
    def test_no_slots_before_5pm_on_an_office_day(self):
        slots = list(
            candidate_slots([], WEEK_START, 30, HOUSEHOLD_TZ, day=WEEK_START, office_days={WEEK_START})
        )

        for start, _ in slots:
            self.assertGreaterEqual(start.time(), time(17, 0))

    def test_normal_9am_start_on_a_non_office_day(self):
        other_day = WEEK_START + timedelta(days=1)
        slots = list(
            candidate_slots([], WEEK_START, 30, HOUSEHOLD_TZ, day=other_day, office_days={WEEK_START})
        )

        self.assertEqual(slots[0][0].time(), time(9, 0))

    def test_find_slots_also_respects_office_days(self):
        slots = find_slots(
            [], WEEK_START, 30, HOUSEHOLD_TZ, day=WEEK_START, count=1, office_days={WEEK_START}
        )

        self.assertGreaterEqual(slots[0][0].time(), time(17, 0))


class HasConflictTests(unittest.TestCase):
    def test_no_conflict_on_an_empty_calendar(self):
        start = datetime(2026, 7, 20, 9, 0, tzinfo=HOUSEHOLD_TZ)
        end = datetime(2026, 7, 20, 9, 30, tzinfo=HOUSEHOLD_TZ)

        self.assertFalse(has_conflict([], start, end, HOUSEHOLD_TZ))

    def test_detects_an_overlapping_event(self):
        # Busy 9:00-10:00; proposed slot 9:15-9:45 overlaps.
        busy = [_timed_event_for_slots(WEEK_START, 9, 0, 60)]
        start = datetime(2026, 7, 20, 9, 15, tzinfo=HOUSEHOLD_TZ)
        end = datetime(2026, 7, 20, 9, 45, tzinfo=HOUSEHOLD_TZ)

        self.assertTrue(has_conflict(busy, start, end, HOUSEHOLD_TZ))

    def test_no_conflict_for_a_non_overlapping_event(self):
        # Busy 9:00-10:00; proposed slot 10:00-10:30 doesn't overlap (adjacent, not overlapping).
        busy = [_timed_event_for_slots(WEEK_START, 9, 0, 60)]
        start = datetime(2026, 7, 20, 10, 0, tzinfo=HOUSEHOLD_TZ)
        end = datetime(2026, 7, 20, 10, 30, tzinfo=HOUSEHOLD_TZ)

        self.assertFalse(has_conflict(busy, start, end, HOUSEHOLD_TZ))

    def test_all_day_events_never_conflict(self):
        busy = [_timed_event_for_slots(WEEK_START, 0, 0, 0, all_day=True)]
        start = datetime(2026, 7, 20, 9, 0, tzinfo=HOUSEHOLD_TZ)
        end = datetime(2026, 7, 20, 9, 30, tzinfo=HOUSEHOLD_TZ)

        self.assertFalse(has_conflict(busy, start, end, HOUSEHOLD_TZ))


if __name__ == "__main__":
    unittest.main()
