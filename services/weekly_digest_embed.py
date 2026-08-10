"""Builds the weekly digest embed: a backward-looking recap of the week that
just ended - chores completed and by whom, one-off /task or /week bookings
completed, plus whatever's still overdue - pairing with #this-week's
forward-looking view. No Discord API calls or database access here - just
data in, a discord.Embed out."""

from datetime import date, datetime, timedelta

import discord

from services.chores import is_overdue
from services.schedule import format_day_label

DIGEST_COLOR = 0x4A6FA5
FIELD_LIMIT = 1024


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def build_weekly_digest_embed(
    week_start: date,
    completions: list[dict],
    chores: list[dict],
    now: datetime,
    tasks: list[dict] | None = None,
) -> discord.Embed:
    week_end = week_start + timedelta(days=6)
    embed = discord.Embed(
        title=f"📋 Last Week's Recap ({week_start.strftime('%b %d')} – {week_end.strftime('%b %d')})",
        color=DIGEST_COLOR,
    )

    if completions:
        lines = []
        for entry in completions:
            done_at = datetime.fromisoformat(entry["done_at"])
            lines.append(
                f"✅ **{entry['chore_name']}** — {entry['done_by']} "
                f"({format_day_label(done_at.date())})"
            )
        embed.add_field(
            name="Chores Completed", value=_truncate("\n".join(lines), FIELD_LIMIT), inline=False
        )
    else:
        embed.add_field(name="Chores Completed", value="_Nothing logged last week_", inline=False)

    tasks = tasks or []
    if tasks:
        lines = []
        for entry in tasks:
            completed_at = datetime.fromisoformat(entry["completed_at"])
            lines.append(
                f"✅ **{entry['task_name']}** — {entry['completed_by']} "
                f"({format_day_label(completed_at.date())})"
            )
        embed.add_field(
            name="📦 Tasks Completed", value=_truncate("\n".join(lines), FIELD_LIMIT), inline=False
        )

    by_person: dict[str, int] = {}
    for entry in completions:
        by_person[entry["done_by"]] = by_person.get(entry["done_by"], 0) + 1
    for entry in tasks:
        by_person[entry["completed_by"]] = by_person.get(entry["completed_by"], 0) + 1
    if by_person:
        lines = [
            f"{name}: {count}" for name, count in sorted(by_person.items(), key=lambda pair: -pair[1])
        ]
        embed.add_field(name="🏆 Last Week's Leaderboard", value="\n".join(lines), inline=True)

    overdue = [chore for chore in chores if is_overdue(chore, now)]
    if overdue:
        lines = [f"🔴 **{chore['name']}**" for chore in overdue]
        embed.add_field(
            name="Still Overdue", value=_truncate("\n".join(lines), FIELD_LIMIT), inline=False
        )

    embed.set_footer(text="🏠 Household Hub")
    return embed
