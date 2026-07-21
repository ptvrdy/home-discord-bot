import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

from services.database import initialize_database


load_dotenv()

TOKEN = os.environ["DISCORD_TOKEN"]

intents = discord.Intents.default()
intents.message_content = True

class HouseBot(commands.Bot):
    async def setup_hook(self):
        initialize_database()
        await self.load_extension("commands.recipe_commands")
        await self.load_extension("commands.chore_commands")
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


bot.run(TOKEN)
