import discord
from discord import app_commands
from discord.ext import commands

from services.google_calendar import check_calendar_access, get_configured_calendars


class Schedule(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="check_calendar_setup",
        description="Verify the bot's Google service account can reach each configured calendar",
    )
    async def check_calendar_setup(self, interaction: discord.Interaction):
        configured = get_configured_calendars()
        if not configured:
            await interaction.response.send_message(
                "❌ No calendars configured — set PERSONAL_CALENDAR_ID, "
                "PARTNER_CALENDAR_ID, and/or FAMILY_CALENDAR_ID in .env.",
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
