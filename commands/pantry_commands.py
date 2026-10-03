"""Pantry commands: Grocy inventory driven entirely from Discord.

- /put_away - turn items crossed off in OurGroceries into pantry stock
- #pantry channel (or /pantry) - plain-English updates: "used 4 eggs"
- /what_can_i_make - recipes ranked by what's in stock
- /in_stock, /pantry_fix, /sync_tj_catalog
- Background: monthly TJ's catalog sync (1st, 4am), evening "looks like you
  shopped" check (7pm), morning use-soon nudges (9am), weekly recall check.

Grocy is optional - without GROCY_URL/GROCY_API_KEY every command explains
what's missing and every background task quietly does nothing.
"""

import logging
import os
from datetime import datetime, time

import discord
from discord import app_commands
from discord.ext import commands, tasks

from config.discord_tags import DISCORD_TAGS
from services.database import (
    forget_og_imported,
    get_all_recipes,
    get_imported_og_keys,
    get_new_tj_products,
    get_pantry_products,
    get_state,
    get_tj_catalog,
    record_og_imported,
    search_tj_products,
    set_state,
    upsert_tj_products,
)
from services.forum import HUMAN_TAGS
from services.google_calendar import HOUSEHOLD_TZ
from services.grocery_list import _staple_rank, add_items, get_grocery_lists, get_list_items_with_status
from services.grocy import Grocy, GrocyError, GrocyNotConfigured, grocy_configured
from services.ingredient_match import CONFIDENT_SCORE
from services.pantry import (
    PantryState,
    apply_action,
    ensure_setup,
    expiring_items,
    in_pantry_ingredients,
    learn,
    load_state,
    plan_put_away,
    put_away,
    recipe_consumption,
    relink_tj_item,
)
from services.pantry_embed import build_sync_summary, build_what_can_i_make_embed, format_expiring_lines, score_recipes
from services.pantry_parser import ADD, CONSUME, CONSUME_ALL, FREEZE, PantryAction, parse_pantry_message
from services.recalls import fetch_recent_recalls, format_recall_alert, match_recalls
from services.tj_catalog import fetch_catalog

logger = logging.getLogger(__name__)

CATALOG_SYNC_TIME = time(4, 0, tzinfo=HOUSEHOLD_TZ)  # checked daily, runs on the 1st
SHOPPING_CHECK_TIME = time(19, 0, tzinfo=HOUSEHOLD_TZ)
EXPIRY_CHECK_TIME = time(9, 0, tzinfo=HOUSEHOLD_TZ)
RECALL_CHECK_TIME = time(10, 0, tzinfo=HOUSEHOLD_TZ)  # checked daily, runs Mondays
RECALL_CHECK_WEEKDAY = 0

CATALOG_SYNCED_STATE_KEY = "tj_catalog_synced_at"
SHOPPING_NUDGE_STATE_KEY = "pantry_shopping_nudge_keys"
EXPIRY_NUDGED_STATE_KEY = "pantry_expiry_nudged"
RECALLS_SEEN_STATE_KEY = "pantry_recalls_seen"

PUT_AWAY_BUTTON_LIMIT = 23  # 25 components, minus Confirm and Cancel
EXPIRY_NUDGE_LIMIT = 5      # two buttons each, 5 rows max

NOT_CONFIGURED_MESSAGE = (
    "🥫 The pantry isn't set up yet — add `GROCY_URL` and `GROCY_API_KEY` to `.env` "
    "(see docs/grocy-setup.md)."
)

PANTRY_TAG_CHOICES = [
    app_commands.Choice(name=tag_info["discord_name"], value=tag_key)
    for tag_key, tag_info in DISCORD_TAGS.items()
    if tag_key not in HUMAN_TAGS
]


def _channel_id(name: str) -> int | None:
    value = os.getenv(name)
    return int(value) if value else None


def _pantry_list_name() -> str | None:
    """The OurGroceries list "add to shopping list" buttons default to,
    e.g. "Trader Joe's". Unset = ask which list."""
    return os.getenv("PANTRY_LIST_NAME")


async def _undo_all(transaction_ids: list[str]) -> None:
    async with Grocy() as grocy:
        for transaction_id in reversed(transaction_ids):
            await grocy.undo_transaction(transaction_id)


