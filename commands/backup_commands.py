import os
from datetime import datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord
from discord import app_commands
from discord.ext import commands, tasks

from services.backup import BACKUP_RETENTION, backup_database, prune_old_backups


def _household_timezone():
    timezone_name = os.getenv("HOUSEHOLD_TIMEZONE", "America/New_York")
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        # Windows has no built-in IANA timezone database; fall back to the
        # system's local offset rather than retrying the same failed lookup.
        return datetime.now().astimezone().tzinfo


HOUSEHOLD_TZ = _household_timezone()
BACKUP_TIME = time(3, 0, tzinfo=HOUSEHOLD_TZ)  # daily, a quiet hour


class Backup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.daily_backup.start()

    def cog_unload(self):
        self.daily_backup.cancel()

    @tasks.loop(time=BACKUP_TIME)
    async def daily_backup(self):
        try:
            backup_database()
        except FileNotFoundError:
            return  # nothing to back up yet
        prune_old_backups()

    @daily_backup.before_loop
    async def before_daily_backup(self):
        await self.bot.wait_until_ready()

    @app_commands.command(
        name="backup_now",
        description="Manually back up the database right now",
    )
    async def backup_now(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            backup_path = backup_database()
        except FileNotFoundError as error:
            await interaction.followup.send(f"❌ {error}", ephemeral=True)
            return

        removed = prune_old_backups()
        message = f"✅ Backed up to `{backup_path.name}`."
        if removed:
            message += f" Pruned {len(removed)} old backup(s) — keeping the most recent {BACKUP_RETENTION}."
        await interaction.followup.send(message, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Backup(bot))
