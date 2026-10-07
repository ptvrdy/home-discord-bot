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

Grocy runs from this repo's [`grocy/`](../grocy/README.md) folder. Its compose file:
- uses the `lscr.io/linuxserver/grocy` image on port **9283**;
- keeps Grocy's data in `grocy/config/` (git-ignored);
- turns off the Grocy features Rosie or OurGroceries already cover: chores, tasks,
  calendar, recipes, meal plan and shopping list;
- adds the Trader Joe's barcode plugin and a nightly backup.

```
cd grocy
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
TJ_STORE_CODE=547                 # optional; prices vary by store. Default 547 = Downtown Brooklyn
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

**Barcodes:** when Rosie creates a pantry item from a Trader Joe's-brand product, she also
registers that product's barcode in Grocy.
- **How it works:** TJ's own-brand barcodes are `00` + the item number's last 5 digits +
  a check digit. Every case in the FDA recall records confirmed this.
- **Scanning:** the camera scanner on Grocy's mobile page (Purchase / Consume) recognizes
  the package. Barcode Buddy works too if you add it later.
- **Name-brand items** sold at TJ's carry their own barcodes, so they aren't registered.

**Scanning something new.** If you scan a Trader Joe's item that isn't in the pantry yet,
Grocy offers to look it up. The `grocy/` folder includes a Trader Joe's lookup plugin
(`grocy/plugins/TraderJoesBarcodeLookupPlugin.php`) for this:
- **What it sets:** TJ's name, section, location and shelf life, plus TJ's price on the
  barcode, so the Purchase page pre-fills it.
- **Where the data comes from:** Rosie's copy of the catalog, which Grocy reads directly.
  traderjoes.com blocks Grocy's own requests. Grocy reads this repo's `data/` folder,
  read-only; `grocy/.env` can point elsewhere (see `grocy/.env.example`).
- **Within 10 minutes**, Rosie links the new product to its TJ's item. She adds the photo
  and the other barcode lengths, and fills in the section and shelf life for anything
  Open Food Facts created.
- **Other barcodes** (name-brand items) still go to Open Food Facts, as before.
- **Keep in sync:** the shelf-life rules in the plugin mirror `config/shelf_life.py`. If you
  change one, change the other.

After each monthly catalog sync, Rosie also refreshes TJ's price on every linked barcode.

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

## Setting it up on the home server

Starting fresh on the server is simplest. Rosie's production database has no pantry data
yet, so a new Grocy and Rosie start out matching.

1. On the server, `git pull`, then `cd grocy && docker compose up -d`. The defaults already
   point at Rosie's `data/rosies_recipe_box.db`, so no `.env` is needed.
2. In Grocy (`http://<server>:9283`): log in as admin/admin, change the password and
   create an API key.
3. In Rosie's `.env`, add `GROCY_URL=http://localhost:9283`, the API key,
   `PANTRY_CHANNEL_ID` and `PANTRY_LIST_NAME`. Then restart Rosie; her new database tables
   are created automatically.
4. Run `/sync_tj_catalog` in Discord.

(To keep a dev Grocy's data instead, copy its `grocy/config/` over before step 1. Also copy
the dev database's `pantry_aliases` and `pantry_products` rows into Rosie's, so her links
point at the right Grocy products.)
