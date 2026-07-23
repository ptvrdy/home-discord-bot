import os
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord
from discord import app_commands
from discord.ext import commands, tasks

from services.chore_stats_embed import build_chore_stats_embed
from services.chores import chore_stats, chores_needing_nudge, format_nudge_message
from services.database import (
    get_all_chores,
    get_chore_names,
    mark_chore_done,
    mark_nudge_sent,
)


def _household_timezone():
    timezone_name = os.getenv("HOUSEHOLD_TIMEZONE", "America/New_York")
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        # Windows has no built-in IANA timezone database; fall back to the
        # system's local offset rather than retrying the same failed lookup.
        return datetime.now().astimezone().tzinfo


HOUSEHOLD_TZ = _household_timezone()
NUDGE_TIMES = [time(9, 0, tzinfo=HOUSEHOLD_TZ), time(17, 0, tzinfo=HOUSEHOLD_TZ)]


async def chore_name_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    current_lower = current.lower()
    matches = [name for name in get_chore_names() if current_lower in name.lower()]
    return [app_commands.Choice(name=name, value=name) for name in matches[:25]]


class Chores(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        nudges_channel_id = os.getenv("NUDGES_CHANNEL_ID")
        self.nudges_channel_id = int(nudges_channel_id) if nudges_channel_id else None
        self.nudge_check.start()

    def cog_unload(self):
        self.nudge_check.cancel()

    @tasks.loop(time=NUDGE_TIMES)
    async def nudge_check(self):
        if self.nudges_channel_id is None:
            return

        channel = self.bot.get_channel(self.nudges_channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            return

        now = datetime.now(HOUSEHOLD_TZ)
        chores = get_all_chores()
        for chore in chores_needing_nudge(chores, now):
            await channel.send(format_nudge_message(chore, now))
            mark_nudge_sent(chore["name"], now)

    @nudge_check.before_loop
    async def before_nudge_check(self):
        await self.bot.wait_until_ready()

    @app_commands.command(
        name="done",
        description="Mark a household chore as completed",
    )
    @app_commands.describe(
        chore="Which chore you completed",
        completed_by="Optional: attribute this to someone else instead of yourself",
        days_ago="Optional: backdate this (e.g. 3 for \"3 days ago\") instead of just now",
    )
    @app_commands.autocomplete(chore=chore_name_autocomplete)
    async def done(
        self,
        interaction: discord.Interaction,
        chore: str,
        completed_by: discord.Member | None = None,
        days_ago: app_commands.Range[int, 0, 3650] = 0,
    ):
        member = completed_by or interaction.user
        done_at = datetime.now(HOUSEHOLD_TZ) - timedelta(days=days_ago)
        updated = mark_chore_done(chore, member.display_name, done_at)

        if updated is None:
            await interaction.response.send_message(
                f'❌ No chore named "{chore}" — pick a suggestion from the '
                "autocomplete list so the name matches exactly.",
                ephemeral=True,
            )
            return

        when = f"{days_ago} day{'s' if days_ago != 1 else ''} ago" if days_ago else "just now"
        await interaction.response.send_message(
            f"✅ **{updated['name']}** marked done by {member.display_name} ({when})."
        )

    @app_commands.command(
        name="chore_stats",
        description="See household chore stats: overdue, coming up, and who's been keeping up",
    )
    async def chore_stats_command(self, interaction: discord.Interaction):
        now = datetime.now(HOUSEHOLD_TZ)
        stats = chore_stats(get_all_chores(), now)
        await interaction.response.send_message(embed=build_chore_stats_embed(stats))


async def setup(bot):
    await bot.add_cog(Chores(bot))
