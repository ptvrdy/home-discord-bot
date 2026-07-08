import discord

from models.recipe_card import Recipe
from services.embed import create_recipe_embed


async def create_recipe_post(
    channel: discord.ForumChannel,
    recipe: Recipe
):
    title = recipe.title or "Untitled Recipe"

    embed = create_recipe_embed(recipe)

    await channel.create_thread(
        name=title[:100],
        embed=embed
    )