# --- shared buttons ---


class UndoPantryButton(discord.ui.Button):
    def __init__(self, transaction_ids: list[str], og_item_ids: list[str] | None = None):
        super().__init__(label="Undo", style=discord.ButtonStyle.danger)
        self.transaction_ids = transaction_ids
        self.og_item_ids = og_item_ids or []

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            await _undo_all(self.transaction_ids)
        except (GrocyError, GrocyNotConfigured) as error:
            await interaction.followup.send(f"❌ I couldn't undo that: {error}", ephemeral=True)
            return
        # Put-away undo: offer these list items again next time.
        forget_og_imported(self.og_item_ids)
        await interaction.edit_original_response(content="↩️ Undone — the pantry is back the way it was.", view=None)


class AddToListButton(discord.ui.Button):
    """After something runs out: one tap to put it back on the shopping list."""

    def __init__(self, items: list[str]):
        label = f"🛒 Add {', '.join(items)} to the list"
        super().__init__(label=label[:80], style=discord.ButtonStyle.secondary)
        self.items = items

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            lists = await get_grocery_lists()
        except Exception as error:
            await interaction.followup.send(f"❌ I couldn't connect to OurGroceries: {error}", ephemeral=True)
            return

        preferred = _pantry_list_name()
        target = next((entry for entry in lists if preferred and entry["name"].lower() == preferred.lower()), None)
        if target is None and len(lists) == 1:
            target = lists[0]
        if target is None:
            await interaction.followup.send(
                "Which list?", view=ChooseListView(self.items, lists), ephemeral=True
            )
            return

        try:
            await add_items(target["id"], self.items)
        except Exception as error:
            await interaction.followup.send(f"❌ I couldn't update OurGroceries: {error}", ephemeral=True)
            return
        self.disabled = True
        self.label = f"✅ Added to {target['name']}"[:80]
        await interaction.message.edit(view=self.view)
        await interaction.followup.send(f"🛒 Added {', '.join(self.items)} to **{target['name']}**.", ephemeral=True)


class ChooseListSelect(discord.ui.Select):
    def __init__(self, items: list[str], lists: list[dict]):
        super().__init__(
            placeholder="Which list?",
            options=[discord.SelectOption(label=entry["name"][:100], value=entry["id"]) for entry in lists[:25]],
        )
        self.items = items

    async def callback(self, interaction: discord.Interaction):
        list_id = self.values[0]
        list_name = next(option.label for option in self.options if option.value == list_id)
        await interaction.response.defer()
        try:
            await add_items(list_id, self.items)
        except Exception as error:
            await interaction.edit_original_response(content=f"❌ I couldn't update OurGroceries: {error}", view=None)
            return
        await interaction.edit_original_response(
            content=f"🛒 Added {', '.join(self.items)} to **{list_name}**.", view=None
        )


class ChooseListView(discord.ui.View):
    def __init__(self, items: list[str], lists: list[dict]):
        super().__init__(timeout=300)
        self.add_item(ChooseListSelect(items, lists))


class ResultView(discord.ui.View):
    def __init__(self, transaction_ids: list[str], ran_out: list[str] | None = None, og_item_ids: list[str] | None = None):
        super().__init__(timeout=900)
        if transaction_ids:
            self.add_item(UndoPantryButton(transaction_ids, og_item_ids))
        if ran_out:
            self.add_item(AddToListButton(ran_out))


# --- toggle lists (put-away, recipe consumption) ---


class ToggleButton(discord.ui.Button):
    """Same look and feel as the /shopping_list ingredient toggles."""

    def __init__(self, label_text: str, payload, checked: bool = True):
        self.label_text = label_text
        self.payload = payload
        self.checked = checked
        super().__init__(label=self._label(), style=self._style())

    def _label(self) -> str:
        return f"{'✅' if self.checked else '⬜'} {self.label_text}"[:80]

    def _style(self) -> discord.ButtonStyle:
        return discord.ButtonStyle.success if self.checked else discord.ButtonStyle.secondary

    async def callback(self, interaction: discord.Interaction):
        self.checked = not self.checked
        self.style = self._style()
        self.label = self._label()
        await interaction.response.edit_message(view=self.view)


class CancelButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Cancel", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(content="Cancelled — nothing changed.", view=None)


def _checked_payloads(view: discord.ui.View) -> list:
    return [child.payload for child in view.children if isinstance(child, ToggleButton) and child.checked]


class ConfirmPutAwayButton(discord.ui.Button):
    def __init__(self, list_id: str):
        super().__init__(label="Put Away", style=discord.ButtonStyle.primary)
        self.list_id = list_id

    async def callback(self, interaction: discord.Interaction):
        chosen = _checked_payloads(self.view)
        unchosen = [
            child.payload for child in self.view.children if isinstance(child, ToggleButton) and not child.checked
        ]
        await interaction.response.defer()

        now = datetime.now(HOUSEHOLD_TZ)
        # Unchecked = "didn't actually buy it" - remember those too, so they
        # aren't offered again for this same cross-off.
        record_og_imported([(item.og_item_id, item.crossed_off_at) for item in unchosen], self.list_id, now)
        if not chosen:
            await interaction.edit_original_response(content="Nothing selected — nothing put away.", view=None)
            return

        try:
            async with Grocy() as grocy:
                state = await load_state(grocy)
                lines, transactions = await put_away(grocy, state, chosen, interaction.user.display_name)
        except (GrocyError, GrocyNotConfigured) as error:
            await interaction.edit_original_response(content=f"❌ I couldn't update the pantry: {error}", view=None)
            return

        record_og_imported([(item.og_item_id, item.crossed_off_at) for item in chosen], self.list_id, now)
        await interaction.edit_original_response(
            content="🧺 Put away:\n" + "\n".join(lines),
            view=ResultView(transactions, og_item_ids=[item.og_item_id for item in chosen]),
        )


class PutAwayView(discord.ui.View):
    def __init__(self, items: list, list_id: str):
        super().__init__(timeout=900)
        for item in items[:PUT_AWAY_BUTTON_LIMIT]:
            self.add_item(ToggleButton(item.label(), item))
        self.add_item(ConfirmPutAwayButton(list_id))
        self.add_item(CancelButton())


class ConfirmConsumeButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Use Up Selected", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        chosen = _checked_payloads(self.view)
        if not chosen:
            await interaction.response.edit_message(content="Nothing selected — pantry unchanged.", view=None)
            return
        await interaction.response.defer()

        lines, transactions, ran_out = [], [], []
        try:
            async with Grocy() as grocy:
                state = await load_state(grocy)
                for row in chosen:
                    result = await apply_action(
                        grocy, state, PantryAction(CONSUME, row["ingredient"], row["amount"]), row["product"]
                    )
                    lines.append(result.line)
                    if result.transaction_id:
                        transactions.append(result.transaction_id)
                    if result.ran_out:
                        ran_out.append(result.ran_out)
        except (GrocyError, GrocyNotConfigured) as error:
            await interaction.edit_original_response(content=f"❌ I couldn't update the pantry: {error}", view=None)
            return

        await interaction.edit_original_response(
            content="\n".join(lines), view=ResultView(transactions, ran_out)
        )


class RecipeConsumeView(discord.ui.View):
    def __init__(self, rows: list[dict]):
        super().__init__(timeout=900)
        for row in rows[:PUT_AWAY_BUTTON_LIMIT]:
            # Staples start unchecked: a pinch of salt isn't worth a package.
            checked = _staple_rank(row["ingredient"]) is None
            amount = f"{row['amount']:g}× " if row["amount"] != 1 else ""
            self.add_item(ToggleButton(f"{amount}{row['product']['name']}", row, checked))
        self.add_item(ConfirmConsumeButton())
        self.add_item(CancelButton())


async def offer_recipe_consumption(interaction: discord.Interaction, ingredients: list[str]) -> None:
    """Called after /review logs a "Made" entry: offer to deduct the
    recipe's in-stock ingredients. Silent if the pantry isn't set up or
    nothing matches - this is a bonus, never an error."""
    if not grocy_configured():
        return
    try:
        async with Grocy() as grocy:
            state = await load_state(grocy)
    except GrocyError as error:
        logger.warning("Skipping recipe consumption offer: %s", error)
        return

    rows = recipe_consumption(ingredients, state)
    if not rows:
        return
    await interaction.followup.send(
        "🥫 Use up what went into it? Uncheck anything you didn't use:",
        view=RecipeConsumeView(rows),
        ephemeral=True,
    )


