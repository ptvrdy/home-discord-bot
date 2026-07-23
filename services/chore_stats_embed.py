"""Builds the /chore_stats embed. No Discord API calls or database access
here - just a stats dict in, a discord.Embed out."""

import discord

SCHEDULE_COLOR = 0x2E6F40


def _no_wrap(text: str) -> str:
    """Glue a chip's words together with non-breaking spaces so Discord only
    wraps between chips, never inside one."""
    return text.replace(" ", " ")


def build_chore_stats_embed(stats: dict) -> discord.Embed:
    embed = discord.Embed(title="🧹 Chore Stats", color=SCHEDULE_COLOR)

    embed.add_field(
        name="🧹 Chore Board",
        value=_no_wrap(
            f"{stats['total']} chores  •  {stats['overdue_count']} overdue  •  "
            f"{stats['upcoming_count']} coming up"
        ),
        inline=False,
    )

    if stats["never_done_count"]:
        embed.add_field(
            name="Never Logged",
            value=f"{stats['never_done_count']} chore(s) have never been marked done with /done",
            inline=False,
        )

    if stats["worst_offender"]:
        days_late = stats["worst_offender_days_late"]
        day_word = "day" if days_late == 1 else "days"
        embed.add_field(
            name="Most Overdue",
            value=f"🔴 **{stats['worst_offender']['name']}** — {days_late} {day_word} past due",
            inline=False,
        )

    if stats["by_person"]:
        lines = [
            f"{name}: {count}"
            for name, count in sorted(stats["by_person"].items(), key=lambda pair: -pair[1])
        ]
        embed.add_field(name="Most Recently Responsible For", value="\n".join(lines), inline=True)

    embed.set_footer(text="🏠 Household Hub")
    return embed
