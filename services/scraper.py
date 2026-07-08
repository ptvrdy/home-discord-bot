from recipe_scrapers import scrape_me
from models.recipe_card import Recipe


def safe_scrape(method):
    try:
        return method()
    except Exception:
        return None
        # TODO adding logger.warning(f"Failed to scrape {method.__name__}(): {e}")


def scrape_recipe(url: str):
    scraper = scrape_me(url)

    return Recipe(
        title=safe_scrape(scraper.title) or "Untitled Recipe",
        ingredients=safe_scrape(scraper.ingredients) or [],
        instructions=safe_scrape(scraper.instructions),
        total_time=safe_scrape(scraper.total_time),
        yields=safe_scrape(scraper.yields),
        image_url=safe_scrape(scraper.image),
        source_url=url,
        prep_time=safe_scrape(scraper.prep_time),
        cook_time=safe_scrape(scraper.cook_time),
    )