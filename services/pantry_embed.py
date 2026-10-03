"""Pure builders for pantry-related Discord output: recipe suggestions from
what's in stock, the "use soon" list, and catalog-sync summaries. No Grocy,
no SQLite - callers pass data in."""

from datetime import date

import discord

from services.grocery_list import _staple_rank
from services.ingredient_match import CONFIDENT_SCORE, best_product_match, normalize_item

EMBED_COLOR = discord.Color.from_rgb(200, 30, 45)  # TJ's red
SUGGESTION_LIMIT = 5
EXPIRING_BONUS = 0.15
FIELD_LIMIT = 1024


def _truncate(text: str, limit: int = FIELD_LIMIT) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def score_recipes(
    recipes: list[dict],
    products: list[dict],
    aliases: dict[str, int],
    stock: dict[int, float],
    expiring_ids: set[int] | None = None,
) -> list[dict]:
    """Rank recipes by how much of them is already in the pantry.

    Pantry staples (salt, oil, flour...) are assumed on hand and ignored, so
    a recipe isn't penalized for them. Score = share of the remaining
    ingredients in stock, plus a bonus for using up something about to
    expire. Recipes with nothing in stock are dropped.

    Returns [{"title", "discord_thread_id", "score", "have", "total",
    "missing", "uses_expiring"}], best first."""
    expiring_ids = expiring_ids or set()
    results = []
    for recipe in recipes:
        have, missing, uses_expiring = [], [], []
        for ingredient in recipe["ingredients"]:
            normalized = normalize_item(ingredient)
            if not normalized or _staple_rank(ingredient) is not None:
                continue
            match = best_product_match(ingredient, products, aliases)
            in_stock = (
                match is not None
                and match.score >= CONFIDENT_SCORE
                and stock.get(match.item["id"], 0) > 0
            )
            if in_stock:
                have.append(match.item["name"])
                if match.item["id"] in expiring_ids:
                    uses_expiring.append(match.item["name"])
            else:
                missing.append(normalized)

        total = len(have) + len(missing)
        if total == 0 or not have:
            continue
        score = len(have) / total + (EXPIRING_BONUS if uses_expiring else 0)
        results.append(
            {
                "title": recipe["title"],
                "discord_thread_id": recipe.get("discord_thread_id"),
                "score": round(score, 4),
                "have": len(have),
                "total": total,
                "missing": missing,
                "uses_expiring": sorted(set(uses_expiring)),
            }
        )
    results.sort(key=lambda result: (-result["score"], len(result["missing"]), result["title"]))
    return results


def build_what_can_i_make_embed(scored: list[dict], tag: str | None = None) -> discord.Embed:
    title = "🍳 What can I make?" + (f" ({tag})" if tag else "")
    embed = discord.Embed(title=title, color=EMBED_COLOR)
    if not scored:
        embed.description = (
            "Nothing in the recipe box lines up with the pantry yet. "
            "Put away some groceries with `/put_away` and try again!"
        )
        return embed

    lines = []
    for result in scored[:SUGGESTION_LIMIT]:
        name = f"<#{result['discord_thread_id']}>" if result["discord_thread_id"] else f"**{result['title']}**"
        line = f"{name} — have {result['have']}/{result['total']}"
        if result["uses_expiring"]:
            line += f" · ⏰ uses {', '.join(result['uses_expiring'])}"
        if result["missing"]:
            shown = result["missing"][:5]
            extra = len(result["missing"]) - len(shown)
            line += f"\n  missing: {', '.join(shown)}" + (f" +{extra} more" if extra else "")
        else:
            line += " · ✅ you have everything"
        lines.append(line)
    embed.description = _truncate("\n".join(lines), 4096)
    embed.set_footer(text="Pantry staples like salt, oil, and flour are assumed on hand.")
    return embed


def _days_label(best_before: str | None, today: date) -> str:
    if not best_before:
        return ""
    try:
        days = (date.fromisoformat(best_before[:10]) - today).days
    except ValueError:
        return ""
    if days < 0:
        return f"{-days}d overdue" if days < -1 else "since yesterday"
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    return f"in {days} days"


def format_expiring_lines(items: list[dict], today: date, limit: int = 8) -> list[str]:
    lines = []
    for item in items[:limit]:
        amount = f"{item['amount']:g}× " if item.get("amount", 0) > 1 else ""
        icon = "🔴" if item.get("overdue") else "🟠"
        lines.append(f"{icon} {amount}{item['name']} — {_days_label(item.get('best_before_date'), today)}")
    if len(items) > limit:
        lines.append(f"…and {len(items) - limit} more")
    return lines


def expiring_field_value(items: list[dict], today: date) -> str | None:
    """Text for #this-week's "Use soon" field, or None to leave it out."""
    if not items:
        return None
    return _truncate("\n".join(format_expiring_lines(items, today)))


def build_sync_summary(stats: dict, total: int, returned_names: list[str], new_items: list[dict]) -> str:
    lines = [
        f"🛒 Synced **{total:,}** Trader Joe's products — "
        f"{stats['added']} new to Rosie, {stats['price_changed']} price changes, "
        f"{stats['discontinued']} no longer listed."
    ]
    if returned_names:
        lines.append(f"🎃 **Back at TJ's** (you've bought these before): {', '.join(returned_names)}")
    if new_items:
        lines.append("✨ **New at TJ's:** " + ", ".join(item["name"] for item in new_items))
    return _truncate("\n".join(lines), 2000)
