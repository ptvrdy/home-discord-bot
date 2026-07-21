"""OurGroceries integration.

OurGroceries has no official API. This wraps the community-maintained
`ourgroceries` package, which reverse-engineers the same endpoints their
mobile app uses (username/password login, no API keys). Because it's
unofficial, response shapes aren't guaranteed - this was built against
version 1.5.4, verified against Home Assistant's production integration
(which uses the same library), and has since been exercised against a real
account. If OurGroceries changes their site, this may need updating. See
docs/ourgroceries-api-notes.md for the full reverse-engineering writeup.

Policy: every call here is triggered by a specific Discord interaction a
person clicked - a slash command, a select, a button. Nothing in this module
should ever run on a timer or poll in the background. An OurGroceries
developer has publicly asked integrators to keep API usage light (see the
docs file above); if a future feature needs recurring/scheduled data (e.g. a
"remind me what's on my list" nudge), reconsider the call pattern rather than
adding a naive polling loop.
"""

import os
import re

from ourgroceries import OurGroceries


# Common pantry staples, ordered from "almost everyone already has this" to
# "less certain" - used to decide what to drop first if a recipe has more
# ingredients than fit in Discord's 24-button cap for the ingredient-picker
# UI. Earlier entries are dropped before later ones, regardless of where the
# ingredient happens to appear in the recipe itself.
PANTRY_STAPLES = [
    "salt", "kosher salt", "sea salt", "table salt", "black pepper", "pepper", "water",
    "sugar", "brown sugar", "powdered sugar", "confectioners sugar",
    "flour", "corn starch", "cornstarch",
    "baking soda", "baking powder", "cream of tartar",
    "olive oil", "vegetable oil", "canola oil", "cooking oil", "cooking spray", "sesame oil",
    "vanilla extract", "vanilla",
    "cinnamon", "nutmeg", "ground ginger", "cayenne pepper", "paprika", "cumin",
    "chili powder", "oregano", "italian seasoning", "bay leaf", "bay leaves",
    "garlic powder", "onion powder", "red pepper flakes",
    "white vinegar", "apple cider vinegar", "rice vinegar",
    "soy sauce", "worcestershire sauce", "hot sauce", "ketchup", "mustard", "mayonnaise",
    "honey", "breadcrumbs", "panko", "yeast", "cocoa powder",
]


def _staple_rank(ingredient: str) -> int | None:
    """Lower rank = more universally already-owned = dropped first.
    None means it's not a recognized staple at all."""
    text = ingredient.lower()
    for rank, staple in enumerate(PANTRY_STAPLES):
        if re.search(r"\b" + re.escape(staple) + r"'?s?\b", text):
            return rank
    return None


def prioritize_ingredients(ingredients: list[str], limit: int) -> list[str]:
    """If there are more ingredients than fit, drop the most universal pantry
    staples first (regardless of where they appear in the recipe), only
    touching non-staples if every staple has already been dropped. Keeps the
    original relative order among whatever's kept."""
    if len(ingredients) <= limit:
        return ingredients

    indexed = list(enumerate(ingredients))

    def drop_key(pair):
        index, ingredient = pair
        rank = _staple_rank(ingredient)
        if rank is None:
            return (1, 0, index)  # not a staple: drop only as a last resort
        return (0, rank, index)  # staples: most universal dropped first

    drop_count = len(ingredients) - limit
    droppable_first = sorted(indexed, key=drop_key)
    dropped_indices = {index for index, _ in droppable_first[:drop_count]}

    return [ingredient for index, ingredient in indexed if index not in dropped_indices]


def _client() -> OurGroceries:
    username = os.getenv("OURGROCERIES_USERNAME")
    password = os.getenv("OURGROCERIES_PASSWORD")
    if not username or not password:
        raise RuntimeError(
            "OURGROCERIES_USERNAME and OURGROCERIES_PASSWORD must be set in .env"
        )
    return OurGroceries(username, password)


async def get_grocery_lists(client: OurGroceries | None = None) -> list[dict]:
    """Return every list on the account as [{"id": ..., "name": ...}, ...]."""
    client = client or _client()
    await client.login()
    response = await client.get_my_lists()
    return [
        {"id": shopping_list["id"], "name": shopping_list["name"]}
        for shopping_list in response["shoppingLists"]
    ]


