import discord
from models.recipe_card import Recipe


def create_recipe_embed(recipe: Recipe):
    title = recipe.title

    embed = discord.Embed(
        title=f"🍳 {title}",
        description="Imported recipe",
        color=discord.Color.orange()
    )

    embed.add_field(
        name="⏱ Time",
        value=recipe.total_time or "Not provided",
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

    embed.set_footer(
        text="Rosie's Recipe Box 🍒"
    )
    
    image = recipe.image_url
    
    if image:
        embed.set_image(url=image)

    return embed