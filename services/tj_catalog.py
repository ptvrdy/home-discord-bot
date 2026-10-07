"""Trader Joe's product catalog, fetched from the same GraphQL endpoint
traderjoes.com's own product pages use.

There's no official API and no key; this is the public storefront query.
Policy: it's fetched about once a month (plus on demand via
/sync_tj_catalog), one page at a time with a pause between pages - roughly
26 requests per sync for ~2,500 items. Prices and availability are per
store, so TJ_STORE_CODE picks the store (find yours in the URL of your
store's page on traderjoes.com).
"""

import asyncio
import logging
import os

import httpx

logger = logging.getLogger(__name__)

GRAPHQL_URL = "https://www.traderjoes.com/api/graphql"
IMAGE_BASE_URL = "https://www.traderjoes.com"
PAGE_SIZE = 100
PAGE_DELAY_SECONDS = 1.0
MAX_PAGES = 60  # safety stop (~6,000 items) in case total_pages is ever wrong
# Downtown Brooklyn (445 Gold St) - this household's store. Union Square
# (540) has the same catalog and only differs on a few wine prices; TJ's
# prices do vary by region, so set TJ_STORE_CODE if shopping elsewhere.
DEFAULT_STORE_CODE = "547"

# Browser-like headers: the endpoint rejects requests without them (403).
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
    "Origin": "https://www.traderjoes.com",
    "Referer": "https://www.traderjoes.com/home/products/category",
}

SEARCH_PRODUCTS_QUERY = """
query SearchProducts($pageSize: Int, $currentPage: Int, $storeCode: String, $published: String = "1") {
  products(
    filter: {store_code: {eq: $storeCode}, published: {eq: $published}}
    pageSize: $pageSize
    currentPage: $currentPage
  ) {
    items {
      sku
      item_title
      retail_price
      sales_size
      sales_uom_description
      primary_image
      new_product
      availability
      category_hierarchy { id name level }
    }
    total_count
    page_info { current_page page_size total_pages }
  }
}
"""

# Buckets that aren't groceries (shampoo, dog treats, bouquets) - skipped so
# the catalog, and fuzzy matching against it, stays about food and drink.
NON_GROCERY_CATEGORIES = {"Flowers & Plants", "Everything Else", "Bouquets", "Plants"}


def store_code() -> str:
    return os.getenv("TJ_STORE_CODE") or DEFAULT_STORE_CODE


def _category_names(item: dict) -> tuple[str | None, str | None]:
    """(broad, specific) category - e.g. ("Meat, Seafood & Plant-based",
    "Beef, Pork & Lamb"). Level 1 is always "Products" and level 2 is
    "Food"/"Beverages"/etc., so the useful ones are 3 and 4 (falling back to
    2 for shallow trees like "Flowers & Plants")."""
    by_level = {entry.get("level"): entry.get("name") for entry in item.get("category_hierarchy") or []}
    broad = by_level.get(3) or by_level.get(2)
    specific = by_level.get(4)
    return broad, specific


def _price(value) -> float | None:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _check_digit(digits: str) -> str:
    """GS1 check digit (EAN-8 / UPC-A / EAN-13 all agree for zero-padded codes)."""
    total = sum(int(digit) * (3 if index % 2 == 0 else 1) for index, digit in enumerate(reversed(digits)))
    return str((10 - total % 10) % 10)


def barcodes_for_sku(sku: str) -> list[str]:
    """The barcodes printed on a Trader Joe's-brand package for this SKU.

    TJ's house-brand barcodes are "00" + the SKU's last 5 digits + a check
    digit - verified against every FDA recall notice listing both a TJ's UPC
    and a product still in the catalog (13 of 13 matched; e.g. Vegetable
    Fried Rice is SKU 052148, UPC 00521482). Scanners report that as 8, 12,
    or 13 digits depending on the app, so all three forms are returned.
    Name-brand items sold at TJ's carry their own UPCs and won't match."""
    digits = "".join(character for character in sku if character.isdigit())
    if len(digits) < 5:
        return []
    body = "00" + digits[-5:]
    ean8 = body + _check_digit(body)
    return [ean8, "0000" + ean8, "00000" + ean8]


