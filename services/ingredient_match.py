"""Matching free text (recipe ingredient lines, OurGroceries items, "used 4
eggs" messages) to pantry products and Trader Joe's catalog items.

Pure logic - no Grocy, no SQLite, no Discord - so it's all unit-testable.

The core idea: reduce text to a set of meaningful words, then treat the LAST
word as the "head noun" (in English that's almost always what the thing
actually is - "chicken thigh" is a thigh, "garlic powder" is a powder, not
garlic). Two things only match if their head nouns agree, which is what keeps
"garlic powder" from matching a pantry product called "Garlic".
"""

import re
from dataclasses import dataclass

# Units and container words that describe an amount, not the item itself.
UNITS = {
    "cup", "cups", "c", "tablespoon", "tablespoons", "tbsp", "tbs", "tbl", "teaspoon",
    "teaspoons", "tsp", "pound", "pounds", "lb", "lbs", "ounce", "ounces", "oz",
    "gram", "grams", "g", "kg", "kilogram", "kilograms", "ml", "milliliter",
    "milliliters", "l", "liter", "liters", "quart", "quarts", "qt", "pint", "pints",
    "pt", "gallon", "gallons", "pinch", "pinches", "dash", "dashes", "clove", "cloves",
    "can", "cans", "jar", "jars", "package", "packages", "pkg", "bag", "bags", "box",
    "boxes", "bunch", "bunches", "head", "heads", "stick", "sticks", "slice", "slices",
    "piece", "pieces", "sprig", "sprigs", "handful", "handfuls", "container",
    "containers", "bottle", "bottles", "carton", "cartons", "dozen", "inch", "inches",
}

# Descriptive words that don't change which pantry product you'd reach for.
PREP_WORDS = {
    "a", "an", "the", "of", "and", "or", "for", "to", "with", "into", "in", "about",
    "some", "my", "our", "fresh", "freshly", "large", "small", "medium", "extra",
    "chopped", "diced", "minced", "sliced", "thinly", "thickly", "finely", "roughly",
    "coarsely", "grated", "shredded", "crushed", "peeled", "seeded", "cored",
    "trimmed", "halved", "quartered", "cubed", "julienned", "torn", "packed",
    "softened", "melted", "cold", "warm", "hot", "room", "temperature", "divided",
    "optional", "taste", "needed", "plus", "more", "boneless", "skinless", "bone-in",
    "skin-on", "organic", "trader", "joe's", "joes", "tj's", "tjs", "uncooked",
    "cooked", "raw", "frozen", "thawed", "drained", "rinsed", "lightly", "beaten",
    "whole", "ripe", "good", "quality", "best", "favorite", "store-bought",
    "homemade", "prepared", "approximately", "heaping", "level", "generous",
    "few", "several", "each", "per", "serving", "servings", "garnish", "garnishing",
    "last", "rest", "leftover", "leftovers",
}

# Different words for the same pantry product, normalized to one spelling.
# Applied to the whole normalized phrase, so multi-word keys work.
SYNONYMS = {
    "scallion": "green onion",
    "spring onion": "green onion",
    "coriander leaf": "cilantro",
    "garbanzo bean": "chickpea",
    "confectioner sugar": "powdered sugar",
    "icing sugar": "powdered sugar",
    "courgette": "zucchini",
    "aubergine": "eggplant",
    "capsicum": "bell pepper",
    "hamburger": "ground beef",
    "minced beef": "ground beef",
}

_UNICODE_FRACTIONS = {"½": 0.5, "⅓": 1 / 3, "⅔": 2 / 3, "¼": 0.25, "¾": 0.75, "⅛": 0.125}
_NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "dozen": 12, "half": 0.5, "couple": 2,
}
_QUANTITY_PATTERN = re.compile(
    r"^\s*(?P<number>\d+\s+\d+/\d+|\d+/\d+|\d+\s*[½⅓⅔¼¾⅛]|\d+(?:\.\d+)?|[½⅓⅔¼¾⅛])"
    r"(?:\s*[-–]\s*\d+(?:\.\d+)?)?"  # ranges like "2-3" use the low end
    r"\s*(?P<unit>[a-zA-Z.]+)?"
)

# How confident a match has to be before acting on it without asking.
CONFIDENT_SCORE = 0.6


def _singularize(word: str) -> str:
    if len(word) <= 3 or word.endswith(("ss", "us", "is")):
        return word
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith("oes"):
        return word[:-2]
    if word.endswith(("ches", "shes", "xes")):
        return word[:-2]
    if word.endswith("ves") and word not in {"olives", "chives", "cloves"}:
        return word[:-3] + "f"  # loaves -> loaf, halves -> half
    if word.endswith("s"):
        return word[:-1]
    return word


def normalize_item(text: str) -> str:
    """Reduce an ingredient line or item name to its essential words, e.g.
    "2 lbs boneless, skinless chicken thighs (about 6)" -> "chicken thigh"."""
    text = re.sub(r"\([^)]*\)", " ", text.lower())  # parentheticals: "(about 6)"
    # Commas usually start trailing prep ("onion, diced"), but sometimes
    # separate leading adjectives ("boneless, skinless chicken") - so use the
    # first comma-separated piece that still names something.
    for segment in text.split(","):
        normalized = _normalize_segment(segment)
        if normalized:
            return normalized
    return ""


