import discord

from models.recipe_card import Recipe
from services.embed import create_recipe_embed
from config.discord_tags import DISCORD_TAGS


def get_matching_tags(
    channel: discord.ForumChannel,
    recipe_tags: list[str],
) -> list[discord.ForumTag]:
    """Convert logical recipe tags into Discord ForumTag objects."""

    discord_tag_names = []

    for tag_key in recipe_tags:
        tag_info = DISCORD_TAGS.get(tag_key)

        if tag_info is None:
            print(f"Unknown tag: {tag_key}")
            continue

        discord_tag_names.append(tag_info["discord_name"])

    return [
        tag
        for tag in channel.available_tags
        if tag.name in discord_tag_names
    ]


async def create_recipe_post(
    channel: discord.ForumChannel,
    recipe: Recipe,
):
    title = recipe.title or "Untitled Recipe"

    embed = create_recipe_embed(recipe)

    tags = get_matching_tags(channel, recipe.tags)

    await channel.create_thread(
        name=title[:100],
        embed=embed,
        applied_tags=tags,
    )