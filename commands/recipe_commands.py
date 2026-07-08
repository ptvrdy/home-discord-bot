import os

import discord
from discord import app_commands
from discord.ext import commands

from services.forum import create_recipe_post
from services.scraper import scrape_recipe


class Recipe(commands.Cog):

    def __init__(self, bot):
        self.bot = bot


    @app_commands.command(
        name="recipe",
        description="Import a recipe from a URL"
    )
    async def recipe(
        self,
        interaction: discord.Interaction,
        url: str
    ):
        await interaction.response.defer()

        try:
            recipe = scrape_recipe(url)

            
🍳 **{recipe.title}**

⏱ Total Time:
{recipe.total_time or "Not provided"}

🍽 Servings:
{recipe.yields}

## Ingredients

{chr(10).join(recipe.ingredients[:10])}

Source:
{url}
"""

            guild = interaction.guild
            if guild is None:
                await interaction.followup.send(
                    "❌ This command can only be used in a server."
                )
                return

            forum_id = int(os.environ["RECIPE_FORUM_ID"])
            # TODO add config to import settings for each channel ID so they are centralized and not hardcoded in the codebase

            channel = guild.get_channel(forum_id)

            if not isinstance(channel, discord.ForumChannel):
                await interaction.followup.send(
                    "❌ Recipe channel is not a forum channel."
                )
                return

            await create_recipe_post(
                channel,
                recipe,
            )

            await interaction.followup.send(
                "✅ Recipe added!"
            )

        except Exception as e:
            await interaction.followup.send(
                f"❌ I couldn't import that recipe.\n\nError: {e}"
            )


async def setup(bot):
    await bot.add_cog(Recipe(bot))