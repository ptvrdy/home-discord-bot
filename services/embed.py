import discord

from config.discord_tags import DISCORD_TAGS
from models.recipe_card import Recipe
from services.image_layout import should_use_thumbnail


RECIPE_BOX_COLOR = 0xA8391F
INGREDIENT_FIELD_LIMIT = 1024


def _truncate_ingredient_lines(ingredients: list[str]) -> str:
    """Keep the ingredient field within Discord's 1,024-character limit."""
    lines: list[str] = []
    length = 0

    for ingredient in ingredients:
        line = f"• {ingredient}"
        separator_length = 1 if lines else 0
        if length + separator_length + len(line) > INGREDIENT_FIELD_LIMIT - 4:
            lines.append("…")
            break

        lines.append(line)
        length += separator_length + len(line)

    return "\n".join(lines) or "Not provided"


def _no_wrap(text: str) -> str:
    """Glue a chip's words together with non-breaking spaces so Discord only
    wraps between chips (e.g. at a bullet), never inside one like "⏱️ / Quick"."""
    return text.replace(" ", " ")


def _display_tags(tags: list[str]) -> list[str]:
    """Map logical recipe tags to the matching Discord forum-tag labels."""
    unique_tags = dict.fromkeys(tags)
    return [
        DISCORD_TAGS[tag]["discord_name"]
        for tag in unique_tags
        if tag in DISCORD_TAGS
    ]


def create_recipe_embed(recipe: Recipe) -> discord.Embed:
    source_name = recipe.source_name or "the original recipe"
    source_line = f"From **{source_name}**"
    if recipe.source_url:
        source_line += f" · [View the original recipe ↗]({recipe.source_url})"

    embed = discord.Embed(
        title=f"🍒 {recipe.title}",
        description=(
            f"{_no_wrap('❦ · ❦ · ❦ · ❦ · ❦ · ❦ · ❦ · ❦ · ❦ · ❦ · ❦ · ❦ · ❦ · ❦ · ❦ · ❦ · ❦ · ❦ · ❦')}\n"
            f"{source_line}"
        ),
        color=RECIPE_BOX_COLOR,
    )
    embed.set_author(name="Rosie's Recipe Box")

    if recipe.image_url:
        if should_use_thumbnail(recipe.image_url):
            embed.set_thumbnail(url=recipe.image_url)
        else:
            embed.set_image(url=recipe.image_url)

    tags = _display_tags(recipe.tags)
    if tags:
        embed.add_field(
            name="🏷️ Categories",
            value="\n".join(tags),
            inline=False,
        )

    timing = []
    if recipe.prep_time:
        timing.append(_no_wrap(f"**Prep** {recipe.prep_time}"))
    if recipe.cook_time:
        timing.append(_no_wrap(f"**Cook** {recipe.cook_time}"))
    if recipe.total_time:
        timing.append(_no_wrap(f"**Total** {recipe.total_time}"))

    if timing:
        embed.add_field(
            name="⏱️ Time",
            value="  •  ".join(timing),
            inline=False,
        )

    embed.add_field(
        name="🍽️ Servings",
        value=recipe.yields or "Not provided",
        inline=True,
    )

    embed.add_field(
        name="🧺 Ingredients",
        value=_truncate_ingredient_lines(recipe.ingredients),
        inline=False,
    )

    embed.set_footer(text="🍒 Filed in Rosie's Recipe Box")
    return embed
