"""Working out what a recipe's source label should be, from the link it came
from - so a YouTube recipe's card says "From **YouTube**" like an NYT one says
"From **New York Times Cooking**".

Used both when a recipe is added by hand and by /fix_sources, which repairs the
recipes saved before this existed. Pure logic only: no Discord, no database.
"""

from typing import NamedTuple

from services.scraper import get_source_name


class SourceFix(NamedTuple):
    """What a recipe's source name and source link should become."""
    source_name: str | None
    source_url: str


def looks_like_url(text: str | None) -> bool:
    return bool(text) and text.strip().lower().startswith(("http://", "https://"))


def plan_source_fix(source_url: str | None, source_name: str | None) -> SourceFix | None:
    """The change a stored recipe needs, or None if it's already right.

    Two cases, and nothing else - a name someone chose on purpose ("Hand-entered",
    "Handwritten from Sarah", an existing "TikTok") is never overwritten:

    * a link was typed into the NAME slot (the /manual_recipe "Source" box used
      to accept anything), so the card read "From **https://youtu...**": the link
      moves to where it belongs and the name becomes the site's;
    * a link is saved but no name, so the card read "From **the original recipe**".

    A link from a site we don't recognise still gets the link restored, with no
    name, which the card shows as "the original recipe" plus a working link."""
    url = (source_url or "").strip()
    name = (source_name or "").strip()

    if looks_like_url(name):
        link = url or name
        fix = SourceFix(get_source_name(link), link)
    elif url and not name:
        site = get_source_name(url)
        if site is None:
            return None
        fix = SourceFix(site, url)
    else:
        return None

    if fix == SourceFix(source_name, source_url or ""):
        return None
    return fix


def unlabelled_sites(rows: list[dict]) -> dict[str, list[str]]:
    """Recipes that have a source link but no site name, because the site isn't
    in SOURCE_NAMES_BY_DOMAIN: {domain: [recipe titles]}, busiest domain first.
    This is the list to look through when deciding which sites to add."""
    from urllib.parse import urlparse

    by_site: dict[str, list[str]] = {}
    for row in rows:
        url = (row["source_url"] or "").strip()
        if not url or (row["source_name"] or "").strip() or get_source_name(url):
            continue
        site = urlparse(url).netloc.lower().split(":")[0].removeprefix("www.")
        by_site.setdefault(site or "(unreadable link)", []).append(row["title"])
    return dict(sorted(by_site.items(), key=lambda item: (-len(item[1]), item[0])))
