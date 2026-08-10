from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

from services.database import (
    get_open_wishlist_items,
    get_wishlist_item,
    mark_wishlist_item_bought,
    record_wishlist_item,
)
from services.google_calendar import HOUSEHOLD_TZ
from services.wishlist_embed import build_wishlist_item_embed
from services.wishlist_scraper import scrape_wishlist_link

WISHLIST_LIST_LIMIT = 25


class Wishlist(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """Reacting ✅ on a /want item marks it bought - anyone in the
        household can do this, matching how /task completion works."""
        if self.bot.user and payload.user_id == self.bot.user.id:
            return
        if str(payload.emoji) != "✅":
            return

        item = get_wishlist_item(payload.message_id)
        if item is None:
            return

        channel = self.bot.get_channel(payload.channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            return

        # payload.member is populated directly from the gateway event for
        # guild reactions - no member-cache lookup or Members intent needed.
        bought_by = payload.member.display_name if payload.member else "someone"

        result = mark_wishlist_item_bought(payload.message_id, datetime.now(HOUSEHOLD_TZ), bought_by)
        if result is None:
            return  # already marked bought - don't re-fire on a second reaction

        try:
            message = await channel.fetch_message(payload.message_id)
            embed = build_wishlist_item_embed(
                item["title"],
                item["url"],
                item["image_url"],
                item["price"],
                item["added_by"],
                bought_by=bought_by,
            )
            await message.edit(embed=embed)
        except discord.HTTPException:
            pass

    @app_commands.command(
        name="want",
        description="Add a link to the house wishlist (things to buy)",
    )
    @app_commands.describe(url="Link to the item")
    async def want(self, interaction: discord.Interaction, url: str):
        if not url.startswith(("http://", "https://")):
            await interaction.response.send_message(
                "❌ That doesn't look like a URL — needs to start with http:// or https://",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        try:
            metadata = scrape_wishlist_link(url)

            embed = build_wishlist_item_embed(
                metadata["title"], url, metadata["image_url"], metadata["price"], interaction.user.display_name
            )
            message = await interaction.followup.send(embed=embed, wait=True)

            record_wishlist_item(
                message.id,
                message.channel.id,
                metadata["title"],
                url,
                metadata["image_url"],
                metadata["price"],
                interaction.user.display_name,
                datetime.now(HOUSEHOLD_TZ),
            )
        except Exception as error:
            # Anything unexpected here (a bad scrape, a rejected embed, a DB
            # hiccup) must still resolve this interaction - an unhandled
            # exception after defer() leaves Discord showing "thinking..."
            # forever instead of surfacing an error.
            await interaction.followup.send(
                f"❌ I couldn't add that link: {error}", ephemeral=True
            )
            return

        try:
            await message.add_reaction("✅")
        except discord.HTTPException:
            pass

    @app_commands.command(
        name="wishlist",
        description="See everything still on the house wishlist",
    )
    async def wishlist(self, interaction: discord.Interaction):
        items = get_open_wishlist_items()

        if not items:
            await interaction.response.send_message(
                "🛍️ Nothing on the wishlist right now — add something with /want!"
            )
            return

        lines = [f"🛍️ {len(items)} item(s) on the wishlist:"]
        for item in items[:WISHLIST_LIST_LIMIT]:
            price = f" — {item['price']}" if item["price"] else ""
            lines.append(f"• [{item['title']}]({item['url']}){price} — added by {item['added_by']}")
        if len(items) > WISHLIST_LIST_LIMIT:
            lines.append(f"_(showing the first {WISHLIST_LIST_LIMIT} of {len(items)})_")

        await interaction.response.send_message("\n".join(lines))


async def setup(bot):
    await bot.add_cog(Wishlist(bot))
