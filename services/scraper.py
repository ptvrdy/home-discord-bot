from urllib.parse import urlparse

from recipe_scrapers import scrape_me
from models.recipe_card import Recipe
from services.nyt_fallback import fetch_nyt_times, is_nyt_cooking_url
from services.recipe_tags import generate_recipe_tags
from services.time_parser import parse_minutes


def safe_scrape(method):
    try:
        return method()
    except Exception:
        return None
        # TODO adding logger.warning(f"Failed to scrape {method.__name__}(): {e}")


def get_source_name(url):
    domain = urlparse(url).netloc

    sources = {
        "cooking.nytimes.com": "New York Times Cooking",
        "www.allrecipes.com": "AllRecipes",
        "www.seriouseats.com": "Serious Eats",
    }

    return sources.get(domain)

def scrape_recipe(url: str):
    scraper = scrape_me(url)

    recipe = Recipe(
            title=safe_scrape(scraper.title) or "Untitled Recipe",
            ingredients=safe_scrape(scraper.ingredients) or [],
            instructions=safe_scrape(scraper.instructions),
            prep_time=safe_scrape(scraper.prep_time),
            cook_time=safe_scrape(scraper.cook_time),
            total_time=safe_scrape(scraper.total_time),
            yields=safe_scrape(scraper.yields),
            image_url=safe_scrape(scraper.image),
            source_url=url,
            source_name=get_source_name(url)
        )

    if is_nyt_cooking_url(url) and not all(
        (recipe.prep_time, recipe.cook_time, recipe.total_time)
    ):
        fallback_times = fetch_nyt_times(url)
        recipe.prep_time = recipe.prep_time or fallback_times["prep_time"]
        recipe.cook_time = recipe.cook_time or fallback_times["cook_time"]
        recipe.total_time = recipe.total_time or fallback_times["total_time"]

    recipe.total_minutes = parse_minutes(recipe.total_time)
    recipe.tags = generate_recipe_tags(recipe)

    return recipe