async def in_pantry_locations(ingredients: list[str]) -> dict[str, str]:
    """For /shopping_list: {ingredient_lower: "in pantry"} for ingredients
    already in stock, merged into the existing "already on a list" check so
    those start unchecked. Empty (never an error) if Grocy isn't reachable."""
    if not grocy_configured():
        return {}
    try:
        async with Grocy() as grocy:
            state = await load_state(grocy)
    except GrocyError as error:
        logger.warning("Skipping pantry check for shopping list: %s", error)
        return {}
    return {ingredient: "in pantry" for ingredient in in_pantry_ingredients(ingredients, state)}


# --- plain-English: ambiguous matches ---


class ChooseProductButton(discord.ui.Button):
    def __init__(self, action: PantryAction, product: dict | None, label: str):
        super().__init__(label=label[:80], style=discord.ButtonStyle.secondary if product else discord.ButtonStyle.primary)
        self.action = action
        self.product = product

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            async with Grocy() as grocy:
                state = await load_state(grocy)
                if self.product:
                    learn(self.action.item, self.product["id"], interaction.user.display_name)
                result = await apply_action(grocy, state, self.action, self.product, interaction.user.display_name)
        except (GrocyError, GrocyNotConfigured) as error:
            await interaction.edit_original_response(content=f"❌ I couldn't update the pantry: {error}", view=None)
            return
        await interaction.edit_original_response(
            content=result.line,
            view=ResultView([result.transaction_id] if result.transaction_id else [], [result.ran_out] if result.ran_out else None),
        )


class ChooseProductView(discord.ui.View):
    def __init__(self, action: PantryAction, candidates: list[dict]):
        super().__init__(timeout=900)
        for product in candidates[:3]:
            self.add_item(ChooseProductButton(action, product, product["name"]))
        if action.kind == ADD:
            self.add_item(ChooseProductButton(action, None, f"➕ New: {action.item}"))
        self.add_item(CancelButton())


async def handle_pantry_text(text: str, user_name: str) -> list[tuple[str, discord.ui.View | None]]:
    """Run a plain-English pantry message. Returns the replies to send:
    one combined summary (with Undo / add-to-list), plus one "did you
    mean?" prompt per ambiguous item."""
    parsed = parse_pantry_message(text)
    if not parsed.actions:
        return [(
            "🤔 I didn't catch that. Try things like *used 4 eggs*, *finished the milk*, "
            "*bought bananas*, *the spinach went bad*, or *froze the chicken*.",
            None,
        )]

    replies: list[tuple[str, discord.ui.View | None]] = []
    lines, transactions, ran_out = [], [], []
    async with Grocy() as grocy:
        await ensure_setup(grocy)
        state: PantryState = await load_state(grocy)
        for action in parsed.actions:
            match = state.match(action.item)
            confident = match is not None and match.score >= CONFIDENT_SCORE
            if not confident and action.kind != ADD and not state.candidates(action.item):
                lines.append(f"❓ I don't have **{action.item}** in the pantry.")
                continue
            if not confident and (action.kind != ADD or state.candidates(action.item)):
                candidates = [candidate.item for candidate in state.candidates(action.item)]
                replies.append((f"Which one did you mean by **{action.item}**?", ChooseProductView(action, candidates)))
                continue

            product = match.item if confident else None
            if product is not None:
                learn(action.item, product["id"], user_name)
            result = await apply_action(grocy, state, action, product, user_name)
            lines.append(result.line)
            if result.transaction_id:
                transactions.append(result.transaction_id)
            if result.ran_out:
                ran_out.append(result.ran_out)

    if parsed.unparsed:
        lines.append(f"_(skipped: {'; '.join(parsed.unparsed)})_")
    if lines:
        replies.insert(0, ("\n".join(lines), ResultView(transactions, ran_out) if transactions or ran_out else None))
    return replies


