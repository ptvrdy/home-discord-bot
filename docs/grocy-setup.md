# Pantry setup (Grocy + Trader Joe's)

Rosie's pantry features keep inventory in [Grocy](https://grocy.info), a self-hosted
inventory app, but you almost never open Grocy itself. Rosie handles it:

- **Products are generic household names** ("Chicken thigh", "Egg"), the same words you
  type into OurGroceries and recipes use.
- **Product details come from Trader Joe's.** When something is bought for the first
  time, Rosie creates the Grocy product from its best match in the TJ's catalog: photo,
  price, category, where it's stored, and how long it keeps. Nothing is photographed or
  typed by hand.
- **Rosie learns.** Every match you confirm is remembered, so it's instant next time.

Grocy is optional. Without `GROCY_URL`/`GROCY_API_KEY`, the pantry commands explain what's
missing and every other part of Rosie works as before.

## 1. Run Grocy

Grocy runs from its own folder outside this repo, alongside its data. On the dev PC
that's `Desktop\Scripts\grocy`, which holds a `docker-compose.yml` and a short
`SETUP.md`. The compose file:
- uses the `lscr.io/linuxserver/grocy` image on port **9283**;
- stores everything in `./config`;
- turns off the Grocy features Rosie or OurGroceries already cover: chores, tasks,
  calendar, recipes, meal plan and shopping list.

```
docker compose up -d
```

Then open `http://localhost:9283`:

1. **Log in** as `admin` / `admin`, then **change the password** (top right → user
   menu).
2. **Create an API key:** top right → user menu → **Manage API keys** → **Add**. Copy
   the key.

You don't need to create locations, units or product groups. Rosie creates **Fridge**,
**Freezer** and **Pantry** and a "Piece" unit on first use, and makes product groups
from TJ's categories as it goes.

## 2. Configure Rosie

Add to `.env` (or `.env.dev` for a dev bot):

```
GROCY_URL=http://localhost:9283
GROCY_API_KEY=the-key-from-step-1
TJ_STORE_CODE=701                 # optional; your store's code (prices are per store)
PANTRY_CHANNEL_ID=123456789012345678   # optional; a #pantry channel for plain-English updates
PANTRY_LIST_NAME=Trader Joe's     # optional; the OurGroceries list "add to list" uses
```

Restart Rosie and run **`/sync_tj_catalog`** once to load the catalog (about 2,500 items,
takes about 30 seconds). After that it re-syncs on the 1st of each month.

## How the pieces fit

| You do | Rosie does |
|---|---|
| Cross items off in OurGroceries while shopping | At 7pm, offers **Put away** in #nudges. You uncheck anything you didn't buy, and it's in stock. `/put_away` works any time. |
| Type "used 4 eggs, finished the milk" in #pantry | Updates stock. When something hits zero, gives you a button to add it back to the list. |
| `/review` a recipe as made | Offers to use up its in-stock ingredients, with counts like "3 eggs" respected. |
| `/shopping_list` | Starts in-stock ingredients unchecked, labeled "(in pantry)". |
| Nothing | Meat that's about to expire shows on #this-week and gets a 9am "use it or freeze it" nudge with 🧊 Froze it / ✅ Used it buttons. |
| Nothing | Every Monday, checks FDA recalls mentioning Trader Joe's against what's in stock. |

**Shelf lives** live in [`config/shelf_life.py`](../config/shelf_life.py):
- **Meat and seafood** keep 2–3 days in the fridge and about 4 months frozen.
- **Produce** has a 5-day default but is **off** until `TRACK_PRODUCE = True`.
- **Everything else** never expires, so it never nags.
- **These are only defaults** for new products. Edit a product in Grocy to change one
  that already exists.

## Running a dev copy on another machine

To test without touching the real bot:

1. Create a second application in the Discord Developer Portal (e.g. "Rosie Dev") and
   invite it to a private test server.
2. Create `.env.dev` (git-ignored) with that bot's `DISCORD_TOKEN`, the test server's
   channel IDs, the Grocy settings above, and
   `ROSIE_DATABASE_PATH=data/rosie_dev.db` so the dev bot keeps its own database.
   - Leave the Google Calendar IDs unset; those features switch off cleanly.
   - Use a scratch OurGroceries list for testing.
3. Run `ROSIE_ENV_FILE=.env.dev python bot.py`. In PowerShell:
   `$env:ROSIE_ENV_FILE=".env.dev"; python bot.py`.

## Moving Grocy to the home server

1. Copy the whole Grocy folder, including `config/`, to the server and run
   `docker compose up -d` there. To start fresh instead, skip `config/` and redo step 1
   above.
2. In the server's `.env`, set `GROCY_URL=http://localhost:9283` and the API key (a new
   one if you started fresh), plus `PANTRY_CHANNEL_ID` etc.
3. Pull and restart Rosie as usual. The new database tables are created automatically on
   startup.
   - **Database:** if you started Grocy fresh, the pantry tables in Rosie's database will
     be empty too. That's expected, because the catalog re-syncs and aliases are
     relearned as you use it.
   - **Moving Grocy data:** if you kept Grocy's data, copy the dev bot's
     `pantry_aliases` and `pantry_products` rows as well, so Rosie's links keep pointing
     at the right Grocy products.
