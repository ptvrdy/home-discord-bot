from services.time_parser import parse_minutes


def generate_recipe_tags(recipe):
    tags = []

    searchable_text = (
        recipe.title.lower() +
        " " +
        " ".join(recipe.ingredients).lower()
    )
    
    total_minutes = parse_minutes(recipe.total_time)

    if "chicken" in searchable_text:
        tags.append("chicken")

    if "soup" in searchable_text:
        tags.append("soup")

    if recipe.total_minutes is not None:
        if recipe.total_minutes <= 30:
            tags.append("quick")
        if recipe.total_minutes >= 90:
            tags.append("long")

    return tags