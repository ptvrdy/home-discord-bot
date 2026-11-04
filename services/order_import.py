"""Reading a pasted grocery-delivery order (Shipt / Target so far) into
items for /import_order. Pure text handling - no Grocy, no Discord.

The order page lists each item as its name (often twice: once with HTML
entities like "&#39;", once without), then "$4.99 unit price" and
"Qty 1". A substitution shows up as the item you got (with a price)
followed by the original it replaced (name only, no price).
"""

import html
import re
from dataclasses import dataclass

_PRICE = re.compile(r"^\$\s*(?P<price>\d+(?:\.\d+)?)\s*(?:unit price|each|/\s*ea)?$", re.IGNORECASE)
_QUANTITY = re.compile(r"^(?:qty|quantity)\s*:?\s*(?P<qty>\d+(?:\.\d+)?)$", re.IGNORECASE)

# A size at the very end of a name: "Soy Sauce 10 fl oz", "Pizza 13.8 oz".
# Only at the end, so "OLIPOP 9g Fiber Prebiotic Soda" keeps its words.
_TRAILING_SIZE = re.compile(
    r"\s+\d+(?:\.\d+)?\s*(?:fl\.?\s*oz|oz|lbs?|ct|count|pk|pack|g|kg|ml|l)\.?$", re.IGNORECASE
)

# Store brands that only say where it came from, not what it is.
HOUSE_BRANDS = {
    "good & gather", "good and gather", "market pantry", "favorite day", "archer farms",
    "up & up", "up and up", "kirkland signature", "365 by whole foods market",
    "whole foods market", "great value", "simple truth", "o organics",
}


@dataclass
class OrderItem:
    raw: str                       # the name as the order shows it
    price: float | None = None     # unit price paid
    quantity: float = 1
    replaced: str | None = None    # the item this one was substituted for

    @property
    def title(self) -> str:
        return clean_title(self.raw)

    @property
    def frozen(self) -> bool:
        return bool(re.search(r"\bfrozen\b", self.raw, re.IGNORECASE))

    @property
    def received(self) -> bool:
        """Priced items were picked; a name with no price wasn't."""
        return self.price is not None


def clean_title(raw: str) -> str:
    """"Fleischmann's RapidRise Yeast - 0.25oz/3ct: Gluten-Free, Instant" ->
    "Fleischmann's RapidRise Yeast". Drops marketing after a colon, size and
    count segments, store brands, and ™/® marks."""
    text = html.unescape(raw).replace("™", "").replace("®", "")
    text = re.split(r":\s", text, maxsplit=1)[0]
    segments = [segment.strip() for segment in text.split(" - ")]
    kept = [_TRAILING_SIZE.sub("", segments[0]).strip()]
    for segment in segments[1:]:
        if re.search(r"\d", segment) or segment.lower() in HOUSE_BRANDS:
            continue
        kept.append(segment)
    return re.sub(r"\s+", " ", " ".join(part for part in kept if part)).strip() or html.unescape(raw).strip()


def parse_order_text(text: str) -> list[OrderItem]:
    """Every item in a pasted order, in order. Duplicate name lines collapse
    into one item, and an unpriced name right after a priced item is read
    as the original it was substituted for (recorded on that item, not
    imported)."""
    items: list[OrderItem] = []

    def settle_unpriced_tail():
        # The last item never got a price: it's a substituted-out original
        # if a priced item came right before it; otherwise keep it (unpriced).
        if len(items) >= 2 and items[-1].price is None and items[-2].price is not None and items[-2].replaced is None:
            original = items.pop()  # pop first, then mark the (new) last item
            items[-1].replaced = original.raw

    for line in text.splitlines():
        line = html.unescape(line).strip()
        if not line:
            continue
        price = _PRICE.match(line)
        if price:
            if items:
                items[-1].price = float(price.group("price"))
            continue
        quantity = _QUANTITY.match(line)
        if quantity:
            if items:
                items[-1].quantity = float(quantity.group("qty"))
            continue
        if items and items[-1].raw == line and items[-1].price is None:
            continue  # the same name again (the version without HTML codes)
        settle_unpriced_tail()
        items.append(OrderItem(raw=line))

    settle_unpriced_tail()
    return items
