"""Food recall checks against what's actually in the pantry.

Source: the FDA's public openFDA food enforcement API. traderjoes.com's own
recall page refuses automated requests, and many TJ's recalls are filed by
the supplier (e.g. "Ajinomoto Foods") rather than TJ's itself, so this
searches recall *product descriptions* for "Trader Joe's" instead of the
recalling firm. Checked weekly; no key needed at this volume.
"""

import logging
import re
from datetime import date, timedelta

import httpx

from services.ingredient_match import item_words

logger = logging.getLogger(__name__)

OPENFDA_URL = "https://api.fda.gov/food/enforcement.json"
LOOKBACK_DAYS = 60


async def fetch_recent_recalls(today: date, client: httpx.AsyncClient | None = None) -> list[dict]:
    start = (today - timedelta(days=LOOKBACK_DAYS)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")
    params = {
        "search": f'product_description:"Trader Joe\'s" AND report_date:[{start} TO {end}]',
        "sort": "report_date:desc",
        "limit": 100,
    }
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=20.0)
    try:
        response = await client.get(OPENFDA_URL, params=params)
        if response.status_code == 404:  # openFDA's "no matches"
            return []
        response.raise_for_status()
        return response.json().get("results") or []
    finally:
        if owns_client:
            await client.aclose()


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def match_recalls(recalls: list[dict], pantry_items: list[dict]) -> list[dict]:
    """Recalls that look like something in stock.

    pantry_items: [{"name", "tj_name" or None, "tj_sku" or None}] for
    products currently on hand. A recall matches if its description contains
    the item's TJ's SKU (TJ's UPCs embed it) or every meaningful word of its
    TJ's product name - generic names alone ("Egg") are too vague to alert on.

    Returns [{"recall_number", "report_date", "reason", "description",
    "classification", "product"}]."""
    matches = []
    for recall in recalls:
        description = recall.get("product_description") or ""
        description_words = set(item_words(description.replace(",", " ")))
        description_digits = _digits(description)
        for item in pantry_items:
            sku = item.get("tj_sku")
            tj_words = set(item_words(item["tj_name"])) if item.get("tj_name") else set()
            by_sku = bool(sku) and len(sku) >= 5 and sku in description_digits
            by_name = len(tj_words) >= 2 and tj_words <= description_words
            if by_sku or by_name:
                matches.append(
                    {
                        "recall_number": recall.get("recall_number"),
                        "report_date": recall.get("report_date"),
                        "reason": (recall.get("reason_for_recall") or "").strip(),
                        "description": description.strip(),
                        "classification": recall.get("classification"),
                        "product": item["name"],
                    }
                )
                break
    return matches


def format_recall_alert(match: dict) -> str:
    reported = match.get("report_date") or ""
    if len(reported) == 8:
        reported = f"{reported[:4]}-{reported[4:6]}-{reported[6:]}"
    description = match["description"]
    if len(description) > 300:
        description = description[:299] + "…"
    reason = match["reason"]
    if len(reason) > 300:
        reason = reason[:299] + "…"
    return (
        f"⚠️ **Possible recall on something in your pantry: {match['product']}**\n"
        f"{match.get('classification') or 'Recall'} · reported {reported} · #{match.get('recall_number')}\n"
        f"> {description}\n"
        f"**Reason:** {reason}\n"
        "Check the package against the FDA notice before eating it."
    )
