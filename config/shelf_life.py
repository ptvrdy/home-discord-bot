"""Where new pantry products live and how long they last, keyed by Trader
Joe's category. Applied once, when Rosie first creates a product in Grocy -
after that, edit the product in Grocy itself if a default is wrong.

Days are Grocy's "default best before days": -1 means "never expires", so
nothing gets nagged about. Only categories worth an expiry alert get a real
number - meat and seafood now; produce is ready but off until
TRACK_PRODUCE is flipped on.
"""

TRACK_PRODUCE = False

FRIDGE = "Fridge"
FREEZER = "Freezer"
PANTRY = "Pantry"

NEVER_EXPIRES = -1

# (category, subcategory or None for "any") -> rule. First match wins, so
# specific subcategories go before their category's catch-all.
SHELF_LIFE_RULES: list[tuple[str, str | None, dict]] = [
    ("Meat, Seafood & Plant-based", "Chicken & Turkey", {"location": FRIDGE, "days": 2, "freezer_days": 120}),
    ("Meat, Seafood & Plant-based", "Beef, Pork & Lamb", {"location": FRIDGE, "days": 3, "freezer_days": 120}),
    ("Meat, Seafood & Plant-based", "Fish & Seafood", {"location": FRIDGE, "days": 2, "freezer_days": 90}),
    ("Meat, Seafood & Plant-based", None, {"location": FRIDGE, "days": NEVER_EXPIRES, "freezer_days": 90}),
    ("Fresh Fruits & Veggies", None, {"location": FRIDGE, "days": 5, "freezer_days": 180, "produce": True}),
    ("From The Freezer", None, {"location": FREEZER, "days": NEVER_EXPIRES, "freezer_days": NEVER_EXPIRES}),
    ("Dairy & Eggs", None, {"location": FRIDGE, "days": NEVER_EXPIRES, "freezer_days": NEVER_EXPIRES}),
    ("Cheese", None, {"location": FRIDGE, "days": NEVER_EXPIRES, "freezer_days": NEVER_EXPIRES}),
    ("Fresh Prepared Foods", None, {"location": FRIDGE, "days": NEVER_EXPIRES, "freezer_days": NEVER_EXPIRES}),
]

DEFAULT_RULE = {"location": PANTRY, "days": NEVER_EXPIRES, "freezer_days": NEVER_EXPIRES}


# TJ's online catalog skips a lot of basic produce (no plain broccoli,
# limes, cilantro, or celery) and some meat cuts. For anything with no
# believable TJ's match, these keywords still put it in the right aisle -
# and so the right location and shelf life. Matched against the item's
# normalized words; first rule with a hit wins.
KEYWORD_CATEGORIES: list[tuple[set[str], str, str | None]] = [
    ({"chicken", "turkey", "drumstick", "wing"}, "Meat, Seafood & Plant-based", "Chicken & Turkey"),
    ({"beef", "steak", "pork", "chop", "lamb", "sausage", "bacon", "brisket", "ribeye",
      "sirloin", "veal", "ham", "chorizo", "prosciutto"}, "Meat, Seafood & Plant-based", "Beef, Pork & Lamb"),
    ({"salmon", "shrimp", "fish", "cod", "tuna", "tilapia", "scallop", "halibut", "crab",
      "mussel", "clam", "trout"}, "Meat, Seafood & Plant-based", "Fish & Seafood"),
    ({"milk", "egg", "butter", "yogurt", "cream", "kefir"}, "Dairy & Eggs", None),
    ({"cheese", "cheddar", "mozzarella", "parmesan", "feta", "brie", "gouda", "ricotta",
      "provolone", "gruyere", "manchego"}, "Cheese", None),
    ({"broccoli", "lime", "lemon", "cilantro", "parsley", "basil", "mint", "dill", "celery",
      "onion", "garlic", "shallot", "ginger", "lettuce", "kale", "spinach", "arugula",
      "cabbage", "carrot", "potato", "tomato", "pepper", "jalapeno", "zucchini", "squash",
      "cucumber", "mushroom", "asparagus", "cauliflower", "bean", "pea", "corn", "avocado",
      "apple", "banana", "orange", "berry", "strawberry", "blueberry", "raspberry", "grape",
      "pear", "peach", "plum", "mango", "pineapple", "melon", "watermelon", "cherry",
      "eggplant", "leek", "radish", "beet", "scallion", "herb", "thyme", "rosemary",
      "sage", "chive", "fennel", "bok", "choy", "sprout"}, "Fresh Fruits & Veggies", None),
]


# Cut names that take their meat from the word before them ("chicken
# thigh", "salmon fillet") - unlike "chicken broth", which isn't meat.
MEAT_CUTS = {
    "thigh", "breast", "leg", "tender", "tenderloin", "cutlet", "rib", "roast", "loin",
    "fillet", "filet", "patty", "burger", "shank", "shoulder", "belly", "mince", "steak",
}


def guess_category(words: list[str], frozen: bool = False) -> tuple[str | None, str | None]:
    """(category, subcategory) from an item's normalized words, for things
    with no TJ's match. Only the head noun (last word) counts - "garlic
    powder" is a powder, not garlic - except for meat cuts, where the word
    before says which meat."""
    if frozen:
        return "From The Freezer", None
    if not words:
        return None, None
    head = words[-1]
    meat = words[-2] if head in MEAT_CUTS and len(words) >= 2 else None
    for keywords, category, subcategory in KEYWORD_CATEGORIES:
        if head in keywords or (meat and meat in keywords and category.startswith("Meat")):
            return category, subcategory
    return None, None


def rules_for_export() -> list[dict]:
    """The rules above, resolved (produce on/off applied), in the order
    they're checked. Rosie stores these in her database on startup so
    Grocy's Trader Joe's barcode plugin uses exactly the same rules - this
    file is the only place to edit them."""
    exported = []
    for category, subcategory, rule in SHELF_LIFE_RULES:
        days = NEVER_EXPIRES if rule.get("produce") and not TRACK_PRODUCE else rule["days"]
        exported.append(
            {
                "category": category,
                "subcategory": subcategory,
                "location": rule["location"],
                "days": days,
                "freezer_days": rule["freezer_days"],
            }
        )
    return exported


def shelf_life_for(category: str | None, subcategory: str | None) -> dict:
    """{"location", "days", "freezer_days"} for a TJ's category pair."""
    for rule_category, rule_subcategory, rule in SHELF_LIFE_RULES:
        if rule_category != category:
            continue
        if rule_subcategory is not None and rule_subcategory != subcategory:
            continue
        if rule.get("produce") and not TRACK_PRODUCE:
            return {**rule, "days": NEVER_EXPIRES}
        return rule
    return DEFAULT_RULE
