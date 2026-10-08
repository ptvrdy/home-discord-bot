"""Turns plain-English pantry messages into actions, with no AI involved -
just verb patterns. "finished the milk, used 4 eggs and bought bananas"
becomes three actions.

Pure logic: matching an action's item text to a real pantry product happens
later (services/ingredient_match.py), so this module never needs Grocy.
"""

import re
from dataclasses import dataclass

from config.stores import match_store

# Action kinds, in Grocy terms.
CONSUME = "consume"          # used a specific amount (default 1)
CONSUME_ALL = "consume_all"  # finished it / ran out
SPOIL = "spoil"              # threw it out - consumed, marked spoiled
OPEN = "open"                # used *some* of it - mark a package opened
ADD = "add"                  # bought it
FREEZE = "freeze"            # moved it to the freezer

# Phrases that contain "and" but are one item - never split these.
COMPOUND_ITEMS = (
    "mac and cheese", "macaroni and cheese", "half and half", "salt and pepper",
    "peanut butter and jelly", "sweet and sour", "sweet and spicy",
    "cookies and cream", "chips and salsa", "pb and j",
)

_ARTICLES = r"(?:(?:the|our|my|a|an|some|all|of|last|rest)\s+)*"
_NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "dozen": 12, "half": 0.5, "couple": 2,
}
_AMOUNT = r"(?P<amount>\d+(?:\.\d+)?|" + "|".join(_NUMBER_WORDS) + r")\s+(?:of\s+)?"

# (kind, regex) - checked in order, first match wins. Leading-verb patterns
# capture the item after the verb; trailing patterns ("milk is gone") capture
# it before.
_PATTERNS: list[tuple[str, re.Pattern]] = [
    (SPOIL, re.compile(
        rf"^(?:threw out|throw out|threw away|tossed|toss|trashed|composted)\s+(?:{_AMOUNT})?{_ARTICLES}(?P<item>.+)$")),
    (SPOIL, re.compile(
        r"^(?:the\s+|our\s+|my\s+)?(?P<item>.+?)\s+(?:went bad|has gone bad|spoiled|is moldy|got moldy|expired|is expired)$")),
    (CONSUME_ALL, re.compile(
        rf"^(?:finished|finish|used up|ate the last of|used the last of|drank the last of|"
        rf"(?:we're|we are|we're all|im|i'm)?\s*(?:all\s+)?out of|ran out of|run out of|no more|killed)\s+{_ARTICLES}(?P<item>.+)$")),
    (CONSUME_ALL, re.compile(
        r"^(?:the\s+|our\s+|my\s+)?(?P<item>.+?)\s+(?:is|are)\s+(?:all\s+)?(?:gone|finished|empty|used up)$")),
    (FREEZE, re.compile(
        rf"^(?:froze|freeze|frozen)\s+{_ARTICLES}(?P<item>.+?)(?:\s+in the freezer)?$")),
    (FREEZE, re.compile(rf"^put\s+{_ARTICLES}(?P<item>.+?)\s+in the freezer$")),
    (OPEN, re.compile(
        rf"^(?:used|ate|had|opened|open|cooked with|started)\s+(?:some|part|a bit|a little)(?:\s+of)?\s+{_ARTICLES}(?P<item>.+)$")),
    (OPEN, re.compile(rf"^(?:opened|open|started)\s+{_ARTICLES}(?P<item>.+)$")),
    (ADD, re.compile(
        rf"^(?:bought|buy|got|picked up|grabbed|added|restocked)\s+(?:{_AMOUNT})?{_ARTICLES}(?P<item>.+)$")),
    (CONSUME, re.compile(
        rf"^(?:used|use|ate|eat|drank|drink|cooked|cook|had|made)\s+(?:{_AMOUNT})?{_ARTICLES}(?P<item>.+)$")),
]

# A bare leading verb word, used to decide whether a clause starts a new
# action or continues the previous one's ("bought milk, eggs, bananas").
_VERB_START = re.compile(
    r"^(?:threw|throw|tossed|toss|trashed|composted|finished|finish|used|use|ate|eat|"
    r"drank|drink|cooked|cook|had|made|ran|run|out|no more|killed|froze|freeze|frozen|"
    r"put|opened|open|started|bought|buy|got|picked|grabbed|added|restocked|we're|we|"
    r"i'm|im|all out)\b"
)
_TRAILING_STATE = re.compile(r"\s(?:went bad|spoiled|moldy|expired|gone|finished|empty|used up)$")


