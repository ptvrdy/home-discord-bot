def generate_recipe_tags(recipe):
    tags = []

    title = recipe.title.lower()
    ingredients = " ".join(recipe.ingredients).lower()

    if "chicken" in title or "chicken" in ingredients:
        tags.append("🐔 Chicken")

    if "dessert" in title or "cake" in title or "cookie" in title:
        tags.append("🍰 Dessert")

    if "soup" in title or "stew" in title:
        tags.append("🥣 Soup")

    if recipe.total_time:
        if "30" in recipe.total_time:
            tags.append("⏱ Quick")

    return tags