# --- expiry nudges ---


class ExpiryActionButton(discord.ui.Button):
    def __init__(self, item: dict, kind: str):
        label = f"🧊 Froze {item['name']}" if kind == FREEZE else f"✅ Used {item['name']}"
        super().__init__(label=label[:80], style=discord.ButtonStyle.primary if kind == FREEZE else discord.ButtonStyle.success)
        self.item = item
        self.kind = kind

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        action = PantryAction(self.kind, self.item["name"])
        try:
            async with Grocy() as grocy:
                state = await load_state(grocy)
                result = await apply_action(grocy, state, action, state.product(self.item["product_id"]))
        except (GrocyError, GrocyNotConfigured) as error:
            await interaction.followup.send(f"❌ I couldn't update the pantry: {error}", ephemeral=True)
            return
        for child in self.view.children:
            if isinstance(child, ExpiryActionButton) and child.item["product_id"] == self.item["product_id"]:
                child.disabled = True
        await interaction.message.edit(view=self.view)
        await interaction.followup.send(f"{result.line} (by {interaction.user.display_name})")


class ExpiryNudgeView(discord.ui.View):
    def __init__(self, items: list[dict]):
        super().__init__(timeout=None)
        for row, item in enumerate(items[:EXPIRY_NUDGE_LIMIT]):
            freeze = ExpiryActionButton(item, FREEZE)
            used = ExpiryActionButton(item, CONSUME_ALL)
            freeze.row = used.row = row
            self.add_item(freeze)
            self.add_item(used)


# --- the cog ---


