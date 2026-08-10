import os
from datetime import datetime, time, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from commands.chore_commands import chore_name_autocomplete
from services.chores import fairness_callout, mention_for_person
from services.database import (
    delete_booked_task,
    get_all_chores,
    get_booked_task,
    get_chore_log_entries,
    get_meal_plan_items,
    get_state,
    mark_task_completed,
    record_booked_task,
    set_state,
)
from services.google_calendar import (
    HOUSEHOLD_TZ,
    check_calendar_access,
    create_event,
    default_write_calendar_id,
    delete_event,
    get_configured_calendars,
    get_event,
    get_week_events,
    rename_event,
    update_event,
)
from services.schedule import (
    WEEKDAYS,
    find_slots,
    format_day_label,
    format_time,
    get_week_start,
    has_conflict,
    normalize_event,
    office_days_in_week,
    parse_clock_time,
    parse_task_request,
    resolve_day,
)
from services.this_week_embed import build_this_week_embed


THIS_WEEK_MESSAGE_STATE_KEY = "this_week_message_id"
THIS_WEEK_REFRESH_TIME = time(6, 0, tzinfo=HOUSEHOLD_TZ)
DEFAULT_TASK_DURATION_MINUTES = 30
MIN_TASK_DURATION_MINUTES = 5
MAX_TASK_DURATION_MINUTES = 480


def _household_names() -> list[str]:
    """Names configured via PERSONAL_NAME/PARTNER_NAME - kept out of the
    public repo (unlike the generic PERSONAL/PARTNER calendar labels) since
    they're only used locally to match "<name> office day" calendar events
    and label the #this-week office/home status line."""
    return [name for name in (os.getenv("PERSONAL_NAME"), os.getenv("PARTNER_NAME")) if name]


def _office_days_this_week(events: list[dict], week_start) -> set:
    names = _household_names()
    if not names:
        return set()
    return office_days_in_week(events, week_start, names)


async def refresh_this_week(bot: commands.Bot) -> None:
    """Rebuild and post/edit the single #this-week embed. Shared by the daily
    background refresh and the manual /refresh_this_week command so both
    paths can never drift out of sync."""
    channel_id = os.getenv("THIS_WEEK_CHANNEL_ID")
    if not channel_id:
        return

    channel = bot.get_channel(int(channel_id))
    if not isinstance(channel, discord.abc.Messageable):
        return

    now = datetime.now(HOUSEHOLD_TZ)
    monday = get_week_start(now.date())

    calendar_error = None
    try:
        events = get_week_events(monday)
    except Exception as error:
        events = []
        calendar_error = str(error)

    chores = get_all_chores()
    personal_name = os.getenv("PERSONAL_NAME")
    partner_name = os.getenv("PARTNER_NAME")
    personal_discord_id = os.getenv("PERSONAL_DISCORD_ID")
    partner_discord_id = os.getenv("PARTNER_DISCORD_ID")
    chore_fairness = {}
    for chore in chores:
        entries = get_chore_log_entries(chore["name"])
        next_person = fairness_callout(entries, personal_name, partner_name)
        if next_person:
            chore_fairness[chore["name"]] = mention_for_person(
                next_person, personal_name, partner_name, personal_discord_id, partner_discord_id
            )

    meal_plan_items = get_meal_plan_items(monday)

    embed = build_this_week_embed(
        monday,
        events,
        chores,
        now,
        calendar_error=calendar_error,
        personal_name=personal_name,
        partner_name=partner_name,
        chore_fairness=chore_fairness,
        meal_plan_items=meal_plan_items,
    )

    message_id = get_state(THIS_WEEK_MESSAGE_STATE_KEY)
    if message_id:
        try:
            message = await channel.fetch_message(int(message_id))
            await message.edit(embed=embed)
            return
        except discord.NotFound:
            pass  # the message was deleted; fall through and repost it

    message = await channel.send(embed=embed)
    set_state(THIS_WEEK_MESSAGE_STATE_KEY, str(message.id))


def _in_schedule_builder(interaction: discord.Interaction) -> bool:
    """If SCHEDULE_BUILDER_CHANNEL_ID is set, /task and /week are confined to
    that channel per the household spec. If it's not set, don't block setup
    that hasn't happened yet - allow the commands anywhere."""
    channel_id = os.getenv("SCHEDULE_BUILDER_CHANNEL_ID")
    if not channel_id:
        return True
    return interaction.channel_id == int(channel_id)


