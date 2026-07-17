from config.recipe_keywords import RECIPE_KEYWORDS


NON_VEGETARIAN_KEYWORDS = [
    "chicken", "beef", "pork", "bacon", "ham", "turkey", "lamb", "veal",
    "sausage", "pepperoni", "prosciutto", "fish", "shrimp", "prawn", "crab",
    "lobster", "tuna", "salmon", "anchovy", "gelatin", "broth", "stock", "bouillon",
]

def matches_keyword(recipe_text, tag):
    rules = RECIPE_KEYWORDS.get(tag)

    if not rules:
        return False

    text_without_exclusions = recipe_text
    for excluded in rules["exclude"]:
        text_without_exclusions = text_without_exclusions.replace(excluded, "")

    for keyword in rules["include"]:
        if keyword in text_without_exclusions:
            return True

    return False

def generate_recipe_tags(recipe):
    tags = []

    tags.append("needs_review")

    title = recipe.title.lower()

    ingredients = [
        ingredient.lower()
        for ingredient in recipe.ingredients
    ]

    recipe_text = (
        title
        + " "
        + " ".join(ingredients)
        + " "
        + (recipe.instructions or "").lower()
    )

    for tag in RECIPE_KEYWORDS:
        if matches_keyword(recipe_text, tag):
            tags.append(tag)

    if not any(keyword in recipe_text for keyword in NON_VEGETARIAN_KEYWORDS):
        tags.append("vegetarian")

    if "soup" in recipe_text:
        tags.append("soup")

    if recipe.total_minutes:
        if recipe.total_minutes <= 30:
            tags.append("quick")

        if recipe.total_minutes >= 90:
            tags.append("long")

    return tags
