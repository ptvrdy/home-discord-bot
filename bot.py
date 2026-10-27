import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

# Load .env before importing anything that reads it at import time
# (services.database picks its file from ROSIE_DATABASE_PATH). Set
# ROSIE_ENV_FILE=.env.dev to run a separate dev bot alongside the real one.
load_dotenv(os.getenv("ROSIE_ENV_FILE", ".env"))

from services.database import initialize_database  # noqa: E402
from services.timezone import describe_timezone, timezone_warning  # noqa: E402

TOKEN = os.environ["DISCORD_TOKEN"]

intents = discord.Intents.default()
intents.message_content = True

class HouseBot(commands.Bot):
    async def setup_hook(self):
        initialize_database()
        await self.load_extension("commands.recipe_commands")
        await self.load_extension("commands.chore_commands")
        await self.load_extension("commands.schedule_commands")
        await self.load_extension("commands.wishlist_commands")
        await self.load_extension("commands.meal_plan_commands")
        await self.load_extension("commands.backup_commands")
        await self.load_extension("commands.pantry_commands")
        await self.load_extension("commands.recipe_sync_commands")
        await self.tree.sync()

bot = HouseBot(
    command_prefix="!",
    intents=intents
)


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")

    if bot.user:
        print(f"Bot ID: {bot.user.id}")

    # Make the time zone Rosie is REALLY using visible in the log: a missing tz
    # database silently shifts every scheduled time (and breaks at daylight-saving
    # changes), so say so plainly instead of leaving it to be discovered.
    print(f"🕒 Household time zone: {describe_timezone()}")
    warning = timezone_warning()
    if warning:
        print(f"⚠️  {warning}")


bot.run(TOKEN)
