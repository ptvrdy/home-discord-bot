"""Pantry operations: everything that combines Grocy (what's in stock),
the Trader Joe's catalog (what things are), and the matcher (what people
mean). Discord-free, so commands/pantry_commands.py stays thin.

Pantry products are generic household names ("Chicken thigh", "Egg") - the
words people already type into OurGroceries and recipes use - with the TJ's
item they were bought as attached for photo, price, category, and shelf life.
Products are created the first time something is bought, never in bulk, so
Grocy only ever holds things this household actually buys.
"""

import logging
import re
from dataclasses import dataclass, field

from config.shelf_life import FREEZER, FRIDGE, NEVER_EXPIRES, PANTRY, guess_category, shelf_life_for
from services.database import (
    get_pantry_aliases,
    get_pantry_products,
    get_tj_catalog,
    get_tj_product,
    record_pantry_product,
    set_pantry_alias,
)
from services.grocy import Grocy, GrocyError
from services.ingredient_match import (
    CONFIDENT_SCORE,
    Match,
    best_product_match,
    best_tj_match,
    display_name,
    item_words,
    normalize_item,
    parse_quantity,
    rank_matches,
)
from services.pantry_parser import ADD, CONSUME_ALL, FREEZE, OPEN, SPOIL, PantryAction
from services.tj_catalog import barcodes_for_sku, download_image, sku_from_barcode

logger = logging.getLogger(__name__)

LOCATIONS = {FRIDGE: False, FREEZER: True, PANTRY: False}  # name -> is_freezer
DEFAULT_UNIT_NAMES = ("Piece", "Pieces", "Pack", "Unit", "Each")

# Per-process cache of Grocy IDs for locations/units/groups, keyed by Grocy URL.
_setup_cache: dict[str, dict] = {}


# --- one-time Grocy setup ---


async def ensure_setup(grocy: Grocy) -> dict:
    """Make sure the locations and a counting unit Rosie relies on exist,
    creating any that are missing, so a fresh Grocy needs no manual setup
    beyond an API key. Returns {"locations": {name: id}, "unit_id": id,
    "groups": {name: id}}; cached for the life of the process."""
    if grocy.base_url in _setup_cache:
        return _setup_cache[grocy.base_url]

    existing_locations = {row["name"]: int(row["id"]) for row in await grocy.get_objects("locations")}
    locations = {}
    for name, is_freezer in LOCATIONS.items():
        if name in existing_locations:
            locations[name] = existing_locations[name]
        else:
            locations[name] = await grocy.create_object(
                "locations", {"name": name, "is_freezer": 1 if is_freezer else 0}
            )

    units = await grocy.get_objects("quantity_units")
    unit_id = next((int(unit["id"]) for unit in units if unit["name"] in DEFAULT_UNIT_NAMES), None)
    if unit_id is None:
        unit_id = await grocy.create_object("quantity_units", {"name": "Piece", "name_plural": "Pieces"})

    groups = {row["name"]: int(row["id"]) for row in await grocy.get_objects("product_groups")}

    setup = {"locations": locations, "unit_id": unit_id, "groups": groups}
    _setup_cache[grocy.base_url] = setup
    return setup


async def _group_id(grocy: Grocy, setup: dict, name: str | None) -> int | None:
    if not name:
        return None
    if name not in setup["groups"]:
        setup["groups"][name] = await grocy.create_object("product_groups", {"name": name})
    return setup["groups"][name]


# --- the pantry as Rosie sees it ---


@dataclass
class PantryState:
    """A snapshot of Grocy plus Rosie's learned aliases, loaded once per
    interaction so matching many items doesn't mean many API calls."""

    products: list[dict]
    aliases: dict[str, int]
    stock: dict[int, float]  # product_id -> amount on hand
    tj_skus: dict[int, str] = field(default_factory=dict)  # product_id -> TJ's sku

    def amount(self, product_id: int) -> float:
        return self.stock.get(product_id, 0.0)

    def match(self, text: str) -> Match | None:
        return best_product_match(text, self.products, self.aliases)

    def candidates(self, text: str, limit: int = 3) -> list[Match]:
        return rank_matches(text, self.products)[:limit]

    def product(self, product_id: int) -> dict | None:
        return next((product for product in self.products if product["id"] == product_id), None)


