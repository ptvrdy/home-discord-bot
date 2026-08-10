"""Generic Open Graph / <title> metadata scraper for /want links - things to
buy for the house. Unlike recipes, these can point at any retailer, so
there's no site-specific recipe-scrapers library to lean on. Best-effort
only: every field falls back gracefully since not every site sets OG tags,
and some retailers (Amazon included) block automated fetches outright."""

import logging
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

LOGGER = logging.getLogger(__name__)

_PRICE_META_NAMES = ("product:price:amount", "og:price:amount", "twitter:data1")

# Discord embed titles are capped at 256 characters; the raw URL fallback
# (used when a site can't be scraped at all, e.g. Etsy's tracking-parameter
# links) can easily blow past that on its own. Keep the fallback well under
# the limit so build_wishlist_item_embed() never has to silently truncate a
# title into something unreadable.
FALLBACK_TITLE_LIMIT = 100


def _meta_content(soup: BeautifulSoup, *names: str) -> str | None:
    for name in names:
        tag = soup.find("meta", property=name) or soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return tag["content"].strip()
    return None


def _fallback_title_from_url(url: str) -> str:
    """A short, readable stand-in title when a page has no usable <title> or
    og:title - the site plus its last path segment (e.g. "etsy.com —
    modern-perpetual-wall-calendar-1970s"), instead of the full URL with its
    tracking query string attached."""
    parsed = urlparse(url)
    site = parsed.netloc.removeprefix("www.")
    last_segment = parsed.path.rstrip("/").rsplit("/", 1)[-1] or None
    title = f"{site} — {last_segment}" if last_segment else site
    if len(title) > FALLBACK_TITLE_LIMIT:
        title = title[: FALLBACK_TITLE_LIMIT - 1] + "…"
    return title


def parse_wishlist_metadata(html: str, url: str) -> dict:
    """Pull title/image/price metadata out of already-fetched HTML. Split out
    from scrape_wishlist_link() so the parsing logic can be unit tested
    without a real network call."""
    soup = BeautifulSoup(html, "html.parser")

    title = _meta_content(soup, "og:title", "twitter:title")
    if not title and soup.title and soup.title.string:
        title = soup.title.string.strip()

    return {
        "title": title or _fallback_title_from_url(url),
        "image_url": _meta_content(soup, "og:image", "twitter:image"),
        "price": _meta_content(soup, *_PRICE_META_NAMES),
    }


def scrape_wishlist_link(url: str) -> dict:
    """Fetch a product page and pull whatever title/image/price metadata is
    available. Always returns a dict - falls back to a short site-derived
    title if the page can't be fetched or parsed at all, so /want can still
    post something useful."""
    try:
        response = httpx.get(
            url,
            follow_redirects=True,
            timeout=10.0,
            headers={"User-Agent": "Mozilla/5.0 (compatible; HouseBot/1.0)"},
        )
        response.raise_for_status()
    except httpx.HTTPError as error:
        LOGGER.warning("Could not fetch wishlist link metadata for %s: %s", url, error)
        return {"title": _fallback_title_from_url(url), "image_url": None, "price": None}

    return parse_wishlist_metadata(response.text, url)


def get_site_name(url: str) -> str:
    """A short display label for where a wishlist link points, e.g. 'amazon.com'."""
    return urlparse(url).netloc.removeprefix("www.")
