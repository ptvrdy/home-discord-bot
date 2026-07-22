import os
from datetime import datetime, time, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from commands.chore_commands import chore_name_autocomplete
from services.database import get_all_chores, get_state, set_state
from services.google_calendar import (
    HOUSEHOLD_TZ,
    check_calendar_access,
    create_event,
    get_configured_calendars,
    get_week_events,
)
from services.schedule import (
    find_slots,
    format_day_label,
    format_time,
    get_week_start,
    parse_task_request,
    resolve_day,
)
from services.this_week_embed import build_this_week_embed


THIS_WEEK_MESSAGE_STATE_KEY = "this_week_message_id"
THIS_WEEK_REFRESH_TIME = time(6, 0, tzinfo=HOUSEHOLD_TZ)
DEFAULT_TASK_DURATION_MINUTES = 30


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
    embed = build_this_week_embed(monday, events, chores, now, calendar_error=calendar_error)

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


class TaskAlternativeButton(discord.ui.Button):
    def __init__(self, task_name: str, start: datetime, end: datetime):
        super().__init__(label=f"{start.strftime('%a')} {format_time(start)}", style=discord.ButtonStyle.primary)
        self.task_name = task_name
        self.start = start
        self.end = end

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            create_event(self.task_name, self.start, self.end)
        except Exception as error:
            await interaction.edit_original_response(
                content=f"❌ I couldn't add that to the calendar: {error}", view=None
            )
            return

        await refresh_this_week(interaction.client)
        await interaction.edit_original_response(
            content=(
                f"✅ Added **{self.task_name}** to the calendar — "
                f"{format_day_label(self.start.date())} at {format_time(self.start)}."
            ),
            view=None,
        )


class TaskAlternativesView(RequesterOnlyView):
    def __init__(self, task_name: str, alternatives: list[tuple[datetime, datetime]], requester_id: int):
        super().__init__(requester_id)
        for start, end in alternatives:
            self.add_item(TaskAlternativeButton(task_name, start, end))


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

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        try:
            create_event(self.task_name, self.start, self.end)
        except Exception as error:
            await interaction.edit_original_response(
                content=f"❌ I couldn't add that to the calendar: {error}", view=None
            )
            return

        await refresh_this_week(interaction.client)
        await interaction.edit_original_response(
            content=(
                f"✅ Added **{self.task_name}** to the calendar — "
                f"{format_day_label(self.start.date())} at {format_time(self.start)}."
            ),
            view=None,
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
        )
        if not alternatives:
            await interaction.edit_original_response(
                content=f"❌ No other free slots found for **{self.task_name}**.", view=None
            )
            return

        view = TaskAlternativesView(self.task_name, alternatives, self.requester_id)
        await interaction.edit_original_response(
            content=f"Pick a different time for **{self.task_name}**:", view=view
        )


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
        request='e.g. "call vet", "call vet thursday", or "call vet thursday at 5pm"'
    )
    async def task(self, interaction: discord.Interaction, request: str):
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

        today = datetime.now(HOUSEHOLD_TZ).date()
        week_start = get_week_start(today)
        day = resolve_day(parsed["day"], today)

        if parsed["time"] is not None:
            target_day = day or today
            start = datetime.combine(target_day, parsed["time"], tzinfo=HOUSEHOLD_TZ)
            end = start + timedelta(minutes=DEFAULT_TASK_DURATION_MINUTES)
            try:
                create_event(parsed["name"], start, end)
            except Exception as error:
                await interaction.followup.send(f"❌ I couldn't add that to the calendar: {error}")
                return

            await refresh_this_week(self.bot)
            await interaction.followup.send(
                f"✅ Added **{parsed['name']}** to the calendar — "
                f"{format_day_label(target_day)} at {format_time(start)}."
            )
            return

        try:
            events = get_week_events(week_start)
        except Exception as error:
            await interaction.followup.send(f"❌ I couldn't check the calendar: {error}")
            return

        slots = find_slots(events, week_start, DEFAULT_TASK_DURATION_MINUTES, HOUSEHOLD_TZ, day=day, count=1)
        if not slots:
            scope = format_day_label(day) if day else "this week"
            await interaction.followup.send(
                f"❌ I couldn't find a free slot for **{parsed['name']}** {scope} — looks fully booked."
            )
            return

        start, end = slots[0]
        view = TaskSlotView(parsed["name"], start, end, day, interaction.user.id, week_start)
        await interaction.followup.send(
            f"📌 Proposed for **{parsed['name']}**: {format_day_label(start.date())} at "
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

        today = datetime.now(HOUSEHOLD_TZ).date()
        week_start = get_week_start(today)

        try:
            events = get_week_events(week_start)
        except Exception as error:
            await interaction.followup.send(f"❌ I couldn't check the calendar: {error}")
            return

        held: list[tuple[datetime, datetime]] = []
        for name in task_names:
            slots = find_slots(
                events, week_start, DEFAULT_TASK_DURATION_MINUTES, HOUSEHOLD_TZ, count=1, extra_busy=held
            )
            if not slots:
                await interaction.followup.send(f"❌ I couldn't find a free slot for **{name}** this week.")
                continue

            start, end = slots[0]
            held.append((start, end))
            view = TaskSlotView(name, start, end, None, interaction.user.id, week_start)
            await interaction.followup.send(
                f"📌 Proposed for **{name}**: {format_day_label(start.date())} at "
                f"{format_time(start)}–{format_time(end)}. Confirm?",
                view=view,
            )


async def setup(bot):
    await bot.add_cog(Schedule(bot))
