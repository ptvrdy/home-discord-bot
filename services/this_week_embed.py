"""Builds the single, daily-refreshed #this-week embed: the week's calendar
events grouped by day, plus chore status. No Discord API calls or database
access here - just data in, a discord.Embed out, so the layout is easy to
unit test."""

from datetime import date, datetime, time, timedelta

import discord

from services.chores import chores_due_soon, is_overdue
from services.schedule import format_event_sources, format_time, is_office_day, office_event_name

SCHEDULE_COLOR = 0x2E6F40
DAY_FIELD_LIMIT = 1024
CHORE_FIELD_LIMIT = 1024
OFFICE_EMOJI = "🏢"
HOME_EMOJI = "🏠"


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _event_day(event: dict) -> date:
    return event["start"] if event["all_day"] else event["start"].date()


def _event_sort_key(event: dict):
    if event["all_day"]:
        return (0, time.min)
    return (1, event["start"].time())


def _format_event_line(event: dict) -> str:
    label = "All day" if event["all_day"] else format_time(event["start"])
    name = f"[{event['name']} ↗]({event['url']})" if event.get("url") else event["name"]
    return f"{label} — **{name}** {format_event_sources(event['sources'])}"


def _office_status_line(events: list[dict], day: date, personal_name: str, partner_name: str) -> str:
    personal_office = is_office_day(events, day, personal_name)
    partner_office = is_office_day(events, day, partner_name)

    if personal_office and partner_office:
        return f"{OFFICE_EMOJI} {personal_name} & {partner_name}"
    if not personal_office and not partner_office:
        return f"{HOME_EMOJI} {personal_name} & {partner_name}"

    parts = [
        f"{OFFICE_EMOJI if personal_office else HOME_EMOJI} {personal_name}",
        f"{OFFICE_EMOJI if partner_office else HOME_EMOJI} {partner_name}",
    ]
    return "  ".join(parts)


def build_this_week_embed(
    monday: date,
    events: list[dict],
    chores: list[dict],
    now: datetime,
    calendar_error: str | None = None,
    personal_name: str | None = None,
    partner_name: str | None = None,
) -> discord.Embed:
    sunday = monday + timedelta(days=6)
    embed = discord.Embed(
        title=f"🗓️ This Week ({monday.strftime('%b %d')} – {sunday.strftime('%b %d')})",
        color=SCHEDULE_COLOR,
    )

    show_office_status = bool(personal_name and partner_name)
    office_event_names = (
        {office_event_name(personal_name).lower(), office_event_name(partner_name).lower()}
        if show_office_status
        else set()
    )

    events_by_day: dict[date, list[dict]] = {monday + timedelta(days=i): [] for i in range(7)}
    for event in events:
        if event["name"].strip().lower() in office_event_names:
            continue  # shown via the office/home status line instead
        day = _event_day(event)
        if day in events_by_day:
            events_by_day[day].append(event)

    for day, day_events in events_by_day.items():
        parts = []
        if show_office_status:
            parts.append(_office_status_line(events, day, personal_name, partner_name))

        if day_events:
            parts.append("\n".join(_format_event_line(event) for event in sorted(day_events, key=_event_sort_key)))
        else:
            parts.append("_Nothing scheduled_")

        value = _truncate("\n".join(parts), DAY_FIELD_LIMIT)
        embed.add_field(name=day.strftime("%A, %b %d"), value=value, inline=False)

    overdue_chores = [chore for chore in chores if is_overdue(chore, now)]
    upcoming_chores = chores_due_soon(chores, now)

    if overdue_chores:
        lines = [f"🔴 **{chore['name']}**" for chore in overdue_chores]
        embed.add_field(
            name="🧹 Chores Overdue",
            value=_truncate("\n".join(lines), CHORE_FIELD_LIMIT),
            inline=False,
        )
    if upcoming_chores:
        lines = [f"🟡 **{chore['name']}**" for chore in upcoming_chores]
        embed.add_field(
            name="🧹 Coming Up",
            value=_truncate("\n".join(lines), CHORE_FIELD_LIMIT),
            inline=False,
        )
    if not overdue_chores and not upcoming_chores and chores:
        embed.add_field(name="🧹 Chores", value="✅ All caught up!", inline=False)

    if calendar_error:
        embed.add_field(
            name="⚠️ Calendar Error",
            value=_truncate(calendar_error, CHORE_FIELD_LIMIT),
            inline=False,
        )

    embed.set_footer(text="🏠 Household Hub · refreshed daily")
    return embed
