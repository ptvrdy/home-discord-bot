"""Builds the embed /want posts for a "buy for the house" link. No Discord
API calls or database access here - just data in, a discord.Embed out."""

import discord

from services.wishlist_scraper import get_site_name

WISHLIST_COLOR = 0x9B59B6
BOUGHT_COLOR = 0x6B6B6B
# Discord rejects embed titles over 256 characters outright; guard here too
# (not just at the scraper) since this is the one place every title source -
# scraped, fallback, future manual entry - ultimately passes through.
TITLE_LIMIT = 256


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def build_wishlist_item_embed(
    title: str,
    url: str,
    image_url: str | None,
    price: str | None,
    added_by: str,
    bought_by: str | None = None,
) -> discord.Embed:
    bought = bought_by is not None
    embed = discord.Embed(
        title=_truncate(f"{'✅' if bought else '🛍️'} {title}", TITLE_LIMIT),
        url=url,
        color=BOUGHT_COLOR if bought else WISHLIST_COLOR,
    )
    if image_url:
        embed.set_thumbnail(url=image_url)
    if price:
        embed.add_field(name="Price", value=price, inline=True)
    embed.add_field(name="Site", value=get_site_name(url), inline=True)
    embed.set_footer(text=f"Bought by {bought_by}" if bought else f"Added by {added_by}")
    return embed
