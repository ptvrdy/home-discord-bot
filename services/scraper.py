from urllib.parse import urlparse

import httpx
from recipe_scrapers import scrape_html
from models.recipe_card import Recipe
from services.nyt_fallback import fetch_nyt_times, is_nyt_cooking_url
from services.recipe_tags import generate_recipe_tags
from services.time_parser import parse_minutes

try:
    # The library's own request headers, so sites see the same client they
    # always have. A guard rather than a plain import: a recipe-scrapers
    # version that doesn't export HEADERS would otherwise crash the whole bot
    # at startup, a much bigger failure than anything this protects against.
    from recipe_scrapers import HEADERS as SCRAPER_HEADERS
except ImportError:
    SCRAPER_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; HouseBot/1.0)"}

FETCH_TIMEOUT_SECONDS = 15.0


def safe_scrape(method):
    try:
        return method()
    except Exception:
        return None
        # TODO adding logger.warning(f"Failed to scrape {method.__name__}(): {e}")


# How a recipe's source shows on its card ("From **YouTube**"), by the site the
# link points at. Matched on the host and its subdomains, so m.youtube.com and
# vm.tiktok.com count too.
SOURCE_NAMES_BY_DOMAIN = {
    "cooking.nytimes.com": "New York Times Cooking",
    "allrecipes.com": "AllRecipes",
    "seriouseats.com": "Serious Eats",
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "tiktok.com": "TikTok",
    "broccyourbody.com": "Broc Your Body",
    "damndelicious.net": "Damn Delicious",
    "eatthegains.com": "Eat the Gains",
    "favfamilyrecipes.com": "Fav Family Recipes",
    "feelgoodfoodie.net": "Feel Good Foodie",
    "handletheheat.com": "Handle the Heat",
    "healthyfitnessmeals.com": "Healthy Fitness Meals",
    "houseofyumm.com": "House of Yumm",
    "jasonfarmer.com": "Jason Farmer",
    "lemontreedwelling.com": "Lemon Tree Dwelling",
    "organizeyourselfskinny.com": "Organize Yourself Skinny",
    "sallysbakingaddiction.com": "Sally's Baking Addiction",
    "savoryexperiments.com": "Savory Experiments",
    "sugarspunrun.com": "Sugar Spun Run",
    "thecountrycook.net": "The Country Cook",
    "theforkedspoon.com": "The Forked Spoon",
    "themodernnonna.com": "The Modern Nonna",
    "thetoastykitchen.com": "The Toasty Kitchen",
}


def get_source_name(url):
    host = urlparse(url).netloc.lower().split(":")[0]  # drop any :port

    for domain, name in SOURCE_NAMES_BY_DOMAIN.items():
        if host == domain or host.endswith("." + domain):
            return name

    return None


def fetch_recipe_html(url: str) -> str:
    """Download a recipe page's HTML.

    Used instead of recipe_scrapers.scrape_me(), which fetches with plain
    urllib. urllib never decompresses, and NYT Cooking now answers with
    `Content-Encoding: gzip` even when the request didn't ask for it - so
    scrape_me() died decoding raw gzip bytes as UTF-8 (a UnicodeDecodeError)
    and every NYT import failed before any parsing began. httpx decompresses
    transparently. The library's own request headers are kept so other sites
    see exactly the same client as before, and there's now a timeout, which
    urlopen() never had.
    """
    response = httpx.get(
        url,
        headers=SCRAPER_HEADERS,
        follow_redirects=True,
        timeout=FETCH_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.text


def scrape_recipe(url: str):
    scraper = scrape_html(fetch_recipe_html(url), org_url=url)

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
