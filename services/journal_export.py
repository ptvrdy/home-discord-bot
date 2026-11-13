"""Writes Rosie's still-to-do tasks into the journal vault as a dashboard
widget (Obsidian renders the HTML; the vault's CSS styles it).

Off unless JOURNAL_DASHBOARD_DIR is set to the vault's "📊 Dashboards" folder -
the same folder the journal service writes its own widgets to - so the file
rides the vault's normal sync to every device. Pure rendering is separate from
the calendar lookups and the file write, so it's easy to test.
"""

import logging
import os
from datetime import date, datetime
from html import escape
from pathlib import Path

from googleapiclient.errors import HttpError

from services.database import get_open_booked_tasks
from services.google_calendar import HOUSEHOLD_TZ, get_event, get_service
from services.schedule import normalize_event

logger = logging.getLogger(__name__)

FILENAME = "Rosie Tasks.md"
MAX_SHOWN = 7


def _clock(moment: datetime) -> str:
    hour = moment.hour % 12 or 12
    return f"{hour}:{moment.minute:02d} {'AM' if moment.hour < 12 else 'PM'}"


def describe_due(due, now: datetime) -> tuple[str, str]:
    """-> (label, status). status: late | today | soon | later | none."""
    if due is None:
        return "no time set", "none"
    is_timed = isinstance(due, datetime)
    due_day = due.date() if is_timed else due
    today = now.date()
    days = (due_day - today).days
    clock = f" · {_clock(due)}" if is_timed else ""
    if (is_timed and due < now) or (not is_timed and days < 0):
        return f"Overdue · {due_day.strftime('%a %b')} {due_day.day}", "late"
    if days == 0:
        return f"Today{clock}", "today"
    if days == 1:
        return f"Tomorrow{clock}", "soon"
    if days < 7:
        return f"{due_day.strftime('%a')}{clock}", "soon"
    return f"{due_day.strftime('%b')} {due_day.day}", "later"


def _sort_key(task: dict):
    due = task.get("due")
    if due is None:
        return (2, datetime.max)
    when = due if isinstance(due, datetime) else datetime(due.year, due.month, due.day, tzinfo=HOUSEHOLD_TZ)
    return (0, when)


def render_open_tasks(tasks: list[dict], now: datetime) -> str:
    """Markdown for 📊 Dashboards/Rosie Tasks.md: one "##" section holding the
    widget's HTML (no blank lines inside it - they would end the HTML block)."""
    ordered = sorted(tasks, key=_sort_key)
    late = sum(1 for t in ordered if describe_due(t.get("due"), now)[1] == "late")
    shown = ordered[:MAX_SHOWN]

    if late:
        state = f"{late} overdue"
    elif ordered:
        state = f"{len(ordered)} open"
    else:
        state = "all caught up"

    lines = [
        f'<div class="j-widget j-tasks{" has-late" if late else ""}">',
        f'<div class="jw-head"><span class="jw-icon">📌</span><span class="jw-name">Rosie tasks</span><span class="jw-state">{escape(state)}</span></div>',
    ]
    if shown:
        lines.append('<ul class="jw-list">')
        for task in shown:
            label, status = describe_due(task.get("due"), now)
            lines.append(
                f'<li class="{status}"><span class="jw-dot"></span>'
                f'<span class="jw-t">{escape(task["name"])}</span><span class="jw-when">{escape(label)}</span></li>'
            )
        lines.append("</ul>")
        if len(ordered) > len(shown):
            lines.append(f'<div class="jw-foot"><span>+{len(ordered) - len(shown)} more in Discord</span></div>')
    else:
        lines.append('<div class="jw-empty">✅ Nothing waiting — every task Rosie booked is done.</div>')
    lines.append("</div>")

    return "\n".join(
        [
            "---",
            "type: system",
            "cssclasses:",
            "  - widgets",
            "tags:",
            "  - system/rosie",
            "---",
            "## 📌 Rosie tasks",
            "",
            *lines,
            "",
        ]
    )


def fetch_open_tasks(service=None, now: datetime | None = None) -> list[dict]:
    """Open bookings with their due time from Google Calendar. A booking whose
    event was deleted is dropped; a calendar hiccup keeps the task, time unknown."""
    rows = get_open_booked_tasks()
    if not rows:
        return []
    service = service or get_service()
    tasks = []
    for row in rows:
        due = None
        try:
            raw = get_event(row["event_id"], row["calendar_id"], service=service)
            if raw.get("status") == "cancelled":
                continue
            due = normalize_event(raw, "rosie", HOUSEHOLD_TZ)["start"]
        except HttpError as error:
            if getattr(error.resp, "status", None) in (404, 410):
                continue
            logger.warning("Couldn't look up the time for '%s': %s", row["task_name"], error)
        except Exception as error:  # a calendar problem must not hide the task
            logger.warning("Couldn't look up the time for '%s': %s", row["task_name"], error)
        tasks.append({"name": row["task_name"], "due": due, "booked_by": row["booked_by"]})
    return tasks


def export_open_tasks(directory: str | Path, now: datetime | None = None, service=None) -> bool:
    """Write the widget note into `directory`. Returns True if the file changed
    (it is left untouched otherwise, so the vault sync sees no churn)."""
    now = now or datetime.now(HOUSEHOLD_TZ)
    content = render_open_tasks(fetch_open_tasks(service=service, now=now), now)
    target = Path(directory) / FILENAME
    if target.exists() and target.read_text(encoding="utf-8").replace("\r\n", "\n") == content:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, target)
    return True


def export_if_configured() -> bool | None:
    """The hook the bot calls: does nothing (None) unless JOURNAL_DASHBOARD_DIR is set."""
    directory = os.getenv("JOURNAL_DASHBOARD_DIR")
    if not directory:
        return None
    return export_open_tasks(directory)
