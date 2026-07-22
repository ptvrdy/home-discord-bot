"""Pure calendar-event logic: date math, cross-calendar deduplication,
free-slot finding, and display formatting. No Google API calls, no Discord -
easy to unit test."""

import re
from datetime import date, datetime, time, timedelta


WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

# Only propose slots inside this window, per the household's scheduling spec.
SCHEDULING_WINDOW_START_HOUR = 9
SCHEDULING_WINDOW_END_HOUR = 20
SLOT_GRANULARITY_MINUTES = 30

# On a day flagged as an office day for anyone in the household (see
# office_days_in_week below), don't propose chore/task slots until this hour
# instead of the normal SCHEDULING_WINDOW_START_HOUR - safest assumption when
# we don't know exactly who's doing which task, since either person might not
# be home during the day.
OFFICE_DAY_WINDOW_START_HOUR = 17

OFFICE_DAY_EVENT_SUFFIX = " office day"


def get_week_start(reference: date) -> date:
    """Return the Monday of the week containing `reference` (week starts Monday)."""
    return reference - timedelta(days=reference.weekday())


def format_time(moment: datetime) -> str:
    """Format a time portably (avoids strftime's platform-specific no-pad
    flags, e.g. %-I isn't available on Windows)."""
    hour = moment.hour % 12 or 12
    period = "AM" if moment.hour < 12 else "PM"
    return f"{hour}:{moment.minute:02d} {period}"


def format_day_label(day: date) -> str:
    """E.g. "Thursday, Jul 24"."""
    return day.strftime("%A, %b %d")


def parse_task_request(text: str) -> dict:
    """Parse the free text after /task into {"name", "day", "time"}.

    Recognizes an optional trailing weekday name, optionally followed by
    "at H(:MM)am/pm":
      "call vet"                 -> {"name": "call vet", "day": None, "time": None}
      "call vet thursday"        -> {"name": "call vet", "day": "thursday", "time": None}
      "call vet thursday at 5pm" -> {"name": "call vet", "day": "thursday", "time": time(17, 0)}
    """
    remaining = text.strip()

    time_match = re.search(
        r"\s+at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s*$", remaining, re.IGNORECASE
    )
    parsed_time = None
    if time_match:
        hour = int(time_match.group(1)) % 12
        minute = int(time_match.group(2) or 0)
        if time_match.group(3).lower() == "pm":
            hour += 12
        parsed_time = time(hour, minute)
        remaining = remaining[: time_match.start()]

    day_match = re.search(r"\s+(" + "|".join(WEEKDAYS) + r")\s*$", remaining, re.IGNORECASE)
    day = None
    if day_match:
        day = day_match.group(1).lower()
        remaining = remaining[: day_match.start()]

    return {"name": remaining.strip(), "day": day, "time": parsed_time}


def resolve_day(day_name: str | None, today: date) -> date | None:
    """Map a weekday name to its date within the week containing `today`
    (week starts Monday). Returns None if no day name was given."""
    if day_name is None:
        return None
    week_start = get_week_start(today)
    return week_start + timedelta(days=WEEKDAYS.index(day_name.lower()))


def office_event_name(person_name: str) -> str:
    """The event title convention this household uses to mark an office day,
    e.g. "Peyton Office Day" for person_name="Peyton"."""
    return f"{person_name}{OFFICE_DAY_EVENT_SUFFIX}"


def _occurs_on(event: dict, day: date) -> bool:
    if event["all_day"]:
        # Google's all-day "end" date is exclusive, so a single-day event has
        # start == day and end == day + 1.
        return event["start"] <= day < event["end"]
    return event["start"].date() == day


def is_office_day(events: list[dict], day: date, person_name: str) -> bool:
    """Whether `person_name` has an "<name> office day" event covering `day`."""
    target = office_event_name(person_name).lower()
    return any(
        event["name"].strip().lower() == target and _occurs_on(event, day)
        for event in events
    )


def office_days_in_week(events: list[dict], week_start: date, person_names: list[str]) -> set[date]:
    """Days this week where at least one of `person_names` is marked as an
    office day - used to keep task/chore proposals out of work hours."""
    return {
        week_start + timedelta(days=i)
        for i in range(7)
        for name in person_names
        if is_office_day(events, week_start + timedelta(days=i), name)
    }


def _busy_intervals(events: list[dict], household_tz) -> list[tuple[datetime, datetime]]:
    """Only timed events block scheduling - an all-day event (e.g. a
    birthday reminder) shouldn't prevent booking a timed task that day."""
    return [
        (event["start"].astimezone(household_tz), event["end"].astimezone(household_tz))
        for event in events
        if not event["all_day"]
    ]


def _overlaps(a_start, a_end, b_start, b_end) -> bool:
    return a_start < b_end and b_start < a_end


def _round_up_to_granularity(moment: datetime, granularity_minutes: int) -> datetime:
    moment = moment.replace(second=0, microsecond=0)
    remainder = moment.minute % granularity_minutes
    if remainder == 0:
        return moment
    return moment + timedelta(minutes=granularity_minutes - remainder)