async def load_state(grocy: Grocy) -> PantryState:
    products = [
        {"id": int(row["id"]), "name": row["name"], "location_id": row.get("location_id")}
        for row in await grocy.get_objects("products")
        if str(row.get("active", 1)) != "0"
    ]
    stock: dict[int, float] = {}
    for row in await grocy.get_stock():
        product_id = int(row["product_id"])
        stock[product_id] = stock.get(product_id, 0.0) + float(row.get("amount") or 0)
    tj_skus = {row["grocy_product_id"]: row["tj_sku"] for row in get_pantry_products() if row["tj_sku"]}
    return PantryState(products, get_pantry_aliases(), stock, tj_skus)


def learn(text: str, product_id: int, created_by: str | None = None) -> None:
    """Remember a person-confirmed match so it's instant next time."""
    set_pantry_alias(normalize_item(text), product_id, created_by)


# --- creating products from TJ's ---


def suggest_tj_item(text: str, catalog: list[dict] | None = None) -> dict | None:
    catalog = catalog if catalog is not None else get_tj_catalog()
    match = best_tj_match(text, catalog)
    return match.item if match else None


async def create_product(
    grocy: Grocy,
    state: PantryState,
    text: str,
    tj_item: dict | None,
    created_by: str | None = None,
) -> dict:
    """Create a generic pantry product for free text like "chicken thighs",
    filled in from its TJ's match: photo, product group, home location, and
    default shelf life. Adds it to `state` and learns the alias."""
    setup = await ensure_setup(grocy)
    if tj_item:
        category, subcategory = tj_item.get("category"), tj_item.get("subcategory")
    else:
        # No believable TJ's match (their online catalog skips a lot of
        # basic produce) - still get the aisle right from keywords.
        category, subcategory = guess_category(item_words(text), frozen=bool(re.search(r"\bfrozen\b", text.lower())))
    rule = shelf_life_for(category, subcategory)
    name = display_name(text)

    data = {
        "name": name,
        "location_id": setup["locations"][rule["location"]],
        "qu_id_purchase": setup["unit_id"],
        "qu_id_stock": setup["unit_id"],
        "qu_id_consume": setup["unit_id"],
        "qu_id_price": setup["unit_id"],
        "default_best_before_days": rule["days"],
        "default_best_before_days_after_freezing": rule["freezer_days"],
        "default_best_before_days_after_thawing": 1 if rule["days"] != NEVER_EXPIRES else 0,
        "min_stock_amount": 0,
    }
    group_id = await _group_id(grocy, setup, category)
    if group_id is not None:
        data["product_group_id"] = group_id

    try:
        product_id = await grocy.create_object("products", data)
    except GrocyError as error:
        # Grocy 3.x has no qu_id_consume / qu_id_price columns.
        if "qu_id_consume" not in str(error) and "qu_id_price" not in str(error):
            raise
        for key in ("qu_id_consume", "qu_id_price"):
            data.pop(key, None)
        product_id = await grocy.create_object("products", data)

    if tj_item and tj_item.get("image_url"):
        await _attach_picture(grocy, product_id, tj_item)
    if tj_item:
        await _register_barcodes(grocy, product_id, tj_item["sku"])

    record_pantry_product(product_id, name, tj_item["sku"] if tj_item else None)
    learn(text, product_id, created_by)

    product = {"id": product_id, "name": name, "location_id": data["location_id"]}
    state.products.append(product)
    state.aliases[normalize_item(text)] = product_id
    if tj_item:
        state.tj_skus[product_id] = tj_item["sku"]
    return product


async def _attach_picture(grocy: Grocy, product_id: int, tj_item: dict) -> None:
    content = await download_image(tj_item["image_url"])
    if not content:
        return
    extension = tj_item["image_url"].rsplit(".", 1)[-1].lower()
    file_name = f"tj-{tj_item['sku']}.{extension if extension in {'png', 'jpg', 'jpeg', 'webp'} else 'png'}"
    try:
        await grocy.upload_product_picture(file_name, content)
        await grocy.update_object("products", product_id, {"picture_file_name": file_name})
    except GrocyError as error:
        logger.warning("Couldn't attach a picture to product %s: %s", product_id, error)