class RequesterOnlyView(discord.ui.View):
    """A view only the person who ran the originating command can act on -
    the household spec is explicit that only the /week or /task requester
    needs to confirm, not their partner."""

    def __init__(self, requester_id: int):
        super().__init__(timeout=300)
        self.requester_id = requester_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "❌ Only the person who ran this command can respond to this proposal.",
                ephemeral=True,
            )
            return False
        return True


class CancelButton(discord.ui.Button):
    """A graceful way out of a /task or /week proposal - nothing gets added
    to the calendar, and the message stops offering choices."""

    def __init__(self, task_name: str):
        super().__init__(label="Cancel", style=discord.ButtonStyle.danger)
        self.task_name = task_name

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            content=f"❌ Cancelled — nothing was added to the calendar for **{self.task_name}**.",
            view=None,
        )


class UndoTaskButton(discord.ui.Button):
    """Undoes an already-confirmed /task or /week booking - not just an
    unconfirmed proposal (that's what CancelButton is for)."""

    def __init__(self, task_name: str, event_id: str, calendar_id: str):
        super().__init__(label="Undo", style=discord.ButtonStyle.danger)
        self.task_name = task_name
        self.event_id = event_id
        self.calendar_id = calendar_id

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            delete_event(self.event_id, calendar_id=self.calendar_id)
        except Exception as error:
            await interaction.edit_original_response(
                content=f"❌ I couldn't remove that from the calendar: {error}", view=None
            )
            return

        delete_booked_task(interaction.message.id)
        await refresh_this_week(interaction.client)
        await interaction.edit_original_response(
            content=f"↩️ Removed **{self.task_name}** from the calendar.", view=None
        )


class UndoTaskView(RequesterOnlyView):
    def __init__(self, task_name: str, event_id: str, calendar_id: str, requester_id: int):
        super().__init__(requester_id)
        self.add_item(UndoTaskButton(task_name, event_id, calendar_id))


async def _track_booked_task(
    interaction: discord.Interaction,
    message: discord.Message,
    task_name: str,
    event_id: str,
    calendar_id: str,
) -> None:
    """Remember which calendar event a confirmation message corresponds to,
    and pre-add a ✅ reaction so marking it actually done later is a single
    click instead of the user having to know that's even possible."""
    record_booked_task(
        message.id,
        interaction.channel_id,
        task_name,
        event_id,
        calendar_id,
        datetime.now(HOUSEHOLD_TZ),
        interaction.user.display_name,
    )
    try:
        await message.add_reaction("✅")
    except discord.HTTPException:
        pass  # not fatal - the user can still add the reaction themselves


async def _book_event(
    interaction: discord.Interaction,
    task_name: str,
    start: datetime,
    end: datetime,
    requester_id: int,
) -> None:
    """Create the event and swap in an Undo button for it. Shared by every
    path that actually books something (proposal-confirmed or straight-to-
    calendar exact-time), so undo works the same way everywhere."""
    calendar_id = default_write_calendar_id()
    try:
        created = create_event(task_name, start, end, calendar_id=calendar_id)
    except Exception as error:
        await interaction.edit_original_response(
            content=f"❌ I couldn't add that to the calendar: {error}", view=None
        )
        return

    await refresh_this_week(interaction.client)

    event_id = created.get("id")
    view = UndoTaskView(task_name, event_id, calendar_id, requester_id) if event_id else None
    message = await interaction.edit_original_response(
        content=(
            f"✅ Added **{task_name}** to the calendar — "
            f"{format_day_label(start.date())} at {format_time(start)}."
        ),
        view=view,
    )

    if event_id:
        await _track_booked_task(interaction, message, task_name, event_id, calendar_id)


async def _confirm_and_book(
    interaction: discord.Interaction,
    task_name: str,
    start: datetime,
    end: datetime,
    week_start,
    requester_id: int,
) -> None:
    """Shared by TaskSlotView.confirm and TaskAlternativeButton: re-check the
    calendar for a conflict that appeared since this slot was proposed
    (someone could have booked something else in the meantime), then book it.
    Assumes the caller already deferred the interaction."""
    try:
        events = get_week_events(week_start)
    except Exception as error:
        await interaction.edit_original_response(
            content=f"❌ I couldn't check the calendar: {error}", view=None
        )
        return

    if has_conflict(events, start, end, HOUSEHOLD_TZ):
        await interaction.edit_original_response(
            content=(
                f"⚠️ Something else got booked in that slot for **{task_name}** since "
                "this was proposed — nothing was added. Run the command again for a fresh time."
            ),
            view=None,
        )
        return

    await _book_event(interaction, task_name, start, end, requester_id)