def sku_from_barcode(barcode: str) -> str | None:
    """The TJ's SKU behind a scanned Trader Joe's-brand barcode (8, 12, or
    13 digits), or None for anything else - name-brand UPCs, typos, or a bad
    check digit. The inverse of barcodes_for_sku."""
    digits = "".join(character for character in barcode if character.isdigit())
    if len(digits) > 8:
        if digits[:-8].strip("0"):
            return None
        digits = digits[-8:]
    if len(digits) != 8 or not digits.startswith("00"):
        return None
    if _check_digit(digits[:7]) != digits[7]:
        return None
    return "0" + digits[2:7]


def parse_products(response_json: dict) -> tuple[list[dict], int]:
    """Turn one GraphQL page into catalog rows. Returns (rows, total_pages).

    Kept separate from the HTTP call so tests can feed it a saved response."""
    products = (response_json.get("data") or {}).get("products") or {}
    total_pages = (products.get("page_info") or {}).get("total_pages") or 0

    rows = []
    for item in products.get("items") or []:
        sku = item.get("sku")
        title = (item.get("item_title") or "").strip()
        if not sku or not title:
            continue

        category_names = {entry.get("name") for entry in item.get("category_hierarchy") or []}
        if category_names & NON_GROCERY_CATEGORIES:
            continue

        broad, specific = _category_names(item)
        size = item.get("sales_size")
        unit = item.get("sales_uom_description")
        image = item.get("primary_image")
        rows.append(
            {
                "sku": sku,
                "name": title,
                "category": broad,
                "subcategory": specific,
                "price": _price(item.get("retail_price")),
                "size": f"{size:g} {unit}" if isinstance(size, (int, float)) and unit else None,
                "image_url": f"{IMAGE_BASE_URL}{image}" if image else None,
                "is_new": str(item.get("new_product")) == "1",
            }
        )
    return rows, total_pages


async def fetch_catalog(client: httpx.AsyncClient | None = None) -> list[dict]:
    """Fetch every page of the catalog for TJ_STORE_CODE, sequentially."""
    owns_client = client is None
    client = client or httpx.AsyncClient(headers=REQUEST_HEADERS, timeout=20.0)
    try:
        rows: list[dict] = []
        page = 1
        total_pages = 1
        while page <= min(total_pages, MAX_PAGES):
            response = await client.post(
                GRAPHQL_URL,
                json={
                    "operationName": "SearchProducts",
                    "query": SEARCH_PRODUCTS_QUERY,
                    "variables": {
                        "storeCode": store_code(),
                        "published": "1",
                        "currentPage": page,
                        "pageSize": PAGE_SIZE,
                    },
                },
            )
            response.raise_for_status()
            page_rows, total_pages = parse_products(response.json())
            rows.extend(page_rows)
            page += 1
            if page <= total_pages:
                await asyncio.sleep(PAGE_DELAY_SECONDS)
        return rows
    finally:
        if owns_client:
            await client.aclose()


def thumbnail_url(url: str) -> str:
    """TJ's image server (Adobe AEM) keeps a 319x319 rendition of every
    product photo - ~175 KB instead of a ~4.5 MB original, and about the
    size Grocy shows them at anyway."""
    return f"{url}/jcr:content/renditions/cq5dam.thumbnail.319.319.png"


async def download_product_photo(url: str) -> bytes | None:
    """The small rendition of a TJ's product photo, or the original if the
    small one doesn't exist. None if neither downloads."""
    return await download_image(thumbnail_url(url)) or await download_image(url)


async def download_image(url: str, client: httpx.AsyncClient | None = None) -> bytes | None:
    """Best-effort product photo download; None on any failure (a missing
    photo should never block creating a pantry product)."""
    owns_client = client is None
    client = client or httpx.AsyncClient(headers=REQUEST_HEADERS, timeout=15.0, follow_redirects=True)
    try:
        response = await client.get(url)
        response.raise_for_status()
        return response.content
    except httpx.HTTPError as error:
        logger.warning("Couldn't download TJ's image %s: %s", url, error)
        return None
    finally:
        if owns_client:
            await client.aclose()
