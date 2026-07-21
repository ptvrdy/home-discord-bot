"""Pure chore-overdue logic. No Discord, no SQLite - just dicts in, dicts/
strings out, so it's easy to unit test without a database or a bot."""

from datetime import datetime


def _parse(timestamp: str | None) -> datetime | None:
    return datetime.fromisoformat(timestamp) if timestamp else None


def days_since(last_done_at: str | None, now: datetime) -> int | None:
    """Whole days since a chore was last done, or None if it's never been logged."""
    parsed = _parse(last_done_at)
    if parsed is None:
        return None
    return (now - parsed).days


def is_overdue(chore: dict, now: datetime) -> bool:
    """A chore with no done history is always overdue - it's never been done."""
    days = days_since(chore["last_done_at"], now)
    return days is None or days >= chore["threshold_days"]


def chores_needing_nudge(chores: list[dict], now: datetime) -> list[dict]:
    """Overdue chores that haven't already been nudged for this stretch.
    /done clears nudge_sent_at, so a chore only re-enters this list once it
    goes overdue again - the scheduler can run as often as it likes without
    spamming the same reminder."""
    return [
        chore
        for chore in chores
        if chore["nudge_sent_at"] is None and is_overdue(chore, now)
    ]


def format_nudge_message(chore: dict, now: datetime) -> str:
    """Render one overdue-chore reminder line for #nudges."""
    days = days_since(chore["last_done_at"], now)
    if days is None:
        history = "it's never been logged as done"
    else:
        who = chore["last_done_by"] or "someone"
        day_word = "day" if days == 1 else "days"
        history = f"{who} last did it {days} {day_word} ago"

    return (
        f"🧹 **{chore['name']}** is overdue "
        f"(threshold: {chore['threshold_days']} days) — {history}."
    )
