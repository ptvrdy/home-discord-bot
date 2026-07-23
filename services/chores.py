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


def chores_due_soon(chores: list[dict], now: datetime, lookahead_days: int = 3) -> list[dict]:
    """Chores that aren't overdue yet but will be within `lookahead_days` -
    for a "coming up" heads-up rather than a reactive nudge. Chores with no
    done history are always overdue already, so they're excluded here (they
    belong in the overdue list, not this one)."""
    result = []
    for chore in chores:
        if is_overdue(chore, now):
            continue
        days = days_since(chore["last_done_at"], now)
        if days is None:
            continue
        if chore["threshold_days"] - days <= lookahead_days:
            result.append(chore)
    return result


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


def chore_stats(chores: list[dict], now: datetime) -> dict:
    """Aggregate the current chore board into household-wide stats: box size,
    overdue/upcoming/never-done counts, the single most-overdue chore, and a
    snapshot of who most recently completed each chore. This is a snapshot
    of current state, not cumulative history - the chores table only tracks
    each chore's *last* completion, not a full log of every time it's been
    done, so this can't show lifetime totals or streaks."""
    overdue = [chore for chore in chores if is_overdue(chore, now)]
    upcoming = chores_due_soon(chores, now)
    never_done = [chore for chore in chores if chore["last_done_at"] is None]

    overdue_with_days_late = [
        (chore, days_since(chore["last_done_at"], now) - chore["threshold_days"])
        for chore in overdue
        if chore["last_done_at"] is not None
    ]
    overdue_with_days_late.sort(key=lambda pair: pair[1], reverse=True)
    worst_offender, worst_offender_days_late = (
        overdue_with_days_late[0] if overdue_with_days_late else (None, None)
    )

    by_person: dict[str, int] = {}
    for chore in chores:
        if chore["last_done_by"]:
            by_person[chore["last_done_by"]] = by_person.get(chore["last_done_by"], 0) + 1

    return {
        "total": len(chores),
        "overdue_count": len(overdue),
        "upcoming_count": len(upcoming),
        "never_done_count": len(never_done),
        "worst_offender": worst_offender,
        "worst_offender_days_late": worst_offender_days_late,
        "by_person": by_person,
    }


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
