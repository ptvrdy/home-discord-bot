import discord

from models.recipe_card import Recipe
from services.embed import create_recipe_embed
from config.discord_tags import DISCORD_TAGS


MAX_APPLIED_FORUM_TAGS = 5
HUMAN_TAGS = {"needs_review", "made_before", "make_again", "favorite"}

_VARIATION_SELECTORS = "︎️"


def normalize_tag_name(name: str) -> str:
    """Strip emoji variation selectors so a tag still matches even if Discord's
    actual forum tag and our config disagree on whether an emoji like "⏱"
    carries the invisible presentation-selector character that follows it."""
    return "".join(character for character in name if character not in _VARIATION_SELECTORS)


HUMAN_TAG_PRIORITY = {
    "favorite": 0,
    "make_again": 1,
    "made_before": 2,
    "needs_review": 3,
}
TAG_PRIORITY = {
    "needs_review": 0,
    "favorite": 1,
    "made_before": 1,
    "make_again": 1,
    "beef": 10,
    "chicken": 10,
    "pork": 10,
    "seafood": 10,
    "tofu": 10,
    "vegetarian": 10,
    "pasta": 20,
    "soup": 20,
    "dessert": 20,
    "one_pot": 30,
    "slow_cooker": 30,
    "quick": 40,
    "long": 40,
    "breakfast": 60,
    "lunch": 60,
    "dinner": 60,
}


def keep_single_human_tag(tags: list[discord.ForumTag]) -> list[discord.ForumTag]:
    """Keep the most definitive human status tag and preserve every other tag."""
    tag_keys_by_name = {
        normalize_tag_name(tag_info["discord_name"]): tag_key
        for tag_key, tag_info in DISCORD_TAGS.items()
    }
    human_tags = [
        tag for tag in tags
        if tag_keys_by_name.get(normalize_tag_name(tag.name)) in HUMAN_TAGS
    ]
    if len(human_tags) <= 1:
        return tags

    kept_human_tag = min(
        human_tags,
        key=lambda tag: HUMAN_TAG_PRIORITY[tag_keys_by_name[normalize_tag_name(tag.name)]],
    )
    return [
        tag for tag in tags
        if tag not in human_tags or tag == kept_human_tag
    ]


def tags_with_human_status(
    channel: discord.ForumChannel,
    current_tags: list[discord.ForumTag],
    status_key: str,
) -> list[discord.ForumTag]:
    """Replace a recipe's human status while preserving its other forum tags."""
    if status_key not in HUMAN_TAGS:
        raise ValueError(f"Unknown human status: {status_key}")

    tag_keys_by_name = {
        normalize_tag_name(tag_info["discord_name"]): tag_key
        for tag_key, tag_info in DISCORD_TAGS.items()
    }
    non_human_tags = [
        tag for tag in current_tags
        if tag_keys_by_name.get(normalize_tag_name(tag.name)) not in HUMAN_TAGS
    ]
    available_tags = {normalize_tag_name(tag.name): tag for tag in channel.available_tags}
    status_tag = available_tags.get(normalize_tag_name(DISCORD_TAGS[status_key]["discord_name"]))
    if status_tag is None:
        raise ValueError(f"The forum is missing the {status_key} tag")

    non_human_tags.sort(
        key=lambda tag: TAG_PRIORITY.get(tag_keys_by_name.get(normalize_tag_name(tag.name), ""), 100),
    )
    return [status_tag, *non_human_tags][:MAX_APPLIED_FORUM_TAGS]


def get_matching_tags(
    channel: discord.ForumChannel,
    recipe_tags: list[str],
) -> list[discord.ForumTag]:
    """Convert logical recipe tags into Discord ForumTag objects."""

    discord_tag_keys = []

    for tag_key in recipe_tags:
        tag_info = DISCORD_TAGS.get(tag_key)

        if tag_info is None:
            print(f"Unknown tag: {tag_key}")
            continue

        discord_tag_keys.append(tag_key)

    unique_tag_keys = dict.fromkeys(discord_tag_keys)
    human_tag_keys = [
        tag_key for tag_key in unique_tag_keys
        if tag_key in HUMAN_TAGS
    ]
    selected_human_tag = min(
        human_tag_keys,
        key=lambda tag_key: HUMAN_TAG_PRIORITY[tag_key],
        default=None,
    )
    non_human_tag_keys = [
        tag_key for tag_key in unique_tag_keys
        if tag_key not in HUMAN_TAGS
    ]
    prioritized_tag_keys = ([] if selected_human_tag is None else [selected_human_tag]) + sorted(
        non_human_tag_keys,
        key=lambda tag_key: TAG_PRIORITY.get(tag_key, 100),
    )

    available_tags = {normalize_tag_name(tag.name): tag for tag in channel.available_tags}
    return [
        available_tags[normalize_tag_name(DISCORD_TAGS[tag_key]["discord_name"])]
        for tag_key in prioritized_tag_keys
        if normalize_tag_name(DISCORD_TAGS[tag_key]["discord_name"]) in available_tags
    ][:MAX_APPLIED_FORUM_TAGS]


async def create_recipe_post(
    channel: discord.ForumChannel,
    recipe: Recipe,
) -> discord.Thread:
    title = recipe.title or "Untitled Recipe"

    embed = create_recipe_embed(recipe)

    tags = get_matching_tags(channel, recipe.tags)

    created_thread = await channel.create_thread(
        name=title[:100],
        embed=embed,
        applied_tags=tags,
    )
    return created_thread.thread


def diagnose_tags(available_tag_names: list[str]) -> dict:
    """Compare every configured tag against a forum's actual tag names.

    Returns {"ok": [...], "mismatched": [(configured, actual), ...], "missing": [...]}
    so a setup-check command can report exactly what needs fixing.
    """
    available_by_exact = set(available_tag_names)
    available_by_normalized = {
        normalize_tag_name(name): name for name in available_tag_names
    }

    ok, mismatched, missing = [], [], []
    for tag_info in DISCORD_TAGS.values():
        configured_name = tag_info["discord_name"]
        if configured_name in available_by_exact:
            ok.append(configured_name)
            continue

        normalized = normalize_tag_name(configured_name)
        if normalized in available_by_normalized:
            mismatched.append((configured_name, available_by_normalized[normalized]))
        else:
            missing.append(configured_name)

    return {"ok": ok, "mismatched": mismatched, "missing": missing}