def candidate_slots(
    events: list[dict],
    week_start: date,
    duration_minutes: int,
    household_tz,
    day: date | None = None,
    extra_busy: list[tuple[datetime, datetime]] | None = None,
    now: datetime | None = None,
    office_days: set[date] | None = None,
):
    """Yield (start, end) aware-datetime candidate slots within the
    scheduling window, stepping by SLOT_GRANULARITY_MINUTES, skipping
    anything that overlaps an existing timed event (or an `extra_busy`
    interval - used to avoid double-booking multiple as-yet-unconfirmed
    proposals against each other). If `day` is given, only that day is
    considered; otherwise walks Monday through Sunday of the given week.
    If `now` is given, never yields a slot that starts before it - so
    "somewhere this week" can't propose a time earlier today or on an
    already-past day. If a day is in `office_days`, the window doesn't open
    until OFFICE_DAY_WINDOW_START_HOUR instead of SCHEDULING_WINDOW_START_HOUR."""
    busy = _busy_intervals(events, household_tz) + (extra_busy or [])
    days = [day] if day else [week_start + timedelta(days=i) for i in range(7)]

    for current_day in days:
        start_hour = (
            OFFICE_DAY_WINDOW_START_HOUR
            if office_days and current_day in office_days
            else SCHEDULING_WINDOW_START_HOUR
        )
        window_start = datetime.combine(current_day, time(start_hour, 0), tzinfo=household_tz)
        window_end = datetime.combine(
            current_day, time(SCHEDULING_WINDOW_END_HOUR, 0), tzinfo=household_tz
        )

        if now is not None and window_end <= now:
            continue  # the whole day is already in the past

        slot_start = window_start
        if now is not None and slot_start < now:
            slot_start = _round_up_to_granularity(now, SLOT_GRANULARITY_MINUTES)

        while slot_start + timedelta(minutes=duration_minutes) <= window_end:
            slot_end = slot_start + timedelta(minutes=duration_minutes)
            if not any(_overlaps(slot_start, slot_end, b_start, b_end) for b_start, b_end in busy):
                yield (slot_start, slot_end)
            slot_start += timedelta(minutes=SLOT_GRANULARITY_MINUTES)


def find_slots(
    events: list[dict],
    week_start: date,
    duration_minutes: int,
    household_tz,
    day: date | None = None,
    count: int = 1,
    extra_busy: list[tuple[datetime, datetime]] | None = None,
    exclude: tuple[datetime, datetime] | None = None,
    now: datetime | None = None,
    office_days: set[date] | None = None,
) -> list[tuple[datetime, datetime]]:
    """Return up to `count` candidate slots, skipping a slot exactly matching
    `exclude` (used by "Pick Different Time" to not re-offer the slot that
    was just turned down).

    When a specific `day` was requested, or only one slot is needed, results
    come back in plain chronological order. Otherwise (no day pinned, more
    than one slot wanted) results are spread across different days first -
    each day's earliest opening before any day's second, and so on - so a
    batch of alternatives or a /week batch doesn't end up clustered into the
    same afternoon."""
    if day is not None or count <= 1:
        results = []
        for slot in candidate_slots(
            events,
            week_start,
            duration_minutes,
            household_tz,
            day=day,
            extra_busy=extra_busy,
            now=now,
            office_days=office_days,
        ):
            if exclude and slot == exclude:
                continue
            results.append(slot)
            if len(results) >= count:
                break
        return results

    by_day: dict[date, list[tuple[datetime, datetime]]] = {}
    for slot in candidate_slots(
        events,
        week_start,
        duration_minutes,
        household_tz,
        day=None,
        extra_busy=extra_busy,
        now=now,
        office_days=office_days,
    ):
        if exclude and slot == exclude:
            continue
        by_day.setdefault(slot[0].date(), []).append(slot)

    days_in_order = sorted(by_day.keys())
    results = []
    round_index = 0
    while len(results) < count and any(round_index < len(by_day[d]) for d in days_in_order):
        for d in days_in_order:
            if round_index < len(by_day[d]):
                results.append(by_day[d][round_index])
                if len(results) >= count:
                    break
        round_index += 1
    return results


def _parse_event_time(value: dict):
    """Google Calendar events use "dateTime" for timed events and "date" for
    all-day ones - never both. Timed events include a UTC offset, so the
    result is an aware datetime; all-day events become a plain date."""
    if "dateTime" in value:
        return datetime.fromisoformat(value["dateTime"])
    return date.fromisoformat(value["date"])


def normalize_event(raw_event: dict, source: str) -> dict:
    """Convert a raw Google Calendar API event resource into the shape used
    throughout this module: parsed start/end, whether it's all-day, and
    which calendar it came from."""
    start = _parse_event_time(raw_event["start"])
    end = _parse_event_time(raw_event["end"])
    return {
        "name": raw_event.get("summary") or "(untitled event)",
        "start": start,
        "end": end,
        "all_day": not isinstance(start, datetime),
        "source": source,
        "url": raw_event.get("htmlLink"),
    }


def _sort_sources(sources: list[str], source_order: list[str] | None) -> list[str]:
    if not source_order:
        return sorted(sources)
    return sorted(
        sources,
        key=lambda source: source_order.index(source) if source in source_order else len(source_order),
    )


def deduplicate_events(events: list[dict], source_order: list[str] | None = None) -> list[dict]:
    """Merge events that represent the same thing on multiple calendars -
    matched by name (case-insensitive) plus exact start/end instant. Aware
    datetimes compare by absolute instant in Python, so this correctly
    matches duplicates even when calendars report the same event with
    different UTC offsets. Keeps first-seen order; each result gets a
    "sources" list (ordered per `source_order` if given) instead of a single
    "source"."""
    merged: dict[tuple, dict] = {}
    order: list[tuple] = []

    for event in events:
        key = (event["name"].strip().lower(), event["start"], event["end"])
        if key not in merged:
            deduped = {k: v for k, v in event.items() if k != "source"}
            deduped["sources"] = [event["source"]]
            merged[key] = deduped
            order.append(key)
        elif event["source"] not in merged[key]["sources"]:
            merged[key]["sources"].append(event["source"])

    results = [merged[key] for key in order]
    for result in results:
        result["sources"] = _sort_sources(result["sources"], source_order)
    return results


def format_event_sources(sources: list[str]) -> str:
    """Render a source tag line, e.g. "📅 Personal · Family"."""
    return "📅 " + " · ".join(sources)