class Pantry(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.pantry_channel_id = _channel_id("PANTRY_CHANNEL_ID")
        self.nudges_channel_id = _channel_id("NUDGES_CHANNEL_ID")
        self.catalog_sync_task.start()
        self.shopping_check_task.start()
        self.expiry_check_task.start()
        self.recall_check_task.start()

    def cog_unload(self):
        self.catalog_sync_task.cancel()
        self.shopping_check_task.cancel()
        self.expiry_check_task.cancel()
        self.recall_check_task.cancel()

    def _nudges_channel(self) -> discord.abc.Messageable | None:
        if self.nudges_channel_id is None:
            return None
        channel = self.bot.get_channel(self.nudges_channel_id)
        return channel if isinstance(channel, discord.abc.Messageable) else None

    # --- catalog sync ---

    async def run_catalog_sync(self) -> str:
        rows = await fetch_catalog()
        if not rows:
            raise RuntimeError("Trader Joe's returned an empty catalog - leaving the old one in place")
        now = datetime.now(HOUSEHOLD_TZ)
        stats = upsert_tj_products(rows, now)
        set_state(CATALOG_SYNCED_STATE_KEY, now.isoformat())

        pantry = get_pantry_products()
        bought_skus = {row["tj_sku"]: row["name"] for row in pantry if row["tj_sku"]}
        returned = [bought_skus[sku] for sku in stats["returned_skus"] if sku in bought_skus]
        return build_sync_summary(stats, len(rows), returned, get_new_tj_products(limit=8))

    @tasks.loop(time=CATALOG_SYNC_TIME)
    async def catalog_sync_task(self):
        # Monthly (the catalog churns), or the first 4am after a fresh install.
        if datetime.now(HOUSEHOLD_TZ).day != 1 and get_state(CATALOG_SYNCED_STATE_KEY):
            return
        try:
            summary = await self.run_catalog_sync()
        except Exception as error:
            logger.warning("Monthly TJ's catalog sync failed: %s", error)
            return
        channel = self._nudges_channel()
        if channel:
            await channel.send(summary)

    @catalog_sync_task.before_loop
    async def before_catalog_sync(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="sync_tj_catalog", description="Refresh Rosie's copy of the Trader Joe's product catalog now")
    async def sync_tj_catalog(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        try:
            summary = await self.run_catalog_sync()
        except Exception as error:
            await interaction.followup.send(f"❌ Catalog sync failed: {error}")
            return
        await interaction.followup.send(summary)

    # --- put-away ---

    async def _pending_put_away(self) -> tuple[list[dict], dict[str, str]]:
        """Crossed-off items not yet put away, grouped by list. Also forgets
        put-away records for items that are active again."""
        items = await get_list_items_with_status()
        forget_og_imported([item["item_id"] for item in items if not item["crossed_off"]])
        imported = get_imported_og_keys()
        pending = [
            item for item in items
            if item["crossed_off"] and (item["item_id"], item["crossed_off_at"]) not in imported
        ]
        list_names = {item["list_id"]: item["list_name"] for item in items}
        return pending, list_names

    async def send_put_away(self, interaction: discord.Interaction, list_name: str | None = None) -> None:
        """Shared by /put_away and the evening nudge's button. Expects the
        interaction to already be deferred."""
        if not grocy_configured():
            await interaction.followup.send(NOT_CONFIGURED_MESSAGE, ephemeral=True)
            return
        try:
            pending, list_names = await self._pending_put_away()
        except Exception as error:
            await interaction.followup.send(f"❌ I couldn't read OurGroceries: {error}", ephemeral=True)
            return

        if list_name:
            pending = [item for item in pending if item["list_name"].lower() == list_name.lower()]
        if not pending:
            await interaction.followup.send(
                "🧺 Nothing new to put away — cross things off in OurGroceries while you shop, then run this.",
                ephemeral=True,
            )
            return

        try:
            async with Grocy() as grocy:
                state = await load_state(grocy)
        except GrocyError as error:
            await interaction.followup.send(f"❌ I couldn't reach the pantry: {error}", ephemeral=True)
            return

        catalog = get_tj_catalog()
        by_list: dict[str, list[dict]] = {}
        for item in pending:
            by_list.setdefault(item["list_id"], []).append(item)

        for list_id, list_items in by_list.items():
            plan = plan_put_away(list_items, state, catalog)
            content = (
                f"🧺 Crossed off on **{list_names[list_id]}** — uncheck anything you didn't actually buy, "
                "then **Put Away**:"
            )
            if len(plan) > PUT_AWAY_BUTTON_LIMIT:
                content += f"\n_(first {PUT_AWAY_BUTTON_LIMIT} of {len(plan)} — run /put_away again for the rest)_"
            if not catalog:
                content += "\n_(TJ's catalog isn't loaded yet — run /sync_tj_catalog for photos and prices.)_"
            await interaction.followup.send(content, view=PutAwayView(plan, list_id), ephemeral=True)

    @app_commands.command(name="put_away", description="Add what you crossed off in OurGroceries to the pantry")
    @app_commands.describe(list_name="Optional: only this OurGroceries list (default: all lists)")
    async def put_away_command(self, interaction: discord.Interaction, list_name: str | None = None):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.send_put_away(interaction, list_name)

    @tasks.loop(time=SHOPPING_CHECK_TIME)
    async def shopping_check_task(self):
        """Once a day: if new things were crossed off, nudge to put them
        away. One OurGroceries read per list - nowhere near their limits."""
        channel = self._nudges_channel()
        if channel is None or not grocy_configured():
            return
        try:
            pending, _ = await self._pending_put_away()
        except Exception as error:
            logger.warning("Evening shopping check failed: %s", error)
            return

        keys = sorted(f"{item['item_id']}:{item['crossed_off_at']}" for item in pending)
        if not keys or ",".join(keys) == get_state(SHOPPING_NUDGE_STATE_KEY):
            return  # nothing new since the last nudge
        set_state(SHOPPING_NUDGE_STATE_KEY, ",".join(keys))
        await channel.send(
            f"🛒 Looks like you shopped — **{len(pending)}** item(s) crossed off. Put them in the pantry?",
            view=PutAwayNudgeView(self),
        )

    @shopping_check_task.before_loop
    async def before_shopping_check(self):
        await self.bot.wait_until_ready()

    # --- plain-English ---

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if (
            self.pantry_channel_id is None
            or message.channel.id != self.pantry_channel_id
            or message.author.bot
            or not message.content.strip()
        ):
            return
        if not grocy_configured():
            await message.reply(NOT_CONFIGURED_MESSAGE)
            return
        try:
            async with message.channel.typing():
                replies = await handle_pantry_text(message.content, message.author.display_name)
        except (GrocyError, GrocyNotConfigured) as error:
            await message.reply(f"❌ I couldn't update the pantry: {error}")
            return
        for content, view in replies:
            if view:
                await message.reply(content, view=view, mention_author=False)
            else:
                await message.reply(content, mention_author=False)

    @app_commands.command(name="pantry", description='Update the pantry in plain English, e.g. "used 4 eggs, finished the milk"')
    @app_commands.describe(update="What happened - used, finished, bought, tossed, froze...")
    async def pantry_command(self, interaction: discord.Interaction, update: str):
        if not grocy_configured():
            await interaction.response.send_message(NOT_CONFIGURED_MESSAGE, ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        try:
            replies = await handle_pantry_text(update, interaction.user.display_name)
        except (GrocyError, GrocyNotConfigured) as error:
            await interaction.followup.send(f"❌ I couldn't update the pantry: {error}")
            return
        for content, view in replies:
            if view:
                await interaction.followup.send(content, view=view)
            else:
                await interaction.followup.send(content)

    # --- what's in stock / what can I make ---

    @app_commands.command(name="in_stock", description="See what's in the pantry")
    async def in_stock(self, interaction: discord.Interaction):
        if not grocy_configured():
            await interaction.response.send_message(NOT_CONFIGURED_MESSAGE, ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            async with Grocy() as grocy:
                state = await load_state(grocy)
                volatile = await grocy.get_volatile_stock(due_soon_days=3)
        except GrocyError as error:
            await interaction.followup.send(f"❌ I couldn't reach the pantry: {error}", ephemeral=True)
            return

        in_stock = sorted(
            (product["name"], state.amount(product["id"])) for product in state.products if state.amount(product["id"]) > 0
        )
        if not in_stock:
            await interaction.followup.send("🥫 The pantry's empty — `/put_away` after your next shop!", ephemeral=True)
            return
        lines = [f"• {name}" + (f" ×{amount:g}" if amount != 1 else "") for name, amount in in_stock]
        expiring = expiring_items(volatile)
        if expiring:
            lines += ["", "**Use soon:**"] + format_expiring_lines(expiring, datetime.now(HOUSEHOLD_TZ).date())
        text = "\n".join(lines)
        await interaction.followup.send(text[:1990], ephemeral=True)

    @app_commands.command(name="what_can_i_make", description="Recipes ranked by what's already in the pantry")
    @app_commands.describe(tag="Optional: only recipes with this tag")
    @app_commands.choices(tag=PANTRY_TAG_CHOICES)
    async def what_can_i_make(self, interaction: discord.Interaction, tag: app_commands.Choice[str] | None = None):
        if not grocy_configured():
            await interaction.response.send_message(NOT_CONFIGURED_MESSAGE, ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        try:
            async with Grocy() as grocy:
                state = await load_state(grocy)
                volatile = await grocy.get_volatile_stock(due_soon_days=3)
        except GrocyError as error:
            await interaction.followup.send(f"❌ I couldn't reach the pantry: {error}")
            return

        expiring_ids = {item["product_id"] for item in expiring_items(volatile)}
        scored = score_recipes(
            get_all_recipes(tag.value if tag else None), state.products, state.aliases, state.stock, expiring_ids
        )
        await interaction.followup.send(embed=build_what_can_i_make_embed(scored, tag.name if tag else None))

    # --- fixing matches ---

    async def _product_autocomplete(self, interaction: discord.Interaction, current: str):
        rows = get_pantry_products()
        current_lower = current.lower()
        return [
            app_commands.Choice(name=row["name"][:100], value=str(row["grocy_product_id"]))
            for row in rows
            if current_lower in row["name"].lower()
        ][:25]

    async def _tj_autocomplete(self, interaction: discord.Interaction, current: str):
        return [
            app_commands.Choice(name=f"{row['name']} (${row['price']:.2f})"[:100] if row["price"] else row["name"][:100], value=row["sku"])
            for row in search_tj_products(current or "", limit=25)
        ]

    @app_commands.command(name="pantry_fix", description="Point a pantry item at a different Trader Joe's product")
    @app_commands.describe(product="The pantry item to fix", tj_item="The right TJ's product (type to search)")
    @app_commands.autocomplete(product=_product_autocomplete, tj_item=_tj_autocomplete)
    async def pantry_fix(self, interaction: discord.Interaction, product: str, tj_item: str):
        if not grocy_configured():
            await interaction.response.send_message(NOT_CONFIGURED_MESSAGE, ephemeral=True)
            return
        row = next((row for row in get_pantry_products() if str(row["grocy_product_id"]) == product), None)
        if row is None:
            await interaction.response.send_message("❌ Pick a pantry item from the suggestions.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            async with Grocy() as grocy:
                await relink_tj_item(grocy, row["grocy_product_id"], row["name"], tj_item)
        except GrocyError as error:
            await interaction.followup.send(f"❌ I couldn't update the pantry: {error}", ephemeral=True)
            return
        await interaction.followup.send(f"✅ **{row['name']}** is now linked to that TJ's product.", ephemeral=True)

    # --- use-soon nudges ---

    @tasks.loop(time=EXPIRY_CHECK_TIME)
    async def expiry_check_task(self):
        channel = self._nudges_channel()
        if channel is None or not grocy_configured():
            return
        try:
            async with Grocy() as grocy:
                volatile = await grocy.get_volatile_stock(due_soon_days=1)
        except GrocyError as error:
            logger.warning("Expiry check failed: %s", error)
            return

        today = datetime.now(HOUSEHOLD_TZ).date()
        already = set(filter(None, (get_state(EXPIRY_NUDGED_STATE_KEY) or "").split(",")))
        items = [
            item for item in expiring_items(volatile)
            if f"{item['product_id']}:{item['best_before_date']}" not in already
        ]
        if not items:
            return
        set_state(
            EXPIRY_NUDGED_STATE_KEY,
            ",".join(sorted(already | {f"{item['product_id']}:{item['best_before_date']}" for item in items}))[-4000:],
        )
        await channel.send(
            "⏰ **Use it or freeze it:**\n" + "\n".join(format_expiring_lines(items, today, limit=EXPIRY_NUDGE_LIMIT)),
            view=ExpiryNudgeView(items),
        )

    @expiry_check_task.before_loop
    async def before_expiry_check(self):
        await self.bot.wait_until_ready()

    # --- recalls ---

    @tasks.loop(time=RECALL_CHECK_TIME)
    async def recall_check_task(self):
        if datetime.now(HOUSEHOLD_TZ).weekday() != RECALL_CHECK_WEEKDAY:
            return
        channel = self._nudges_channel()
        if channel is None or not grocy_configured():
            return
        try:
            async with Grocy() as grocy:
                state = await load_state(grocy)
            recalls = await fetch_recent_recalls(datetime.now(HOUSEHOLD_TZ).date())
        except Exception as error:
            logger.warning("Recall check failed: %s", error)
            return

        linked = {row["grocy_product_id"]: row for row in get_pantry_products()}
        on_hand = [
            {
                "name": product["name"],
                "tj_name": (linked.get(product["id"]) or {}).get("tj_name"),
                "tj_sku": (linked.get(product["id"]) or {}).get("tj_sku"),
            }
            for product in state.products
            if state.amount(product["id"]) > 0
        ]
        seen = set(filter(None, (get_state(RECALLS_SEEN_STATE_KEY) or "").split(",")))
        for match in match_recalls(recalls, on_hand):
            if match["recall_number"] in seen:
                continue
            seen.add(match["recall_number"])
            await channel.send(format_recall_alert(match))
        set_state(RECALLS_SEEN_STATE_KEY, ",".join(sorted(seen)))

    @recall_check_task.before_loop
    async def before_recall_check(self):
        await self.bot.wait_until_ready()


class PutAwayNudgeButton(discord.ui.Button):
    def __init__(self, cog: Pantry):
        super().__init__(label="🧺 Put away", style=discord.ButtonStyle.primary)
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.cog.send_put_away(interaction)


class PutAwayNudgeView(discord.ui.View):
    def __init__(self, cog: Pantry):
        super().__init__(timeout=None)
        self.add_item(PutAwayNudgeButton(cog))


async def setup(bot):
    await bot.add_cog(Pantry(bot))
