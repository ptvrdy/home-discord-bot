"""Pure calendar-event logic: date math, cross-calendar deduplication, and
display formatting. No Google API calls, no Discord - easy to unit test."""

from datetime import date, datetime, timedelta


def get_week_start(reference: date) -> date:
    """Return the Monday of the week containing `reference` (week starts Monday)."""
    return reference - timedelta(days=reference.weekday())


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