def _normalize_segment(text: str) -> str:
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9'\-\s/½⅓⅔¼¾⅛]", " ", text)

    words = []
    for raw_word in text.split():
        word = raw_word.strip("'-")
        if not word or re.fullmatch(r"[\d/.½⅓⅔¼¾⅛\-]+", word):
            continue
        if word in UNITS or word in PREP_WORDS:
            continue
        words.append(_singularize(word))

    phrase = " ".join(words)
    for original, replacement in SYNONYMS.items():
        phrase = re.sub(rf"\b{re.escape(original)}\b", replacement, phrase)
    return phrase.strip()


def item_words(text: str) -> list[str]:
    return normalize_item(text).split()


def parse_quantity(text: str) -> tuple[float | None, str | None]:
    """Read the leading amount off an ingredient line: "3 large eggs" ->
    (3, None), "2 lbs chicken" -> (2, "lb"), "salt to taste" -> (None, None).
    The unit is only reported if it's a real unit word, so a count of things
    can be told apart from a weight/volume."""
    match = _QUANTITY_PATTERN.match(text.lower())
    if not match:
        first_word = text.lower().split()[0] if text.split() else ""
        if first_word in _NUMBER_WORDS:
            return float(_NUMBER_WORDS[first_word]), None
        return None, None

    number_text = match.group("number")
    if number_text in _UNICODE_FRACTIONS:
        number = _UNICODE_FRACTIONS[number_text]
    elif number_text[-1] in _UNICODE_FRACTIONS:  # "1 ½" / "1½"
        number = int(number_text[:-1].strip()) + _UNICODE_FRACTIONS[number_text[-1]]
    elif " " in number_text:
        whole, fraction = number_text.split()
        numerator, denominator = fraction.split("/")
        number = int(whole) + int(numerator) / int(denominator)
    elif "/" in number_text:
        numerator, denominator = number_text.split("/")
        number = int(numerator) / int(denominator) if int(denominator) else None
    else:
        number = float(number_text)

    unit = (match.group("unit") or "").rstrip(".")
    return number, (_singularize(unit) if unit in UNITS else None)


def match_score(query_text: str, candidate_text: str) -> float:
    """How well a candidate name (a pantry product or TJ's item) fits the
    query text, from 0 (no match) to 1 (exact).

    The head nouns must agree. Beyond that, the score is how much of the
    candidate's description is present in the query, scaled by how much of
    the query the candidate explains - so for "chicken thigh", the product
    "Chicken thighs" scores 1.0, "Thighs" scores lower, and "Chicken breast"
    scores 0."""
    query = item_words(query_text)
    candidate = item_words(candidate_text)
    if not query or not candidate or query[-1] != candidate[-1]:
        return 0.0

    query_set, candidate_set = set(query), set(candidate)
    shared = len(query_set & candidate_set)
    candidate_coverage = shared / len(candidate_set)
    query_coverage = shared / len(query_set)
    return round(candidate_coverage * (0.5 + 0.5 * query_coverage), 4)


@dataclass
class Match:
    item: dict
    score: float


def rank_matches(query_text: str, candidates: list[dict], name_key: str = "name") -> list[Match]:
    """Every candidate with a nonzero score, best first. Ties go to the
    shorter name (the more generic product)."""
    scored = []
    for candidate in candidates:
        score = match_score(query_text, candidate[name_key])
        if score > 0:
            scored.append(Match(candidate, score))
    scored.sort(key=lambda match: (-match.score, len(match.item[name_key])))
    return scored


def best_product_match(
    text: str,
    products: list[dict],
    aliases: dict[str, int] | None = None,
) -> Match | None:
    """Resolve text to a pantry product ({"id", "name", ...}).

    A learned alias (a match a person confirmed before) wins outright;
    otherwise the best-scoring product name, if any."""
    normalized = normalize_item(text)
    if not normalized:
        return None

    if aliases and normalized in aliases:
        product_id = aliases[normalized]
        for product in products:
            if product["id"] == product_id:
                return Match(product, 1.0)

    ranked = rank_matches(text, products)
    return ranked[0] if ranked else None


def best_tj_match(text: str, catalog: list[dict]) -> Match | None:
    """Pick the Trader Joe's item that best fits a generic name, e.g.
    "chicken thighs" -> "Organic Boneless Skinless Chicken Thighs".

    Unlike pantry products, TJ's titles are long and descriptive, so this
    rewards the TJ's item containing all of the query's words, and only
    lightly prefers shorter titles."""
    query = item_words(text)
    if not query:
        return None

    query_set = set(query)
    best: Match | None = None
    for item in catalog:
        title_words = item_words(item["name"])
        if not title_words or title_words[-1] != query[-1]:
            continue
        title_set = set(title_words)
        query_coverage = len(query_set & title_set) / len(query_set)
        if query_coverage < 1:
            continue
        # 1.0 for an exact title; longer, more specific titles fade gently.
        score = round(0.6 + 0.4 * len(query_set) / len(title_set), 4)
        if best is None or score > best.score or (
            score == best.score and len(item["name"]) < len(best.item["name"])
        ):
            best = Match(item, score)
    return best


def display_name(text: str) -> str:
    """A tidy generic product name from free text: "2 lbs boneless chicken
    thighs" -> "Chicken thigh". Used when creating a new pantry product."""
    normalized = normalize_item(text)
    return normalized[:1].upper() + normalized[1:] if normalized else text.strip()