class TaskAlternativeButton(discord.ui.Button):
    def __init__(self, task_name: str, start: datetime, end: datetime, week_start, requester_id: int):
        super().__init__(label=f"{start.strftime('%a')} {format_time(start)}", style=discord.ButtonStyle.primary)
        self.task_name = task_name
        self.start = start
        self.end = end
        self.week_start = week_start
        self.requester_id = requester_id

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await _confirm_and_book(
            interaction, self.task_name, self.start, self.end, self.week_start, self.requester_id
        )


class TaskAlternativesView(RequesterOnlyView):
    def __init__(
        self,
        task_name: str,
        alternatives: list[tuple[datetime, datetime]],
        requester_id: int,
        week_start,
    ):
        super().__init__(requester_id)
        for start, end in alternatives:
            self.add_item(TaskAlternativeButton(task_name, start, end, week_start, requester_id))
        self.add_item(CancelButton(task_name))


class TaskSlotView(RequesterOnlyView):
    def __init__(
        self,
        task_name: str,
        start: datetime,
        end: datetime,
        day,
        requester_id: int,
        week_start,
    ):
        super().__init__(requester_id)
        self.task_name = task_name
        self.start = start
        self.end = end
        self.day = day
        self.week_start = week_start
        self.add_item(CancelButton(task_name))

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await _confirm_and_book(
            interaction, self.task_name, self.start, self.end, self.week_start, self.requester_id
        )

    @discord.ui.button(label="Pick Different Time", style=discord.ButtonStyle.secondary)
    async def pick_different(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        duration_minutes = int((self.end - self.start).total_seconds() // 60)
        try:
            events = get_week_events(self.week_start)
        except Exception as error:
            await interaction.edit_original_response(
                content=f"❌ I couldn't check the calendar: {error}", view=None
            )
            return

        alternatives = find_slots(
            events,
            self.week_start,
            duration_minutes,
            HOUSEHOLD_TZ,
            day=self.day,
            count=3,
            exclude=(self.start, self.end),
            now=datetime.now(HOUSEHOLD_TZ),
            office_days=_office_days_this_week(events, self.week_start),
        )
        if not alternatives:
            await interaction.edit_original_response(
                content=f"❌ No other free slots found for **{self.task_name}**.", view=None
            )
            return

        view = TaskAlternativesView(self.task_name, alternatives, self.requester_id, self.week_start)
        await interaction.edit_original_response(
            content=f"Pick a different time for **{self.task_name}**:", view=view
        )


class EditTaskModal(discord.ui.Modal, title="Edit Task Time"):
    time_input = discord.ui.TextInput(
        label="New Time",
        placeholder="e.g. 5pm or 5:30pm",
        max_length=20,
    )
    day_input = discord.ui.TextInput(
        label="New Day (optional)",
        placeholder="e.g. thursday — leave blank to keep the same day",
        required=False,
        max_length=20,
    )
    duration_input = discord.ui.TextInput(
        label="Duration in minutes (optional)",
        placeholder="Leave blank to keep the current duration",
        required=False,
        max_length=5,
    )

    def __init__(self, task: dict, message: discord.Message):
        super().__init__()
        self.task = task
        self.message = message

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        new_time = parse_clock_time(self.time_input.value)
        if new_time is None:
            await interaction.followup.send(
                "❌ I couldn't understand that time — try something like `5pm` or `5:30pm`.",
                ephemeral=True,
            )
            return

        day_text = self.day_input.value.strip().lower()
        if day_text and day_text not in WEEKDAYS:
            await interaction.followup.send(
                f'❌ "{self.day_input.value}" isn\'t a day of the week — try e.g. `thursday`.',
                ephemeral=True,
            )
            return

        duration_text = self.duration_input.value.strip()
        if duration_text and not duration_text.isdigit():
            await interaction.followup.send(
                "❌ Duration needs to be a number of minutes.", ephemeral=True
            )
            return

        try:
            raw_event = get_event(self.task["event_id"], calendar_id=self.task["calendar_id"])
        except Exception as error:
            await interaction.followup.send(f"❌ I couldn't look up that event: {error}", ephemeral=True)
            return

        current = normalize_event(raw_event, "current", household_tz=HOUSEHOLD_TZ)
        current_duration_minutes = int((current["end"] - current["start"]).total_seconds() // 60)

        today = datetime.now(HOUSEHOLD_TZ).date()
        target_day = resolve_day(day_text, today) if day_text else current["start"].date()
        duration_minutes = int(duration_text) if duration_text else current_duration_minutes

        new_start = datetime.combine(target_day, new_time, tzinfo=HOUSEHOLD_TZ)
        new_end = new_start + timedelta(minutes=duration_minutes)

        week_start = get_week_start(target_day)
        try:
            events = get_week_events(week_start)
        except Exception as error:
            await interaction.followup.send(f"❌ I couldn't check the calendar: {error}", ephemeral=True)
            return

        # Exclude the event's own current slot - otherwise it always
        # "conflicts" with itself.
        others = [
            event
            for event in events
            if not (event["start"] == current["start"] and event["end"] == current["end"])
        ]
        if has_conflict(others, new_start, new_end, HOUSEHOLD_TZ):
            await interaction.followup.send(
                "⚠️ That new time conflicts with something else on the calendar — nothing was changed.",
                ephemeral=True,
            )
            return

        try:
            update_event(self.task["event_id"], new_start, new_end, calendar_id=self.task["calendar_id"])
        except Exception as error:
            await interaction.followup.send(f"❌ I couldn't update the calendar: {error}", ephemeral=True)
            return

        await refresh_this_week(interaction.client)

        try:
            await self.message.edit(
                content=(
                    f"✅ **{self.task['task_name']}** rescheduled — "
                    f"{format_day_label(target_day)} at {format_time(new_start)}."
                )
            )
        except discord.HTTPException:
            pass

        await interaction.followup.send("✅ Task rescheduled.", ephemeral=True)


class Schedule(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.refresh_this_week_task.start()

    def cog_unload(self):
        self.refresh_this_week_task.cancel()

    @tasks.loop(time=THIS_WEEK_REFRESH_TIME)
    async def refresh_this_week_task(self):
        await refresh_this_week(self.bot)

    @refresh_this_week_task.before_loop
    async def before_refresh_this_week(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """Reacting ✅ on a /task or /week confirmation message marks it
        actually completed - separate from the recurring-chore /done
        system, since one-off tasks aren't chores. Anyone in the server can
        do this (not just whoever booked it), matching how either person can
        do the underlying chore."""
        if self.bot.user and payload.user_id == self.bot.user.id:
            return
        if str(payload.emoji) != "✅":
            return

        task = get_booked_task(payload.message_id)
        if task is None:
            return

        channel = self.bot.get_channel(payload.channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            return

        # payload.member is populated directly from the gateway event for
        # guild reactions - no member-cache lookup (and no members intent)
        # needed, unlike guild.get_member() which only sees already-cached
        # members and silently misses everyone else.
        completed_by = payload.member.display_name if payload.member else "someone"

        result = mark_task_completed(payload.message_id, datetime.now(HOUSEHOLD_TZ), completed_by)
        if result is None:
            return  # already marked completed - don't re-fire on a second reaction

        try:
            message = await channel.fetch_message(payload.message_id)
            await message.edit(content=f"{message.content}\n✅ Marked done by {completed_by}.", view=None)
        except discord.HTTPException:
            pass

        try:
            rename_event(
                task["event_id"], f"✅ {task['task_name']}", calendar_id=task["calendar_id"]
            )
        except Exception:
            pass  # not fatal - the Discord message and booked_tasks record still reflect completion
        await refresh_this_week(self.bot)

    @app_commands.command(
        name="refresh_this_week",
        description="Manually refresh the #this-week schedule embed",
    )
    async def refresh_this_week_command(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        if not os.getenv("THIS_WEEK_CHANNEL_ID"):
            await interaction.followup.send(
                "❌ THIS_WEEK_CHANNEL_ID isn't set in .env.", ephemeral=True
            )
            return

        try:
            await refresh_this_week(self.bot)
        except Exception as error:
            await interaction.followup.send(
                f"❌ I couldn't refresh #this-week: {error}", ephemeral=True
            )
            return

        await interaction.followup.send("✅ #this-week refreshed.", ephemeral=True)

    @app_commands.command(
        name="check_calendar_setup",
        description="Verify the bot's Google service account can reach each configured calendar",
    )
    async def check_calendar_setup(self, interaction: discord.Interaction):
        configured = get_configured_calendars()
        if not configured:
            await interaction.response.send_message(
                "❌ No calendars configured — set PERSONAL_CALENDAR_ID, "
                "PARTNER_CALENDAR_ID, FAMILY_CALENDAR_ID, and/or "
                "DISCORD_CALENDAR_ID in .env.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            results = check_calendar_access()
        except Exception as error:
            await interaction.followup.send(
                f"❌ I couldn't load the service account credentials: {error}",
                ephemeral=True,
            )
            return

        lines = []
        for label, result in results.items():
            if result["ok"]:
                lines.append(f"✅ {label}: **{result['summary']}**")
            else:
                lines.append(f"❌ {label}: {result['error']}")

        await interaction.followup.send("\n".join(lines), ephemeral=True)

    @app_commands.command(
        name="task",
        description='Schedule a quick one-off task, e.g. "call vet" or "call vet thursday at 5pm"',
    )
    @app_commands.describe(
        request='e.g. "call vet", "call vet thursday", or "call vet thursday at 5pm"',
        duration_minutes="Optional: how long it takes, in minutes (default 30)",
    )
    async def task(
        self,
        interaction: discord.Interaction,
        request: str,
        duration_minutes: app_commands.Range[
            int, MIN_TASK_DURATION_MINUTES, MAX_TASK_DURATION_MINUTES
        ] = DEFAULT_TASK_DURATION_MINUTES,
    ):
        if not _in_schedule_builder(interaction):
            await interaction.response.send_message(
                "❌ Use this command in #schedule-builder.", ephemeral=True
            )
            return

        parsed = parse_task_request(request)
        if not parsed["name"]:
            await interaction.response.send_message(
                "❌ Tell me what the task is, e.g. `/task call vet` or "
                "`/task call vet thursday at 5pm`.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        now = datetime.now(HOUSEHOLD_TZ)
        today = now.date()
        week_start = get_week_start(today)
        day = resolve_day(parsed["day"], today)

        if parsed["time"] is not None:
            target_day = day or today
            start = datetime.combine(target_day, parsed["time"], tzinfo=HOUSEHOLD_TZ)
            end = start + timedelta(minutes=duration_minutes)
            try:
                calendar_id = default_write_calendar_id()
                created = create_event(parsed["name"], start, end, calendar_id=calendar_id)
            except Exception as error:
                await interaction.followup.send(f"❌ I couldn't add that to the calendar: {error}")
                return

            await refresh_this_week(self.bot)
            event_id = created.get("id")
            view = (
                UndoTaskView(parsed["name"], event_id, calendar_id, interaction.user.id)
                if event_id
                else None
            )
            message = await interaction.followup.send(
                f"✅ Added **{parsed['name']}** to the calendar — "
                f"{format_day_label(target_day)} at {format_time(start)}.",
                view=view,
                wait=True,
            )
            if event_id:
                await _track_booked_task(interaction, message, parsed["name"], event_id, calendar_id)
            return

        try:
            events = get_week_events(week_start)
        except Exception as error:
            await interaction.followup.send(f"❌ I couldn't check the calendar: {error}")
            return

        search_week_start = week_start
        slots = find_slots(
            events,
            search_week_start,
            duration_minutes,
            HOUSEHOLD_TZ,
            day=day,
            count=1,
            now=now,
            office_days=_office_days_this_week(events, search_week_start),
        )

        # No specific day was requested and this week's out of room (either
        # genuinely fully booked, or - late on a Sunday - simply out of time
        # left in the week) - try next week instead of dead-ending.
        if not slots and day is None:
            search_week_start = week_start + timedelta(days=7)
            try:
                events = get_week_events(search_week_start)
            except Exception as error:
                await interaction.followup.send(f"❌ I couldn't check the calendar: {error}")
                return
            slots = find_slots(
                events,
                search_week_start,
                duration_minutes,
                HOUSEHOLD_TZ,
                day=None,
                count=1,
                now=now,
                office_days=_office_days_this_week(events, search_week_start),
            )

        if not slots:
            scope = format_day_label(day) if day else "this week or next"
            await interaction.followup.send(
                f"❌ I couldn't find a free slot for **{parsed['name']}** {scope} — looks fully booked."
            )
            return

        start, end = slots[0]
        week_note = "" if search_week_start == week_start else " (next week)"
        view = TaskSlotView(parsed["name"], start, end, day, interaction.user.id, search_week_start)
        await interaction.followup.send(
            f"📌 Proposed for **{parsed['name']}**: {format_day_label(start.date())}{week_note} at "
            f"{format_time(start)}–{format_time(end)}. Confirm?",
            view=view,
        )

    @app_commands.command(
        name="week",
        description="Schedule up to 5 one-off tasks this week (autocomplete suggests your chores)",
    )
    @app_commands.describe(
        task_1="First task",
        task_2="Optional: second task",
        task_3="Optional: third task",
        task_4="Optional: fourth task",
        task_5="Optional: fifth task",
        duration_minutes="Optional: how long each task takes, in minutes (default 30, applies to the whole batch)",
    )
    @app_commands.autocomplete(
        task_1=chore_name_autocomplete,
        task_2=chore_name_autocomplete,
        task_3=chore_name_autocomplete,
        task_4=chore_name_autocomplete,
        task_5=chore_name_autocomplete,
    )
    async def week(
        self,
        interaction: discord.Interaction,
        task_1: str,
        task_2: str | None = None,
        task_3: str | None = None,
        task_4: str | None = None,
        task_5: str | None = None,
        duration_minutes: app_commands.Range[
            int, MIN_TASK_DURATION_MINUTES, MAX_TASK_DURATION_MINUTES
        ] = DEFAULT_TASK_DURATION_MINUTES,
    ):
        if not _in_schedule_builder(interaction):
            await interaction.response.send_message(
                "❌ Use this command in #schedule-builder.", ephemeral=True
            )
            return

        task_names = []
        for raw_name in (task_1, task_2, task_3, task_4, task_5):
            name = (raw_name or "").strip()
            if name and name not in task_names:
                task_names.append(name)

        if not task_names:
            await interaction.response.send_message(
                "❌ Enter at least one task.", ephemeral=True
            )
            return

        await interaction.response.defer()

        now = datetime.now(HOUSEHOLD_TZ)
        week_start = get_week_start(now.date())

        try:
            events = get_week_events(week_start)
        except Exception as error:
            await interaction.followup.send(f"❌ I couldn't check the calendar: {error}")
            return

        # One call for the whole batch: find_slots spreads results across
        # different days by itself (see services/schedule.py), so tasks in
        # this batch naturally land on different days instead of clustering
        # into the same afternoon, and can never collide with each other
        # even before any of them are confirmed.
        slots = find_slots(
            events,
            week_start,
            duration_minutes,
            HOUSEHOLD_TZ,
            count=len(task_names),
            now=now,
            office_days=_office_days_this_week(events, week_start),
        )
        assignments = [(name, slot, week_start) for name, slot in zip(task_names, slots)]

        # Anything that didn't fit this week (genuinely full, or - late on a
        # Sunday - simply out of time left) rolls over into next week instead
        # of just being reported as unschedulable.
        remaining = task_names[len(slots):]
        if remaining:
            next_week_start = week_start + timedelta(days=7)
            try:
                next_events = get_week_events(next_week_start)
                next_slots = find_slots(
                    next_events,
                    next_week_start,
                    duration_minutes,
                    HOUSEHOLD_TZ,
                    count=len(remaining),
                    now=now,
                    office_days=_office_days_this_week(next_events, next_week_start),
                )
                assignments += [
                    (name, slot, next_week_start) for name, slot in zip(remaining, next_slots)
                ]
                remaining = remaining[len(next_slots):]
            except Exception:
                pass  # fall through; remaining is reported below as-is

        for name, slot, slot_week_start in assignments:
            start, end = slot
            week_note = "" if slot_week_start == week_start else " (next week)"
            view = TaskSlotView(name, start, end, None, interaction.user.id, slot_week_start)
            await interaction.followup.send(
                f"📌 Proposed for **{name}**: {format_day_label(start.date())}{week_note} at "
                f"{format_time(start)}–{format_time(end)}. Confirm?",
                view=view,
            )

        for name in remaining:
            await interaction.followup.send(
                f"❌ I couldn't find a free slot for **{name}** this week or next."
            )


@app_commands.context_menu(name="Edit Task Time")
async def edit_task_time(interaction: discord.Interaction, message: discord.Message):
    task = get_booked_task(message.id)
    if task is None:
        await interaction.response.send_message(
            "❌ This isn't a task message I'm tracking — I can only edit tasks booked via /task or /week.",
            ephemeral=True,
        )
        return
    if task["completed_at"]:
        await interaction.response.send_message(
            "❌ This task is already marked done — nothing to edit.", ephemeral=True
        )
        return

    await interaction.response.send_modal(EditTaskModal(task, message))


async def setup(bot):
    await bot.add_cog(Schedule(bot))
    bot.tree.add_command(edit_task_time)
