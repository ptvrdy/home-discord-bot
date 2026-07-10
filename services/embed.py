import discord
from models.recipe_card import Recipe


def create_recipe_embed(recipe: Recipe):
    embed = discord.Embed(
        title=f"🍳 {recipe.title}",
        description="✨ Added to Rosie's Recipe Box",
        color=0xD4A373
    )

    image = recipe.image_url
    
    if image:
        embed.set_thumbnail(url=image)
        
    title = recipe.title
    
    if recipe.tags:
        embed.add_field(
        name="🏷️ Categories",
        value=" ".join(recipe.tags),
        inline=False
    )

    time_parts = []

    if recipe.prep_time:
        embed.add_field(
            name="🔪 Prep",
            value=recipe.prep_time,
            inline=True
        )

    if recipe.cook_time:
        embed.add_field(
            name="🔥 Cook",
            value=recipe.cook_time,
            inline=True
        )

    if recipe.total_time:
        embed.add_field(
            name="⏱ Total",
            value=recipe.total_time,
            inline=True
        )

    time_text = "\n".join(time_parts) or "Not provided"
    
    embed.add_field(
        name="⏱ Time",
        value=time_text,
        inline=True
    )

    embed.add_field(
        name="🍽 Servings",
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
        name="🥘 Ingredients",
        value=ingredient_text or "Not provided",
        inline=False
    )

    embed.add_field(
        name="🔗 Original Recipe",
        value=recipe.source_url or "Not provided",
        inline=False
    )
    
    embed.add_field(
        name="🔗 Source Name",
        value=recipe.source_name or "Not provided",
        inline=False
    )
    

    embed.set_footer(
        text="Rosie's Recipe Box 🍒"
    )

    return embed