async def _register_barcodes(grocy: Grocy, product_id: int, sku: str, existing: set[str] | None = None) -> None:
    """Let Grocy's own barcode scanning (its mobile web UI, Barcode Buddy)
    recognize the TJ's package. Best-effort: a barcode already registered
    (here or to another product) is left alone."""
    for barcode in barcodes_for_sku(sku):
        if existing and barcode in existing:
            continue
        try:
            await grocy.create_object("product_barcodes", {"product_id": product_id, "barcode": barcode})
        except GrocyError as error:
            logger.info("Skipping barcode %s for product %s: %s", barcode, product_id, error)


async def relink_tj_item(grocy: Grocy, product_id: int, name: str, sku: str) -> None:
    """/pantry_fix: point a product at a different TJ's item (new photo,
    and its barcode now scans as this product too)."""
    tj_item = get_tj_product(sku)
    record_pantry_product(product_id, name, sku)
    if tj_item and tj_item.get("image_url"):
        await _attach_picture(grocy, product_id, tj_item)
    await _register_barcodes(grocy, product_id, sku)


# --- products scanned straight into Grocy ---


async def adopt_scanned_products(grocy: Grocy) -> list[str]:
    """Link products that were created by scanning a barcode in Grocy (via
    the Trader Joe's lookup plugin, or Open Food Facts before it) to their
    TJ's item, so they get everything a Rosie-made product has:

    - the TJ's photo (traderjoes.com blocks Grocy's own downloads)
    - the other lengths of the same barcode, so any scanner app matches
    - TJ's price on the barcode, for the Purchase page
    - a section, home location, and shelf life, if the product has none
      yet (Open Food Facts doesn't set them)
    - recall / "back at TJ's" tracking

    Only products whose barcode is a Trader Joe's-brand one and that Rosie
    doesn't know yet are touched; each is adopted once. Returns their names."""
    known = {row["grocy_product_id"] for row in get_pantry_products()}
    barcodes = await grocy.get_objects("product_barcodes")
    existing = {row["barcode"] for row in barcodes}

    candidates: dict[int, tuple[str, list[dict]]] = {}
    for row in barcodes:
        product_id = int(row["product_id"])
        sku = sku_from_barcode(row["barcode"])
        if sku is None or product_id in known:
            continue
        candidates.setdefault(product_id, (sku, []))[1].append(row)
    if not candidates:
        return []

    products = {int(row["id"]): row for row in await grocy.get_objects("products")}
    setup = await ensure_setup(grocy)
    adopted = []
    for product_id, (sku, barcode_rows) in candidates.items():
        product = products.get(product_id)
        tj_item = get_tj_product(sku)
        if product is None or tj_item is None:
            continue

        try:
            if not product.get("product_group_id"):
                rule = shelf_life_for(tj_item.get("category"), tj_item.get("subcategory"))
                update = {
                    "location_id": setup["locations"][rule["location"]],
                    "default_best_before_days": rule["days"],
                    "default_best_before_days_after_freezing": rule["freezer_days"],
                    "default_best_before_days_after_thawing": 1 if rule["days"] != NEVER_EXPIRES else 0,
                }
                group_id = await _group_id(grocy, setup, tj_item.get("category"))
                if group_id is not None:
                    update["product_group_id"] = group_id
                await grocy.update_object("products", product_id, update)
            if not product.get("picture_file_name") and tj_item.get("image_url"):
                await _attach_picture(grocy, product_id, tj_item)
            await _register_barcodes(grocy, product_id, sku, existing)
            if tj_item.get("price") is not None:
                for row in barcode_rows:
                    if not row.get("last_price"):
                        await grocy.update_object("product_barcodes", int(row["id"]), {"last_price": tj_item["price"]})
        except GrocyError as error:
            logger.warning("Couldn't fully adopt scanned product %s: %s", product_id, error)

        record_pantry_product(product_id, product["name"], sku)
        learn(product["name"], product_id)
        adopted.append(product["name"])
    return adopted


