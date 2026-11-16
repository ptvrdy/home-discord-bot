"""The /open_tasks list: every booked task that was never marked done, each
linked back to its confirmation message so it can be checked off (or cleaned
up). Pure formatting is kept apart from the calendar lookups so it's easy to
test.

Unlike the journal dashboard widget (services/journal_export.py), which hides
a task whose calendar event was deleted, this list KEEPS those and flags them:
they're exactly the ones that need a look. A task whose Discord message was
deleted is different - there's nothing left to react on, so the command drops
it from the database and says so (see removed_note), instead of listing a dead
link."""

import logging
import re
from datetime import datetime

import discord
from googleapiclient.errors import HttpError

from services.google_calendar import HOUSEHOLD_TZ, get_event, get_service
from services.journal_export import describe_due
from services.pantry_embed import chunk_lines
from services.schedule import normalize_event

logger = logging.getLogger(__name__)

EMBED_COLOR = 0x2E6F40
# Under Discord's 4,096-character embed description, leaving room for the header lines.
CHUNK_LIMIT = 3600

# Characters that would break a [link text](url) or style a task name.
_MARKDOWN_SPECIALS = re.compile(r"([\\\[\]*_~`|>])")


def message_link(guild_id: int, channel_id: int, message_id: int) -> str:
    """A jump link to a message, which works for anyone who can see the channel."""
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


def _escape(text: str) -> str:
    return _MARKDOWN_SPECIALS.sub(r"\\\1", text)


def look_up_events(rows: list[dict], service=None) -> list[dict]:
    """Each open-task row plus its calendar state: "due" (the event's current
    start, which follows any manual reschedule) and "event_deleted". A calendar
    hiccup leaves due unknown (None) without claiming the event is gone."""
    if not rows:
        return []
    service = service or get_service()

    results = []
    for row in rows:
        task = dict(row, due=None, event_deleted=False)
        try:
            raw = get_event(row["event_id"], row["calendar_id"], service=service)
            if raw.get("status") == "cancelled":
                task["event_deleted"] = True
            else:
                task["due"] = normalize_event(raw, "rosie", HOUSEHOLD_TZ)["start"]
        except HttpError as error:
            if getattr(error.resp, "status", None) in (404, 410):
                task["event_deleted"] = True
            else:
                logger.warning("Couldn't look up the time for %r: %s", row["task_name"], error)
        except Exception as error:  # a calendar problem must not hide the task
            logger.warning("Couldn't look up the time for %r: %s", row["task_name"], error)
        results.append(task)
    return results


def _sort_key(task: dict):
    """Most overdue first. Tasks with no known time (deleted events, calendar
    errors) go last, oldest booking first."""
    due = task.get("due")
    if due is None:
        return (1, datetime.fromisoformat(task["booked_at"]))
    when = due if isinstance(due, datetime) else datetime(due.year, due.month, due.day, tzinfo=HOUSEHOLD_TZ)
    return (0, when)


def format_open_tasks(tasks: list[dict], now: datetime, guild_id: int) -> list[str]:
    """One line per task, e.g.
    "• [clean kitchen cart](link) — Overdue · Sun Sep 6 · booked by Joe"."""
    lines = []
    for task in sorted(tasks, key=_sort_key):
        name = _escape(task["task_name"])
        head = f"• [{name}]({message_link(guild_id, task['channel_id'], task['message_id'])})"
        notes = []

        if task.get("event_deleted"):
            notes.append("calendar event deleted")
        elif task.get("due") is None:
            notes.append("due time unknown")
        else:
            notes.append(describe_due(task["due"], now)[0])

        notes.append(f"booked by {task['booked_by']}")
        lines.append(f"{head} — {' · '.join(notes)}")
    return lines


def summarize(tasks: list[dict], now: datetime) -> str:
    """e.g. "**10** tasks never completed · 9 past due"."""
    count = len(tasks)
    parts = [f"**{count}** task{'s' if count != 1 else ''} never completed"]
    overdue = sum(
        1 for task in tasks
        if task.get("due") is not None and describe_due(task["due"], now)[1] == "late"
    )
    if overdue:
        parts.append(f"{overdue} past due")
    return " · ".join(parts)


def removed_note(names: list[str], limit: int = 500) -> str:
    """The line telling you which tasks were dropped because their message was
    deleted - a list that quietly changed the database would be surprising, so
    the command says what it did. Capped so a big cleanup can't overflow the embed."""
    shown = ", ".join(_escape(name) for name in names)
    if len(shown) > limit:
        shown = shown[: limit - 1].rstrip(", ") + "…"
    count = len(names)
    return (
        f"🧹 Removed **{count}** task{'s' if count != 1 else ''} whose Discord message was "
        f"deleted: {shown}. (Their calendar events, if any, are untouched.)"
    )


def build_open_task_embeds(lines: list[str], summary: str, removed: list[str] | None = None) -> list[discord.Embed]:
    """The list as one or more embeds (a long list won't fit in one): the
    title, summary and any "removed" note on the first, the how-to footer on
    the last."""
    chunks = chunk_lines(lines, CHUNK_LIMIT) or [""]
    embeds = [discord.Embed(description=chunk, color=EMBED_COLOR) for chunk in chunks]
    embeds[0].title = "📌 Unfinished tasks"
    header = summary if not removed else f"{summary}\n{removed_note(removed)}"
    embeds[0].description = f"{header}\n\n{embeds[0].description}".rstrip()
    embeds[-1].set_footer(text="React ✅ on a linked message to mark that task done.")
    return embeds
