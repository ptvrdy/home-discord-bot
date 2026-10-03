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
