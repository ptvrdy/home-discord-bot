"""Pure chore-overdue logic. No Discord, no SQLite - just dicts in, dicts/
strings out, so it's easy to unit test without a database or a bot."""

import random
from datetime import datetime


# Attribution used for a chore_log entry that seeds a chore's history (e.g.
# anchoring a new chore's due date to a specific future day) rather than
# recording a real person's completion. Callers building a leaderboard or
# similar per-person view should filter this out - see
# services/chore_stats_embed.py / commands/chore_commands.py.
SYSTEM_ATTRIBUTION = "System"


def filter_person_completions(by_person: dict[str, int]) -> dict[str, int]:
    """Remove SYSTEM_ATTRIBUTION from a completions-by-person breakdown -
    system-seeded entries (e.g. anchoring a new chore's start date) aren't
    real household activity and shouldn't show up in a leaderboard."""
    return {name: count for name, count in by_person.items() if name != SYSTEM_ATTRIBUTION}


def count_completions_by_person(entries: list[dict]) -> dict[str, int]:
    """Aggregate a list of chore_log-style entries (each with a "done_by"
    key, e.g. from get_chore_completions_between()) into {person: count},
    excluding SYSTEM_ATTRIBUTION seed entries."""
    counts: dict[str, int] = {}
    for entry in entries:
        who = entry["done_by"]
        if who == SYSTEM_ATTRIBUTION:
            continue
        counts[who] = counts.get(who, 0) + 1
    return counts


def mention_for_person(
    name: str,
    personal_name: str | None,
    partner_name: str | None,
    personal_discord_id: str | None,
    partner_discord_id: str | None,
) -> str:
    """Map a household member's display name (as matched against
    PERSONAL_NAME/PARTNER_NAME) to a real Discord ping (<@id>) built from
    their PERSONAL_DISCORD_ID/PARTNER_DISCORD_ID, so a fairness callout
    actually notifies them instead of just printing their name. Falls back
    to the plain name if the matching Discord ID isn't configured."""
    if name == personal_name and personal_discord_id:
        return f"<@{personal_discord_id}>"
    if name == partner_name and partner_discord_id:
        return f"<@{partner_discord_id}>"
    return name


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


def _overdue_weight(chore: dict, now: datetime) -> int:
    """Higher weight = more overdue = more likely to be picked by
    random_overdue_chore. Never-done chores use their own threshold as a
    reasonable baseline weight, since there's no way to know how overdue
    they truly are."""
    days = days_since(chore["last_done_at"], now)
    if days is None:
        return 1 + chore["threshold_days"]
    return 1 + max(0, days - chore["threshold_days"])


def random_overdue_chore(
    chores: list[dict],
    now: datetime,
    rng: random.Random | None = None,
) -> dict | None:
    """Pick a random overdue chore, weighted toward whichever is most
    overdue. Returns None if nothing is currently overdue."""
    overdue = [chore for chore in chores if is_overdue(chore, now)]
    if not overdue:
        return None

    rng = rng or random
    weights = [_overdue_weight(chore, now) for chore in overdue]
    return rng.choices(overdue, weights=weights, k=1)[0]


FAIRNESS_STREAK = 3


def fairness_callout(
    entries: list[dict],
    personal_name: str | None,
    partner_name: str | None,
    streak: int = FAIRNESS_STREAK,
) -> str | None:
    """If the last `streak` real completions of a chore (from
    get_chore_log_entries()-style entries, oldest first) were all done by
    the same one of the two named household members, return the OTHER
    member's name - the household's swung too far to one person on this
    chore. Returns None if there aren't enough logged completions yet, the
    streak is mixed, the names aren't configured, or the streak belongs to
    someone other than the two named household members (e.g. a guest)."""
    if not personal_name or not partner_name:
        return None

    real_entries = [entry for entry in entries if entry["done_by"] != SYSTEM_ATTRIBUTION]
    if len(real_entries) < streak:
        return None

    recent = real_entries[-streak:]
    doer = recent[0]["done_by"]
    if any(entry["done_by"] != doer for entry in recent):
        return None

    if doer == personal_name:
        return partner_name
    if doer == partner_name:
        return personal_name
    return None


def format_nudge_message(chore: dict, now: datetime, next_person: str | None = None) -> str:
    """Render one overdue-chore reminder line for #nudges. If next_person is
    given (from fairness_callout() against the chore's full history), append
    a pointed callout so the reminder doesn't default to whoever's turn it
    "feels" like based only on the last completion."""
    days = days_since(chore["last_done_at"], now)
    if days is None:
        history = "it's never been logged as done"
        who = None
    else:
        who = chore["last_done_by"] or "someone"
        day_word = "day" if days == 1 else "days"
        history = f"{who} last did it {days} {day_word} ago"

    message = (
        f"🧹 **{chore['name']}** is overdue "
        f"(threshold: {chore['threshold_days']} days) — {history}."
    )
    if next_person:
        message += f"\n🔁 {next_person}, this one's been on {who} the last few times — your turn?"
    return message