def _is_crossed_off(item: dict) -> bool:
    """The `ourgroceries` library's own "crossedOff" default-False normalizer
    only preserves that key if the raw server response already used it - and
    the actual field appears to be "crossedOffAt" (a timestamp) instead, based
    on how Home Assistant's production integration reads it. Check both."""
    return bool(item.get("crossedOff") or item.get("crossedOffAt"))


def _item_text(item: dict) -> str:
    """Item text has been seen under both "value" and "name" depending on
    the response path, so check both rather than assume one."""
    return (item.get("value") or item.get("name") or "").strip()


def _existing_item_names(list_items_response: dict) -> set[str]:
    """Crossed-off items are skipped entirely - crossing something off means
    "bought it," not "keep this list line forever," so it should be addable
    again."""
    items = list_items_response.get("list", {}).get("items", [])
    names = set()
    for item in items:
        if _is_crossed_off(item):
            continue

        text = _item_text(item)
        if text:
            names.add(text.lower())
    return names


async def get_list_contents(list_id: str, client: OurGroceries | None = None) -> dict:
    """Return a list's current items, split into what's still needed and
    what's already been crossed off. Returns {"active": [...], "crossed_off": [...]}."""
    client = client or _client()
    await client.login()

    response = await client.get_list_items(list_id)
    items = response.get("list", {}).get("items", [])

    active = []
    crossed_off = []
    for item in items:
        text = _item_text(item)
        if not text:
            continue
        (crossed_off if _is_crossed_off(item) else active).append(text)

    return {"active": active, "crossed_off": crossed_off}


async def find_existing_locations(
    ingredients: list[str],
    client: OurGroceries | None = None,
) -> dict[str, str]:
    """Check every list on the account (not just one) for each ingredient,
    case-insensitive, active items only. Returns {ingredient_lower: list_name}
    for whichever list each match was first found on. Stops checking further
    lists as soon as every ingredient has been located, to keep this light -
    OurGroceries' developer has asked integrators to avoid unnecessary calls."""
    client = client or _client()
    await client.login()

    wanted = {ingredient.strip().lower() for ingredient in ingredients}
    locations: dict[str, str] = {}

    lists_response = await client.get_my_lists()
    for shopping_list in lists_response["shoppingLists"]:
        if wanted <= locations.keys():
            break

        list_response = await client.get_list_items(shopping_list["id"])
        for item in list_response.get("list", {}).get("items", []):
            if _is_crossed_off(item):
                continue

            text = _item_text(item).lower()
            if text in wanted and text not in locations:
                locations[text] = shopping_list["name"]

    return locations


async def add_recipe_ingredients(
    list_id: str,
    ingredients: list[str],
    recipe_title: str,
    client: OurGroceries | None = None,
) -> dict:
    """Add a recipe's ingredients to a list, skipping anything already on it.

    Returns {"added": [...], "skipped": [...], "added_item_ids": [...]}.
    added_item_ids supports undoing the add later via remove_items(); it's
    filled in by re-fetching the list after adding and matching by text,
    rather than trusting whatever add_item_to_list's own response contains -
    that shape isn't verified (see services/grocery_list.py module docstring).
    """
    client = client or _client()
    await client.login()

    existing_response = await client.get_list_items(list_id)
    existing = _existing_item_names(existing_response)

    added = []
    skipped = []
    for ingredient in ingredients:
        if ingredient.strip().lower() in existing:
            skipped.append(ingredient)
            continue

        await client.add_item_to_list(
            list_id,
            ingredient,
            auto_category=True,
            note=recipe_title,
        )
        added.append(ingredient)

    added_item_ids = []
    if added:
        added_lower = {ingredient.strip().lower() for ingredient in added}
        refreshed = await client.get_list_items(list_id)
        for item in refreshed.get("list", {}).get("items", []):
            if _is_crossed_off(item):
                continue
            if _item_text(item).lower() in added_lower:
                item_id = item.get("id")
                if item_id is not None:
                    added_item_ids.append(item_id)

    return {"added": added, "skipped": skipped, "added_item_ids": added_item_ids}


async def remove_items(
    list_id: str,
    item_ids: list[str],
    client: OurGroceries | None = None,
) -> None:
    """Remove specific items from a list by ID - used to undo a recent add."""
    client = client or _client()
    await client.login()
    for item_id in item_ids:
        await client.remove_item_from_list(list_id, item_id)
