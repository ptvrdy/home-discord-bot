"""Which OurGroceries lists are grocery stores, for the pantry.

Each grocery list is a store: crossing items off it and running /put_away
records the purchase at that store (a "store" in Grocy, named after the
list). Lists not named here - CVS, Marshalls, the liquor store - are never
offered for the pantry.

Trader Joe's is special: its purchases get the TJ's catalog match, photo,
and price. At every other store the price is what you actually pay (Grocy
remembers it per barcode), and new items get their section and shelf life
from their name.

Override per machine in .env (comma-separated), e.g. for a dev bot:
    PANTRY_STORE_LISTS=Rosie Test,Urban Market
    PANTRY_TJ_LIST=Rosie Test
"""

import os

TRADER_JOES_LIST = "Trader Joe's"

GROCERY_STORE_LISTS = [
    TRADER_JOES_LIST,
    "Urban Market",        # the regular grocery store by the house (Key Food)
    "Whole Foods",         # specialty items, or a car trip
    "Farmers Market",      # produce, sometimes milk and ground turkey
    "Ideal Food Basket",
]


def store_lists() -> list[str]:
    configured = os.getenv("PANTRY_STORE_LISTS")
    if configured:
        return [name.strip() for name in configured.split(",") if name.strip()]
    return GROCERY_STORE_LISTS


def trader_joes_list() -> str:
    return os.getenv("PANTRY_TJ_LIST") or TRADER_JOES_LIST


def is_grocery_list(list_name: str) -> bool:
    return list_name.strip().lower() in {name.lower() for name in store_lists()}


def is_trader_joes(store_name: str | None) -> bool:
    """No store recorded counts as Trader Joe's - it's the household's main
    store, and every purchase before stores were tracked was from there."""
    return store_name is None or store_name.strip().lower() == trader_joes_list().lower()


def match_store(text: str) -> str | None:
    """The store a phrase like "urban market" or "whole foods" refers to
    (case-insensitive; "trader joes"/"tjs" count as Trader Joe's)."""
    wanted = text.strip().lower().replace("’", "'")
    if wanted in {"tj's", "tjs", "trader joes", "trader joe's", "traders"}:
        return trader_joes_list()
    for name in store_lists():
        if name.lower() == wanted or name.lower().replace("'", "") == wanted.replace("'", ""):
            return name
    return None
