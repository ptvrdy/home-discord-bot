"""Pure helpers for the catch-up sweep that completes tasks whose ✅ Rosie
missed. Discord only tells Rosie about a reaction at the instant it's added;
if she was restarting, reconnecting or busy then, the click is lost for good.
The sweep re-reads the messages of recently booked, still-open tasks instead.
No Discord or database access here, so the selection logic is easy to test."""

from datetime import datetime, timedelta


def recent_open_tasks(tasks: list[dict], now: datetime, window_days: int) -> list[dict]:
    """The open tasks booked within the last `window_days` days.

    Older ones are deliberately left alone: completing a months-old backlog
    "now" would credit it all to whatever week the sweep happened to run in,
    so the sweep only heals recent misses; stale tasks are for a deliberate
    cleanup. A naive `booked_at` is read as being in `now`'s time zone."""
    cutoff = now - timedelta(days=window_days)
    recent = []
    for task in tasks:
        booked_at = datetime.fromisoformat(task["booked_at"])
        if booked_at.tzinfo is None:
            booked_at = booked_at.replace(tzinfo=now.tzinfo)
        if booked_at >= cutoff:
            recent.append(task)
    return recent
