"""Renders a recipe's cooking-log entries into the single, growing journal embed."""

from datetime import datetime

import discord

from config.discord_tags import DISCORD_TAGS
from services.embed import RECIPE_BOX_COLOR


JOURNAL_DESCRIPTION_LIMIT = 4096


def _format_made_on(made_at: str) -> str:
    made_at_date = datetime.fromisoformat(made_at)
    return f"{made_at_date.strftime('%B')} {made_at_date.day}, {made_at_date.year}"


def _format_entry(entry: dict) -> str:
    status_name = DISCORD_TAGS.get(entry["status"], {}).get("discord_name", entry["status"])
    lines = [f"**{_format_made_on(entry['made_at'])}** · {entry['author_name']} · {status_name}"]

    if entry.get("rating"):
        lines.append("⭐" * entry["rating"] + "☆" * (5 - entry["rating"]))

    if entry.get("notes"):
        lines.append(f"📝 {entry['notes']}")

    if entry.get("next_time"):
        lines.append(f"🔁 Next time: {entry['next_time']}")

    return "\n".join(lines)


def _build_description(entries: list[dict]) -> str:
    """Render entries oldest-to-newest, dropping the oldest first if it would overflow."""
    remaining = list(entries)

    while remaining:
        description = "\n\n".join(_format_entry(entry) for entry in remaining)
        if len(description) <= JOURNAL_DESCRIPTION_LIMIT:
            return description
        remaining.pop(0)

    return "No entries yet."


def build_journal_embed(entries: list[dict]) -> discord.Embed:
    embed = discord.Embed(
        title="🍒 Recipe Journal",
        description=_build_description(entries) if entries else "No entries yet.",
        color=RECIPE_BOX_COLOR,
    )
    embed.set_footer(text="❦ · ❦ · ❦")
    return embed