@dataclass
class PantryAction:
    kind: str
    item: str
    amount: float | None = None  # None = "the default" (1, or all of it)
    store: str | None = None  # where it was bought ("... at urban market"); None = Trader Joe's


@dataclass
class ParseResult:
    actions: list[PantryAction]
    unparsed: list[str]


def _amount_value(text: str | None) -> float | None:
    if not text:
        return None
    return float(_NUMBER_WORDS[text]) if text in _NUMBER_WORDS else float(text)


def _clean_item(item: str) -> str:
    item = re.sub(r"\b(?:today|tonight|yesterday|this morning|already|too)\b", "", item)
    return re.sub(r"\s+", " ", item).strip(" .!?'\"")


def _make_action(kind: str, item: str, amount: float | None) -> PantryAction:
    # "a dozen eggs" arrives as amount=1, item="dozen eggs".
    if item.startswith("dozen "):
        return PantryAction(kind, item[len("dozen "):], (amount or 1) * 12)
    return PantryAction(kind, item, amount)


def _split_clauses(message: str) -> list[str]:
    text = message.lower().strip()
    text = re.sub(r"^(?:hey\s+)?(?:rosie[,:]?\s+)?", "", text)
    # Protect "mac and cheese"-style items before splitting on "and".
    for index, compound in enumerate(COMPOUND_ITEMS):
        text = text.replace(compound, f"\x00{index}\x00")

    parts = re.split(r"[,;\n]+|\s+(?:and then|then|also|plus|&|and)\s+|\.\s+", text)

    clauses = []
    for part in parts:
        for index, compound in enumerate(COMPOUND_ITEMS):
            part = part.replace(f"\x00{index}\x00", compound)
        part = re.sub(r"^(?:and|also|i|we|just|oh|ok|okay|so)\s+", "", part.strip())
        part = re.sub(r"^(?:i|we|just)\s+", "", part)
        if part:
            clauses.append(part)
    return clauses


_STORE_SUFFIX = re.compile(r"\s+(?:at|from)\s+(?:the\s+)?(?P<store>[a-z'’ ]+?)\s*$")


def _split_store(clause: str) -> tuple[str, str | None]:
    """"milk at urban market" -> ("milk", "Urban Market"). Only known
    grocery stores count, so "pasta from scratch" stays as it is."""
    match = _STORE_SUFFIX.search(clause)
    if match:
        store = match_store(match.group("store"))
        if store:
            return clause[: match.start()], store
    return clause, None


def parse_pantry_message(message: str) -> ParseResult:
    """Parse a whole message into pantry actions.

    A clause with no verb of its own ("eggs" in "bought milk, eggs") reuses
    the previous clause's verb, so lists read naturally. A store named on a
    purchase ("bought milk and eggs at urban market") applies to every
    purchase in the message - one trip, one store."""
    actions: list[PantryAction] = []
    unparsed: list[str] = []
    previous_kind: str | None = None
    trip_store: str | None = None

    for clause in _split_clauses(message):
        clause, store = _split_store(clause)
        trip_store = trip_store or store
        if previous_kind and not _VERB_START.match(clause) and not _TRAILING_STATE.search(clause):
            # Continuation of a list: "bought milk, 2 avocados, eggs".
            amount_match = re.match(rf"^{_AMOUNT}(?P<rest>.+)$", clause)
            amount = _amount_value(amount_match.group("amount")) if amount_match else None
            item = _clean_item(re.sub(rf"^{_ARTICLES}", "", amount_match.group("rest") if amount_match else clause))
            if item:
                actions.append(_make_action(previous_kind, item, amount))
            continue

        for kind, pattern in _PATTERNS:
            match = pattern.match(clause)
            if not match:
                continue
            item = _clean_item(match.group("item"))
            if not item:
                continue
            amount = _amount_value(match.groupdict().get("amount"))
            actions.append(_make_action(kind, item, amount))
            previous_kind = kind
            break
        else:
            unparsed.append(clause)

    if trip_store:
        for action in actions:
            if action.kind == ADD:
                action.store = trip_store
    return ParseResult(actions, unparsed)
