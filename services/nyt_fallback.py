"""Fallback extraction for cooking.nytimes.com recipe timing metadata.

NYT Cooking's public recipe pages have changed their structured data over time.
This module is deliberately narrow: it is used only when recipe-scrapers did
not return one or more timing values.
"""

import json
import logging
import re
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup


LOGGER = logging.getLogger(__name__)

TIME_KEYS = {
    "preptime": "prep_time",
    "cooktime": "cook_time",
    "totaltime": "total_time",
}


def is_nyt_cooking_url(url: str) -> bool:
    """Return whether *url* belongs to NYT Cooking."""
    return urlparse(url).netloc.lower() in {"cooking.nytimes.com", "www.cooking.nytimes.com"}


def _format_duration(value: object) -> str | None:
    """Convert an ISO or numeric duration into an embed-friendly string."""
    if isinstance(value, int):
        return f"{value} minutes"

    if not isinstance(value, str):
        return None

    value = value.strip()
    if not value:
        return None

    iso_match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?", value, flags=re.IGNORECASE)
    if not iso_match:
        return value

    hours, minutes = (int(part or 0) for part in iso_match.groups())
    parts = []
    if hours:
        parts.append(f"{hours} hour" + ("s" if hours != 1 else ""))
    if minutes:
        parts.append(f"{minutes} minute" + ("s" if minutes != 1 else ""))
    return " ".join(parts) or None


def _extract_times_from_data(data: object, times: dict[str, str | None]) -> None:
    if isinstance(data, dict):
        for key, value in data.items():
            normalized_key = re.sub(r"[^a-z]", "", key.lower())
            destination = TIME_KEYS.get(normalized_key)
            formatted_value = _format_duration(value)
            if destination and formatted_value and not times[destination]:
                times[destination] = formatted_value
            _extract_times_from_data(value, times)
    elif isinstance(data, list):
        for item in data:
            _extract_times_from_data(item, times)


def extract_nyt_times(html: str) -> dict[str, str | None]:
    """Extract timing fields from NYT's JSON payloads and rendered labels."""
    times: dict[str, str | None] = {
        "prep_time": None,
        "cook_time": None,
        "total_time": None,
    }
    soup = BeautifulSoup(html, "html.parser")

    for script in soup.find_all("script"):
        content = script.string
        if not content:
            continue
        try:
            _extract_times_from_data(json.loads(content), times)
        except json.JSONDecodeError:
            continue

    page_text = soup.get_text(" ", strip=True)
    label_patterns = {
        "prep_time": r"(?:prep|preparation)\s+time\s*:?\s*",
        "cook_time": r"cook\s+time\s*:?\s*",
        "total_time": r"total\s+time\s*:?\s*",
    }
    duration_pattern = r"(\d+\s*(?:hours?|hrs?|minutes?|mins?)(?:\s+\d+\s*(?:minutes?|mins?))?)"
    for field, label_pattern in label_patterns.items():
        if not times[field]:
            match = re.search(label_pattern + duration_pattern, page_text, flags=re.IGNORECASE)
            if match:
                times[field] = match.group(1)

    return times


def fetch_nyt_times(url: str) -> dict[str, str | None]:
    """Fetch public NYT Cooking metadata, returning empty fields on failure."""
    empty_times: dict[str, str | None] = {
        "prep_time": None,
        "cook_time": None,
        "total_time": None,
    }
    if not is_nyt_cooking_url(url):
        return empty_times

    try:
        response = httpx.get(
            url,
            follow_redirects=True,
            timeout=10.0,
            headers={"User-Agent": "Mozilla/5.0 (compatible; HouseBot/1.0)"},
        )
        response.raise_for_status()
    except httpx.HTTPError as error:
        LOGGER.warning("Could not fetch NYT Cooking timing metadata: %s", error)
        return empty_times

    return extract_nyt_times(response.text)
