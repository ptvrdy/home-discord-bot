# Rosie's Recipe Box 🍒

A Discord bot that turns a forum channel into a family cookbook. Import recipes from
the web (or by hand, for TikTok/Instagram-style recipes with no scrapeable page),
and Rosie tags them, posts a recipe card, and tracks a running journal every time
you cook something again.

SQLite is the source of truth; Discord is just the interface. Nothing important
lives only in a Discord message.

## Features

- **`/recipe <url>`** — scrapes title, ingredients, instructions, prep/cook/total
  time, servings, and image from most recipe sites (via
  [`recipe-scrapers`](https://github.com/hhursev/recipe-scrapers)), then posts a
  formatted recipe card as a new forum thread.
  - NYT Cooking recipes get a fallback scraper ([`services/nyt_fallback.py`](services/nyt_fallback.py))
    that reads the page directly, since `recipe_scrapers` currently misses NYT's
    `legacyTime` field.
  - If the URL is a TikTok link (or scraping otherwise isn't possible), `/recipe`
    opens a two-step modal instead — name/ingredients/instructions/image/video URL,
    then prep/cook/total time and servings — so manually-added recipes end up as
    the exact same `Recipe` object as a scraped one, with the same fields, tags,
    and card layout.
- **Automatic tagging** — keyword-based tagging (protein, dish type, meal, method,
  time) via [`config/recipe_keywords.py`](config/recipe_keywords.py), matched with
  word boundaries so "pie" doesn't match inside "piece" and "cake" doesn't match
  inside "pancake". Up to 4 recipe tags plus 1 human-status tag are applied per
  thread (Discord forum tag limits).
- **`/review`** (run inside a recipe's thread) — logs that you made or reviewed a
  recipe: pick a status (📝 Needs Review / ✅ Made Before / 🔁 Make Again / ⭐
  Favorite), rate it 1–5 stars, and leave notes. This:
  - Swaps the thread's status forum tag
  - Appends a dated, attributed entry to **one growing journal message** per
    recipe (rebuilt fresh from the full cooking-log history each time, so it can
    never drift out of sync with the database)
  - Records the entry in SQLite permanently — even if the rendered journal message
    ever hits Discord's embed character limit and has to drop old entries from
    view, nothing is lost from the database
- **SQLite persistence** ([`services/database.py`](services/database.py)) — every
  recipe, its tags, its human status, and its full cooking history are stored
  durably, keyed off the Discord thread ID. Schema migrations run automatically
  and idempotently on startup.

## Project layout

```
bot.py                     Entry point: loads the cog, syncs slash commands, initializes the DB

commands/
    recipe_commands.py     /recipe, /review slash commands + modals

models/
    recipe_card.py         Recipe dataclass — the shape every recipe takes regardless of source

services/
    scraper.py              Scrapes a URL into a Recipe via recipe_scrapers
    nyt_fallback.py          Fallback time-scraper for NYT Cooking's legacyTime field
    recipe_tags.py           Keyword-based auto-tagging
    embed.py                 Builds the recipe card embed
    forum.py                 Forum tag selection/priority, thread creation
    journal.py               Renders the cooking-log history into the journal embed
    image_layout.py          Decides thumbnail vs. full-size image based on aspect ratio
    time_parser.py           Parses "PT1H30M" / "2 hours" / "20" into minutes
    database.py              SQLite schema, migrations, and all persistence

config/
    discord_tags.py          Maps logical tag keys to Discord forum tag names/emoji
    recipe_keywords.py       Include/exclude keyword rules per tag

tests/                       Unit tests (unittest) for the services above
```

## Setup

1. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
2. Create a `.env` file in the project root:
   ```
   DISCORD_TOKEN=your-bot-token
   RECIPE_FORUM_ID=123456789012345678
   HOUSEHOLD_TIMEZONE=America/New_York   # optional, defaults to America/New_York
   ```
   `RECIPE_FORUM_ID` is the channel ID of your Discord **forum channel** where
   recipes get posted. The bot needs `applied_tags` matching your logical tags
   (`beef`, `chicken`, `dessert`, `needs_review`, `favorite`, etc. — see
   [`config/discord_tags.py`](config/discord_tags.py) for the full list) already
   created on that forum.
3. Run the bot:
   ```
   python bot.py
   ```

On first run, `bot.py` creates `data/rosies_recipe_box.db` automatically and syncs
slash commands globally (global command updates can take up to an hour to appear
on all clients — if a command doesn't show up right away, try fully restarting
your Discord client before assuming something's broken).

## Testing

```
python -m unittest discover tests
```

Tests are self-contained (temp SQLite databases, no network calls, no live
Discord connection) and should run in well under a second.

## Roadmap

- Vintage cookbook visual styling
- Broader tag set (high protein, freezer-friendly, one-pot, etc.)
- `/recipe_history` or similar for recipes whose journal has grown past what fits
  in a single Discord embed
- Eventually: fold into a broader household-hub bot (chores, shared calendar,
  grocery list integration)
