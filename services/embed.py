import discord
from config.discord_tags import DISCORD_TAGS
from models.recipe_card import Recipe


def create_recipe_embed(recipe: Recipe):
    embed = discord.Embed(
        title=f"🍳 {recipe.title}",
        description=(
            "✨ Added to Rosie's Recipe Box\n"
        ),
        color=0xD4A373
    )

    image = recipe.image_url
    
    if image:
        embed.set_thumbnail(url=image)
        
    title = recipe.title
    
    if recipe.tags:
        recipe_tags = list(dict.fromkeys(recipe.tags))

        display_tags = []

        for tag in recipe_tags:
            if tag in DISCORD_TAGS:
                display_tags.append(
                    DISCORD_TAGS[tag]["discord_name"]
                )

        embed.add_field(
            name="🏷️ Categories",
            value=" • ".join(display_tags),
            inline=False
        )

    if recipe.prep_time:
        embed.add_field(
            name="🔪 Prep\n\n",
            value=recipe.prep_time,
            inline=True
        )

    if recipe.cook_time:
        embed.add_field(
            name="🔥 Cook\n",
            value=recipe.cook_time,
            inline=True
        )

    if recipe.total_time:
        embed.add_field(
            name="⏱ Total\n",
            value=recipe.total_time,
            inline=True
        )

    embed.add_field(
        name="🍽 Servings\n",
        value=recipe.yields or "Not provided",
        inline=True
    )

    ingredients = recipe.ingredients

    ingredient_text = "\n".join(
        f"• {item}" for item in ingredients[:15]
    )

    if len(ingredients) > 15:
        ingredient_text += "\n..."

    embed.add_field(
        name="🥘 Ingredients\n",
        value=ingredient_text or "Not provided",
        inline=False
    )

    embed.add_field(
        name="📚 Recipe Source\n",
        value=f"[View Recipe]({recipe.source_url})",
        inline=False
    )
    
    embed.add_field(
        name="🔗 Source Name\n\n",
        value=recipe.source_name or "Not provided",
        inline=False
    )
    
    embed.add_field(
        name="🖼 Image\n\n",
        value = recipe.image_url or "Not provided",
        inline=False
    )

    embed.set_footer(
        text="Rosie's Recipe Box 🍒"
    )

    return embed