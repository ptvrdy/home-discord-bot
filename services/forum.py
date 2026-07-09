import discord

from models.recipe_card import Recipe
from services.embed import create_recipe_embed

def get_matching_tags(channel, recipe_tags):
    return [
        tag
        for tag in channel.available_tags
        if tag.name in recipe_tags
    ]
    

async def create_recipe_post(
    channel: discord.ForumChannel,
    recipe: Recipe
):
    title = recipe.title or "Untitled Recipe"

    embed = create_recipe_embed(recipe)
    
    tags = get_matching_tags(channel, recipe.tags)

    await channel.create_thread(
        name=title[:100],
        embed=embed,
        applied_tags=tags
    )
