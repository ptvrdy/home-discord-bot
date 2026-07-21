import os
from datetime import datetime, time

import discord
from discord import app_commands
from discord.ext import commands, tasks

from services.database import get_all_chores, get_state, set_state
from services.google_calendar import (
    HOUSEHOLD_TZ,
    check_calendar_access,
    get_configured_calendars,
    get_week_events,
)
from services.schedule import get_week_start
from services.this_week_embed import build_this_week_embed


THIS_WEEK_MESSAGE_STATE_KEY = "this_week_message_id"
THIS_WEEK_REFRESH_TIME = time(6, 0, tzinfo=HOUSEHOLD_TZ)


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
                "❌ No calendars configured — set PEYTON_CALENDAR_ID, "
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


async def setup(bot):
    await bot.add_cog(Schedule(bot))
