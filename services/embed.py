import discord

from config.discord_tags import DISCORD_TAGS
from models.recipe_card import Recipe
from services.image_layout import should_use_thumbnail


RECIPE_BOX_COLOR = 0xA8391F
INGREDIENT_FIELD_LIMIT = 1024
INSTRUCTIONS_DESCRIPTION_LIMIT = 4096


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


def _numbered_steps(instructions: str) -> list[str]:
    """Split raw instruction text into individual "Step N." lines."""
    lines = [line.strip() for line in instructions.splitlines() if line.strip()]
    return [f"**Step {index}.** {line}" for index, line in enumerate(lines, start=1)]


def _build_instructions_description(instructions: str) -> str:
    """Render numbered steps, dropping trailing steps if it would overflow
    Discord's 4,096-character embed description limit."""
    steps = _numbered_steps(instructions)
    truncated = False

    while steps:
        description = "\n\n".join(steps)
        suffix = "\n\n…" if truncated else ""
        if len(description) + len(suffix) <= INSTRUCTIONS_DESCRIPTION_LIMIT:
            return description + suffix
        steps.pop()
        truncated = True

    return "Not provided"


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

    summary_parts = []
    if recipe.yields:
        summary_parts.append(_no_wrap(f"🍽 {recipe.yields}"))
    if recipe.total_time:
        summary_parts.append(_no_wrap(f"⏱ {recipe.total_time}"))

    description_lines = []
    if summary_parts:
        description_lines.append("  •  ".join(summary_parts))
    description_lines.append(_no_wrap("❦ · ❦ · ❦"))
    description_lines.append(source_line)

    embed = discord.Embed(
        title=f"🍒 {recipe.title}",
        description="\n".join(description_lines),
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


def build_instructions_embed(recipe: Recipe) -> discord.Embed | None:
    """A separate, numbered-step embed posted right after the recipe card -
    instructions get much more room here (4,096 chars) than they would as a
    field on the main card (1,024 chars)."""
    if not recipe.instructions:
        return None

    embed = discord.Embed(
        title="📖 Instructions",
        description=_build_instructions_description(recipe.instructions),
        color=RECIPE_BOX_COLOR,
    )
    embed.set_footer(text="🍒 Filed in Rosie's Recipe Box")
    return embed


HELP_SECTIONS = [
    (
        "📥 Import",
        [("/recipe <url>", "Import a recipe from the web, or by hand for TikTok/unscrapeable links.")],
    ),
    (
        "🏷️ Organize & Fix",
        [
            ("/tags", "Manually add or remove this recipe's tags. (run in its thread)"),
            ("/fix", "Correct a recipe's name, times, or servings. (run in its thread)"),
        ],
    ),
    (
        "🔍 Find",
        [
            ("/find_ingredient <query>", "Search recipes by title or ingredient."),
            ("/random [tag]", "Suggest a random recipe, optionally filtered by tag."),
            ("/needs_review", "List every recipe still marked Needs Review."),
        ],
    ),
    (
        "⭐ Review & Stats",
        [
            ("/review", "Log that you made/reviewed a recipe, rate it, leave notes. (run in its thread)"),
            ("/cooking_stats", "Top rated, most cooked, and who's been logging reviews."),
        ],
    ),
    (
        "🛒 Grocery Shopping",
        [
            ("/shopping_list", "Add a recipe's ingredients to an OurGroceries list. (run in its thread)"),
            ("/combine_recipes", "Combine ingredients from up to 5 recipes into one shopping list."),
            ("/meal_plan", "Suggest random recipes and combine their ingredients into one shopping list."),
            ("/grocery_list", "See what's currently on one of your OurGroceries lists."),
        ],
    ),
    (
        "🧹 Household Chores",
        [("/done <chore>", "Mark a chore as completed. Add someone to attribute it to them instead of yourself.")],
    ),
    (
        "📅 Schedule",
        [
            ("/task <request>", 'Schedule a quick one-off task, e.g. "call vet" or "call vet thursday at 5pm". Proposes a free slot for you to confirm, unless you gave an exact time.'),
            ("/week", "Schedule up to 5 one-off tasks this week — autocomplete suggests your chores, but you can type anything. Proposes a free slot for each."),
            ("/refresh_this_week", "Manually rebuild the #this-week schedule embed instead of waiting for the daily refresh."),
        ],
    ),
    (
        "⚙️ Admin",
        [
            ("/check_setup", "Verify every configured tag actually matches a tag on the forum."),
            ("/check_calendar_setup", "Verify the Google service account can reach each configured calendar."),
        ],
    ),
]


def build_help_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🍒 Rosie's Recipe Box — Commands",
        description="Commands marked \"(run in its thread)\" only work inside a recipe's forum thread.",
        color=RECIPE_BOX_COLOR,
    )
    for section_name, commands in HELP_SECTIONS:
        value = "\n".join(f"**{name}** — {description}" for name, description in commands)
        embed.add_field(name=section_name, value=value, inline=False)
    embed.set_footer(text="🍒 Filed in Rosie's Recipe Box")
    return embed


def build_stats_embed(stats: dict) -> discord.Embed:
    """Render aggregate household cooking stats (box size, review backlog,
    top-rated/most-cooked recipes, per-person activity) into one embed."""
    embed = discord.Embed(title="📊 Cooking Stats", color=RECIPE_BOX_COLOR)

    embed.add_field(
        name="🍒 Recipe Box",
        value=_no_wrap(
            f"{stats['total_recipes']} recipes  •  {stats['needs_review_count']} need review"
        ),
        inline=False,
    )

    if stats["top_rated"]:
        lines = [
            f"⭐ {entry['avg_rating']:.1f} — **{entry['title']}**"
            for entry in stats["top_rated"]
        ]
        embed.add_field(name="Top Rated", value="\n".join(lines), inline=False)

    if stats["most_cooked"]:
        lines = [
            f"🍳 {entry['times_made']}x — **{entry['title']}**"
            for entry in stats["most_cooked"]
        ]
        embed.add_field(name="Most Cooked", value="\n".join(lines), inline=False)

    if stats["by_author"]:
        lines = [
            f"{entry['author_name']}: {entry['entry_count']}"
            for entry in stats["by_author"]
        ]
        embed.add_field(name="Reviews Logged", value="\n".join(lines), inline=True)

    embed.set_footer(text="🍒 Filed in Rosie's Recipe Box")
    return embed
