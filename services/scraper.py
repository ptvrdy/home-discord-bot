from recipe_scrapers import scrape_me
from models.recipe_card import Recipe
from services.recipe_tags import generate_recipe_tags
from services.time_parser import parse_minutes


def safe_scrape(method):
    try:
        return method()
    except Exception:
        return None
        # TODO adding logger.warning(f"Failed to scrape {method.__name__}(): {e}")


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
        )
    recipe.total_minutes = parse_minutes(recipe.total_time)
    recipe.tags = generate_recipe_tags(recipe)
    
    return recipe