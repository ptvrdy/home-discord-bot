import discord
from models.recipe_card import Recipe


def create_recipe_embed(recipe: Recipe):
    title = recipe.title

    embed = discord.Embed(
        title=f"🍳 {title}",
        description="Imported recipe",
        color=discord.Color.orange()
    )

    time_parts = []

    if recipe.prep_time:
        time_parts.append(f"Prep: {recipe.prep_time}")

    if recipe.cook_time:
        time_parts.append(f"Cook: {recipe.cook_time}")

    if recipe.total_time:
        time_parts.append(f"Total: {recipe.total_time}")

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

    embed.set_footer(
        text="Rosie's Recipe Box 🍒"
    )
    
    image = recipe.image_url
    
    if image:
        embed.set_image(url=image)

    return embed