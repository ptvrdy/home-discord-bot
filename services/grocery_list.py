"""OurGroceries integration.

OurGroceries has no official API. This wraps the community-maintained
`ourgroceries` package, which reverse-engineers the same endpoints their
mobile app uses (username/password login, no API keys). Because it's
unofficial, response shapes aren't guaranteed - this was built against
version 1.5.4 and verified against Home Assistant's production integration
(which uses the same library), but hasn't been exercised against a real
account. If OurGroceries changes their site, this may need updating.
"""

import os

from ourgroceries import OurGroceries


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


def _existing_item_names(list_items_response: dict) -> set[str]:
    """Item text has been seen under both "value" and "name" depending on
    the response path, so check both rather than assume one."""
    items = list_items_response.get("list", {}).get("items", [])
    names = set()
    for item in items:
        text = item.get("value") or item.get("name") or ""
        if text.strip():
            names.add(text.strip().lower())
    return names


async def add_recipe_ingredients(
    list_id: str,
    ingredients: list[str],
    recipe_title: str,
    client: OurGroceries | None = None,
) -> dict:
    """Add a recipe's ingredients to a list, skipping anything already on it.

    Returns {"added": [...], "skipped": [...]}.
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

    return {"added": added, "skipped": skipped}
