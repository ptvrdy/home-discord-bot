from services.time_parser import parse_minutes

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

def generate_recipe_tags(recipe):
    tags = []

    title = recipe.title.lower()

    ingredients = [
        ingredient.lower()
        for ingredient in recipe.ingredients
    ]
    
    ingredient_text = " ".join(ingredients)
    
    if contains_main_ingredient(
        ingredients,
        "chicken"
    ):
        tags.append("chicken")

    if "soup" in title or "soup" in ingredient_text:
        tags.append("soup")

    if recipe.total_minutes is not None:
        if recipe.total_minutes <= 30:
            tags.append("quick")

        if recipe.total_minutes >= 90:
            tags.append("long")

    
    return tags