async def sync_barcode_prices(grocy: Grocy) -> int:
    """After a catalog sync: put each linked product's current TJ's price on
    its Trader Joe's barcodes, so the Purchase page pre-fills today's price.
    Returns how many barcodes changed."""
    prices = {row["grocy_product_id"]: row["tj_price"] for row in get_pantry_products() if row["tj_price"] is not None}
    changed = 0
    for row in await grocy.get_objects("product_barcodes"):
        price = prices.get(int(row["product_id"]))
        if price is None or sku_from_barcode(row["barcode"]) is None:
            continue
        if row.get("last_price") is None or abs(float(row["last_price"]) - price) > 0.001:
            await grocy.update_object("product_barcodes", int(row["id"]), {"last_price": price})
            changed += 1
    return changed


# --- put-away (OurGroceries crossed-off -> stock) ---


@dataclass
class PutAwayItem:
    """One crossed-off list item and what Rosie thinks it is."""

    og_item_id: str
    crossed_off_at: str
    list_id: str
    text: str
    product: dict | None  # an existing pantry product, if confidently matched
    tj_item: dict | None  # otherwise, the TJ's item it'll be created from

    def label(self) -> str:
        if self.product:
            return self.text if normalize_item(self.text) == normalize_item(self.product["name"]) else f"{self.text} → {self.product['name']}"
        if self.tj_item:
            return f"{self.text} → new: {self.tj_item['name']}"
        return f"{self.text} → new"


def plan_put_away(crossed_off: list[dict], state: PantryState, catalog: list[dict]) -> list[PutAwayItem]:
    plan = []
    for item in crossed_off:
        match = state.match(item["text"])
        product = match.item if match and match.score >= CONFIDENT_SCORE else None
        tj_item = None
        if product is None:
            tj_match = best_tj_match(item["text"], catalog)
            tj_item = tj_match.item if tj_match else None
        plan.append(
            PutAwayItem(item["item_id"], item["crossed_off_at"], item["list_id"], item["text"], product, tj_item)
        )
    return plan


@dataclass
class PutAwayResult:
    lines: list[str]
    transactions: list[str]
    done: list[PutAwayItem]  # only these were actually added to stock


async def put_away(
    grocy: Grocy,
    state: PantryState,
    items: list[PutAwayItem],
    created_by: str | None = None,
) -> PutAwayResult:
    """Add one of each item to stock (creating products as needed) at TJ's
    price. One item failing doesn't stop the rest - and what *did* get
    added is reported, so it can be undone and isn't offered again."""
    result = PutAwayResult([], [], [])
    for item in items:
        try:
            product = item.product or await create_product(grocy, state, item.text, item.tj_item, created_by)
            if item.product:
                learn(item.text, product["id"], created_by)
            sku = state.tj_skus.get(product["id"])
            tj_item = item.tj_item or (get_tj_product(sku) if sku else None)
            price = tj_item.get("price") if tj_item else None
            result.transactions.append(await grocy.add_stock(product["id"], 1, price=price))
        except GrocyError as error:
            result.lines.append(f"❌ {item.text}: {error}")
            continue
        state.stock[product["id"]] = state.amount(product["id"]) + 1
        result.lines.append(f"• {product['name']}" + (" _(new)_" if not item.product else ""))
        result.done.append(item)
    return result


# --- plain-English actions ---


@dataclass
class ActionResult:
    line: str
    transaction_id: str | None = None
    ran_out: str | None = None  # product name, when something hit zero


