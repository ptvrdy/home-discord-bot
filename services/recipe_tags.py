from services.time_parser import parse_minutes
from config.recipe_keywords import RECIPE_KEYWORDS

def contains_main_ingredient(
    ingredients,
    ingredient_name
):
    exclusions = {
        "chicken": [
            "chicken broth",
            "chicken stock",
            "chicken bouillon",
        ]
    }

    for item in ingredients:

        if ingredient_name in item:

            for excluded in exclusions.get(
                ingredient_name,
                []
            ):
                if excluded in item:
                    return False

            return True

    return False

def matches_keyword(recipe_text, tag):
    rules = RECIPE_KEYWORDS.get(tag)

    if not rules:
        return False

    for excluded in rules["exclude"]:
        if excluded in recipe_text:
            return False

    for keyword in rules["include"]:
        if keyword in recipe_text:
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
    )

    print("TITLE:", title)
    print("INGREDIENTS:", ingredients)
    print("RECIPE TEXT:", recipe_text)

    for tag in RECIPE_KEYWORDS:
        if matches_keyword(recipe_text, tag):
            tags.append(tag)

    for tag in RECIPE_KEYWORDS:
        if matches_keyword(recipe_text, tag):
            tags.append(tag)

    if "soup" in recipe_text:
        tags.append("soup")

    if recipe.total_minutes:
        if recipe.total_minutes <= 30:
            tags.append("quick")

        if recipe.total_minutes >= 90:
            tags.append("long")

    return tags