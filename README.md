# Rosie's Recipe Box 🍒

A Discord bot that turns a forum channel into a family cookbook. Import recipes from
the web (or by hand, for TikTok/Instagram-style recipes with no scrapeable page),
and Rosie tags them, posts a vintage-styled recipe card, and tracks a running
journal every time you cook something again.

SQLite is the source of truth; Discord is just the interface. Nothing important
lives only in a Discord message.

## Commands

- **`/recipe <url>`** — imports a recipe.
  - Scrapes title, ingredients, instructions, prep/cook/total time, servings, and
    image via [`recipe-scrapers`](https://github.com/hhursev/recipe-scrapers) for
    most sites. NYT Cooking gets a fallback scraper
    ([`services/nyt_fallback.py`](services/nyt_fallback.py)) that reads the page
    directly, since `recipe_scrapers` currently misses NYT's `legacyTime` field.
  - If the URL is a TikTok link (or scraping otherwise isn't possible), opens a
    two-step modal instead — name/ingredients/instructions/image/video URL, then
    prep/cook/total time and servings — producing the exact same `Recipe` object,
    fields, tags, and card layout as a scraped recipe.
  - Checks for an existing import by URL first and links you to the existing
    thread instead of creating a duplicate.
  - Posts a numbered-step instructions embed as a separate follow-up message
    (4,096-character room, vs. 1,024 on a card field).
- **`/review`** (run inside a recipe's thread) — logs that you made or reviewed a
  recipe: pick a status (📝 Needs Review / ✅ Made Before / 🔁 Make Again / ⭐
  Favorite), rate it 1–5 stars, and leave notes. Made Before / Make Again /
  Favorite always log as "Made"; only Needs Review can mean you revisited it
  without cooking. This swaps the thread's status forum tag and appends a dated,
  attributed entry to **one growing journal message** per recipe, rebuilt fresh
  from the full cooking-log history each time so it can never drift out of sync
  with the database. The full history is always in SQLite even if the rendered
  message ever hits Discord's embed character limit and has to drop old entries
  from view.
- **`/fix`** (run inside a recipe's thread) — corrects a recipe's name,
  prep/cook/total time, or servings (the fields most likely to come back wrong
  from a bad scrape), prefilled with the current values. Re-saves to SQLite,
  regenerates and reapplies forum tags, renames the thread if the title changed,
  and edits the recipe card in place — all while preserving whatever human status
  (⭐ Favorite, etc.) the recipe already has. Tags are *unioned* with what's
  already stored, not replaced, so a manual `/tags` addition never gets silently
  dropped by a later `/fix`.
- **`/tags`** (run inside a recipe's thread) — a multi-select menu, pre-checked
  with the recipe's current tags, for manually adding or removing any of the 16
  non-human tags (e.g. marking a recipe `dinner` even though nothing in its text
  matched that keyword). Syncs immediately to both SQLite and the thread's
  applied forum tags.
- **`/find_ingredient <query>`** — searches recipes by title or ingredient. Each
  word in the query is matched independently across both fields (so
  `chicken thighs` matches a recipe titled "Slow Cooker Chicken" whose
  ingredients just say "thighs"), and words that match a known tag (like `beef`)
  reuse that tag's exact include/exclude guardrails from auto-tagging — a search
  for `beef` won't match a recipe whose only beef text is "beef broth," but will
  match one whose only beef text is "ribeye."
- **`/needs_review`** — lists every recipe still marked 📝 Needs Review, oldest
  first, so the backlog doesn't just silently accumulate.
- **`/cooking_stats`** — box size, review backlog, top-rated recipes (by average
  rating), most-cooked recipes (counted from logged "Made" entries only), and
  how many entries each household member has logged.
- **`/random [tag]`** — suggests a random recipe, optionally filtered to one of
  the configured tags, with a jump link to its thread.
- **`/shopping_list`** (run inside a recipe's thread) — adds the recipe's
  ingredients to an OurGroceries list. Prompts you to pick which list (built
  dynamically from whatever lists exist on the account, e.g. per-store lists),
  skips anything already on that list, and adds ingredient text exactly as
  scraped with the recipe's name in the item's note. See
  [OurGroceries integration](#ourgroceries-integration) below.
- **`/check_setup`** — compares every tag in `config/discord_tags.py` against
  what's actually configured on the recipe forum channel and reports exact
  matches, near-matches (e.g. an invisible emoji variation-selector mismatch —
  the kind of bug that silently drops a tag with no error anywhere), and tags
  missing from the forum entirely.

## Design notes

- **Automatic tagging** — keyword-based tagging (protein, dish type, meal,
  method, time) via [`config/recipe_keywords.py`](config/recipe_keywords.py),
  matched with word boundaries so "pie" doesn't match inside "piece" and "cake"
  doesn't match inside "pancake". Discord forum channels cap out at 20 total
  tags and 5 applied per thread — both limits are already reached, so any new
  tag category requires retiring an existing one first.
- **Tag-name matching is normalized**, not exact-string. Discord's real forum
  tag and our config can disagree on invisible characters (emoji variation
  selectors) while looking visually identical; `services/forum.py` strips those
  before comparing so a tag still applies correctly either way.

## OurGroceries integration

OurGroceries has no official public API. `/shopping_list` uses the
community-maintained [`ourgroceries`](https://pypi.org/project/ourgroceries/)
package, which reverse-engineers the same endpoints their mobile app uses
(username/password login — there's no API key system to speak of). This is
unofficial and response shapes aren't guaranteed by anyone; it was built
against `ourgroceries==1.5.4` and cross-checked against Home Assistant's
production integration (which uses the same library), but hasn't been
exercised against a real account yet. If something errors, that's the first
place to look — see [`services/grocery_list.py`](services/grocery_list.py).

Set these in `.env` to enable it (see Setup below):
```
OURGROCERIES_USERNAME=your-ourgroceries-email
OURGROCERIES_PASSWORD=your-ourgroceries-password
```
`/shopping_list` fails gracefully with a clear message if these aren't set.

## Project layout

```
bot.py                     Entry point: loads the cog, syncs slash commands, initializes the DB

commands/
    recipe_commands.py     All slash commands + modals/views

models/
    recipe_card.py         Recipe dataclass — the shape every recipe takes regardless of source

services/
    scraper.py              Scrapes a URL into a Recipe via recipe_scrapers
    nyt_fallback.py          Fallback time-scraper for NYT Cooking's legacyTime field
    recipe_tags.py           Keyword-based auto-tagging
    embed.py                 Builds recipe card / instructions / stats embeds
    forum.py                 Forum tag selection/priority/matching, thread creation, setup diagnostics
    journal.py               Renders the cooking-log history into the journal embed
    grocery_list.py          OurGroceries integration
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
   OURGROCERIES_USERNAME=your-ourgroceries-email   # optional, enables /shopping_list
   OURGROCERIES_PASSWORD=your-ourgroceries-password
   ```
   `RECIPE_FORUM_ID` is the channel ID of your Discord **forum channel** where
   recipes get posted. The bot needs forum tags matching your logical tags
   (`beef`, `chicken`, `dessert`, `needs_review`, `favorite`, etc. — see
   [`config/discord_tags.py`](config/discord_tags.py) for the full list) already
   created on that forum. Run `/check_setup` after creating them to confirm
   they're recognized correctly.
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

Tests are self-contained (temp SQLite databases, mocked OurGroceries client, no
real network calls, no live Discord connection) and should run in well under a
second.

## Roadmap

- Broader tag set — blocked on Discord's 20-tag-per-forum cap; would need to
  retire an existing tag, or track new categories in SQLite only (searchable via
  `/find_ingredient`/`/random`, not shown as a forum tag chip)
- `/recipe_history` or similar for recipes whose journal has grown past what fits
  in a single Discord embed
- Live-verify `/shopping_list` against a real OurGroceries account and fix
  whatever the unofficial API's actual response shape turns out to disagree with
- Eventually: fold into a broader household-hub bot (chores, shared calendar)