async def apply_action(
    grocy: Grocy,
    state: PantryState,
    action: PantryAction,
    product: dict | None,
    created_by: str | None = None,
) -> ActionResult:
    """Carry out one parsed action against an already-resolved product
    (or, for ADD with no product, create one from the TJ's catalog)."""
    if action.kind == ADD:
        if product is None:
            product = await create_product(grocy, state, action.item, suggest_tj_item(action.item), created_by)
        amount = action.amount or 1
        sku = state.tj_skus.get(product["id"])
        tj_item = get_tj_product(sku) if sku else None
        transaction = await grocy.add_stock(product["id"], amount, price=tj_item.get("price") if tj_item else None)
        state.stock[product["id"]] = state.amount(product["id"]) + amount
        return ActionResult(f"🛒 +{amount:g} {product['name']} ({state.amount(product['id']):g} on hand)", transaction)

    if product is None:
        return ActionResult(f"❓ I don't have **{action.item}** in the pantry.")

    on_hand = state.amount(product["id"])
    if on_hand <= 0 and action.kind != FREEZE:
        if action.kind == CONSUME_ALL:
            return ActionResult(f"✅ {product['name']} was already at 0.", ran_out=product["name"])
        return ActionResult(f"ℹ️ The pantry already shows 0 {product['name']}.")

    if action.kind == OPEN:
        transaction = await grocy.open_product(product["id"], 1)
        return ActionResult(f"📂 Opened {product['name']}", transaction)

    if action.kind == FREEZE:
        setup = await ensure_setup(grocy)
        freezer = setup["locations"][FREEZER]
        from_location = product.get("location_id") or setup["locations"][FRIDGE]
        if on_hand <= 0 or int(from_location) == freezer:
            return ActionResult(f"ℹ️ No {product['name']} outside the freezer to move.")
        amount = min(action.amount or on_hand, on_hand)
        transaction = await grocy.transfer(product["id"], amount, int(from_location), freezer)
        return ActionResult(f"🧊 Froze {amount:g} {product['name']}", transaction)

    amount = on_hand if action.kind == CONSUME_ALL or (action.kind == SPOIL and not action.amount) else min(action.amount or 1, on_hand)
    transaction = await grocy.consume(product["id"], amount, spoiled=action.kind == SPOIL)
    state.stock[product["id"]] = on_hand - amount
    left = state.amount(product["id"])
    ran_out = product["name"] if left <= 0 else None

    if action.kind == SPOIL:
        line = f"🗑️ Tossed {amount:g} {product['name']}"
    elif action.kind == CONSUME_ALL or left <= 0:
        line = f"✅ Used up {product['name']}"
    else:
        line = f"➖ {amount:g} {product['name']} ({left:g} left)"
    return ActionResult(line, transaction, ran_out)


# --- recipes x pantry ---


def recipe_consumption(ingredients: list[str], state: PantryState) -> list[dict]:
    """For a recipe that was just made: each ingredient that matches an
    in-stock product, with a sensible amount to deduct - the parsed count
    for countable things ("3 eggs" -> 3), otherwise 1 package ("2 lbs
    chicken" -> 1). [{"ingredient", "product", "amount"}]"""
    rows = []
    seen_products: set[int] = set()
    for ingredient in ingredients:
        match = state.match(ingredient)
        if not match or match.score < CONFIDENT_SCORE:
            continue
        product = match.item
        on_hand = state.amount(product["id"])
        if on_hand <= 0 or product["id"] in seen_products:
            continue
        seen_products.add(product["id"])
        quantity, unit = parse_quantity(ingredient)
        amount = quantity if quantity and unit is None and quantity >= 1 else 1
        rows.append({"ingredient": ingredient, "product": product, "amount": min(amount, on_hand)})
    return rows


def in_pantry_ingredients(ingredients: list[str], state: PantryState) -> set[str]:
    """Lowercased ingredient lines already in stock - for /shopping_list to
    start them unchecked."""
    found = set()
    for ingredient in ingredients:
        match = state.match(ingredient)
        if match and match.score >= CONFIDENT_SCORE and state.amount(match.item["id"]) > 0:
            found.add(ingredient.strip().lower())
    return found


def expiring_items(volatile: dict, products_by_id: dict[int, dict] | None = None) -> list[dict]:
    """Flatten Grocy's volatile-stock response into [{"name", "amount",
    "best_before_date", "overdue"}], soonest first. Only products with a
    real shelf life ever show up here (everything else "never expires")."""
    items = []
    for key, overdue in (("overdue_products", True), ("expired_products", True), ("due_products", False)):
        for row in volatile.get(key) or []:
            product = row.get("product") or (products_by_id or {}).get(int(row.get("product_id", 0))) or {}
            name = product.get("name")
            if not name:
                continue
            items.append(
                {
                    "product_id": int(row.get("product_id") or product.get("id") or 0),
                    "name": name,
                    "amount": float(row.get("amount") or 0),
                    "best_before_date": row.get("best_before_date"),
                    "overdue": overdue,
                }
            )
    # One row per product (expired & overdue can overlap), soonest first.
    unique = {}
    for item in sorted(items, key=lambda item: item["best_before_date"] or "9999"):
        unique.setdefault(item["product_id"], item)
    return list(unique.values())
