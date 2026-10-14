"""Checking the recipe forum against the database, and rebuilding a recipe
from its forum post when the database lost it.

The forum post and the database row are written separately (post first,
then row), so a failure in between leaves a post the database doesn't know
about - invisible to /find_ingredient, /random, /what_can_i_make, /review.
Pure helpers here; /check_recipes (commands/recipe_sync_commands.py) does
the Discord and scraping parts.
"""

import re

from config.discord_tags import DISCORD_TAGS
from models.recipe_card import Recipe
from services.embed import ATTACHMENT_PREFIX
from services.forum import HUMAN_TAGS, normalize_tag_name
from services.time_parser import parse_minutes

_SOURCE_LINK = re.compile(r"\[View the original recipe ↗\]\((?P<url>[^)\s]+)\)")
_SOURCE_NAME = re.compile(r"From \*\*(?P<name>.+?)\*\*")
_STEP_PREFIX = re.compile(r"^\*\*Step \d+\.\*\*\s*")
_TIMING = re.compile(r"\*\*(?P<label>Prep|Cook|Total)\*\*\s*(?P<value>[^•]+)")


def find_mismatches(
    threads: dict[int, str],
    db_rows: list[dict],
) -> tuple[list[tuple[int, str]], list[dict]]:
    """threads: {thread id: title} for every post in the recipe forum.
    db_rows: [{"title", "discord_thread_id"}] from the database.
    Returns (posts the database is missing, database rows whose post is
    gone), each sorted by title."""
    in_db = {row["discord_thread_id"] for row in db_rows}
    missing_in_db = sorted(
        ((thread_id, title) for thread_id, title in threads.items() if thread_id not in in_db),
        key=lambda pair: pair[1].lower(),
    )
    missing_in_forum = sorted(
        (row for row in db_rows if row["discord_thread_id"] not in threads),
        key=lambda row: row["title"].lower(),
    )
    return missing_in_db, missing_in_forum


def tag_keys_from_forum_tags(tag_names: list[str]) -> list[str]:
    """Forum tag labels on a post -> Rosie's logical tag keys (beef, dinner,
    favorite, ...), tolerant of invisible emoji differences."""
    by_name = {normalize_tag_name(info["discord_name"]): key for key, info in DISCORD_TAGS.items()}
    return [by_name[normalize_tag_name(name)] for name in tag_names if normalize_tag_name(name) in by_name]


def _plain(text: str) -> str:
    return text.replace("\xa0", " ").strip()


def recipe_from_post(card: dict, instructions_text: str | None, tag_names: list[str]) -> tuple[Recipe, bool]:
    """Rebuild a recipe from its forum post: the card embed (as a dict, from
    discord.Embed.to_dict()), the instructions message's text, and the post's
    forum tags. Returns (recipe, complete) - complete is False when the card
    had cut the ingredients or instructions short to fit Discord's limits."""
    title = _plain(card.get("title", "")).removeprefix("🍒").strip() or "Untitled Recipe"
    description = _plain(card.get("description", ""))
    fields = {_plain(field["name"]): field["value"] for field in card.get("fields", [])}
    complete = True

    link = _SOURCE_LINK.search(description)
    name = _SOURCE_NAME.search(description)
    source_name = name.group("name") if name else None
    if source_name == "the original recipe":
        source_name = None

    ingredients = []
    for line in fields.get("🧺 Ingredients", "").splitlines():
        line = _plain(line)
        if line == "…":
            complete = False
        elif line.startswith("•"):
            ingredients.append(line.lstrip("•").strip())

    timing = {match.group("label").lower(): _plain(match.group("value")) for match in _TIMING.finditer(fields.get("⏱️ Time", ""))}
    servings = _plain(fields.get("🍽️ Servings", "")) or None
    if servings == "Not provided":
        servings = None

    instructions = None
    if instructions_text and instructions_text.strip() != "Not provided":
        steps = []
        for block in instructions_text.split("\n\n"):
            block = _plain(block)
            if block == "…":
                complete = False
            elif block:
                steps.append(_STEP_PREFIX.sub("", block))
        instructions = "\n".join(steps) or None

    image = (card.get("image") or card.get("thumbnail") or {}).get("url")
    if image:
        # A photo saved onto the card by /fix_image comes back as an expiring
        # Discord CDN link; store the stable attachment reference instead.
        file_name = image.split("?")[0].rsplit("/", 1)[-1]
        if "discordapp" in image and file_name.startswith("recipe-image"):
            image = ATTACHMENT_PREFIX + file_name
    tags = tag_keys_from_forum_tags(tag_names)
    if not any(tag in HUMAN_TAGS for tag in tags):
        tags.insert(0, "needs_review")

    recipe = Recipe(
        title=title,
        ingredients=ingredients,
        instructions=instructions,
        prep_time=timing.get("prep"),
        cook_time=timing.get("cook"),
        total_time=timing.get("total"),
        total_minutes=parse_minutes(timing.get("total")) or parse_minutes(timing.get("cook")),
        yields=servings,
        image_url=image,
        source_url=link.group("url") if link else "",
        source_name=source_name,
        tags=tags,
    )
    return recipe, complete
