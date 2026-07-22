# Rosie's Recipe Box 🍒

A Discord bot that turns a forum channel into a family cookbook. Import recipes from
the web (or by hand, for TikTok/Instagram-style recipes with no scrapeable page),
and Rosie tags them, posts a vintage-styled recipe card, and tracks a running
journal every time you cook something again.

SQLite is the source of truth; Discord is just the interface. Nothing important
lives only in a Discord message.

## Commands

Run `/help` in Discord any time for a categorized list of every command, or see
[`docs/commands.md`](docs/commands.md) for the same reference in the repo.

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
  then shows every ingredient as a toggle button (pre-checked, tap to
  uncheck) so you can skip anything you already have before anything's
  added — including ones already sitting on *any* of your lists, not just
  the one you're adding to, each labeled with which list it's already on. If
  a recipe has more ingredients than fit in Discord's 24-button cap, common
  pantry staples (flour, sugar, salt, etc., ranked by how universally people
  already have them) are dropped first. After adding, an "Undo" button lets
  you remove exactly what was just added. See
  [OurGroceries integration](#ourgroceries-integration) below.
- **`/combine_recipes`** — pick up to 5 recipes (autocomplete search by title
  as you type each one) and merge their ingredients into a single
  deduplicated shopping trip, then pick a list and toggle ingredients exactly
  like `/shopping_list` — same pantry-staple prioritization, cross-list
  duplicate check, and Undo button.
- **`/meal_plan [count] [tag]`** — the same combined-shopping-list flow as
  `/combine_recipes`, but the recipes are picked for you at random (1-5,
  optionally filtered by tag) instead of searched by name.
- **`/grocery_list`** — pick one of your OurGroceries lists and see what's
  currently on it (and how many items are already crossed off), without
  leaving Discord.
- **`/check_setup`** — compares every tag in `config/discord_tags.py` against
  what's actually configured on the recipe forum channel and reports exact
  matches, near-matches (e.g. an invisible emoji variation-selector mismatch —
  the kind of bug that silently drops a tag with no error anywhere), and tags
  missing from the forum entirely.
- **`/help`** — lists every command above, grouped by category, from within Discord.

## Household chores

The bot also tracks recurring household chores (SQLite, same database as everything
else). Each chore has a nudge threshold in days and remembers who last did it and when.

- **`/done <chore>`** — marks a chore completed under whichever Discord user ran
  the command, or under someone else if you pass `completed_by`. Autocomplete
  helps you pick the exact chore name. Doing a chore also clears any pending
  overdue reminder for it.
- **Automatic nudges** — a background task checks every chore at 9am and 5pm
  (household timezone) and posts to `#nudges` (set via `NUDGES_CHANNEL_ID`) the
  first time a chore crosses its threshold, mentioning who last did it and how
  long ago. It won't repeat the same reminder — a chore only nudges again after
  `/done` is run and it goes overdue again.
- The default chore list and thresholds live in
  [`config/chores.py`](config/chores.py); editing that file only affects new
  installs, since existing chores already have their own history in SQLite.

## #this-week

A single message in a channel of your choice (set via `THIS_WEEK_CHANNEL_ID`) that
gets rebuilt every morning at 6am household time — never a new message, always the
same one edited in place. It shows:

- The current week (Monday–Sunday), one field per day, with every event from every
  configured Google Calendar — deduplicated across calendars and tagged with which
  calendar(s) it came from (e.g. `📅 Personal · Family`).
- If `PERSONAL_NAME` and `PARTNER_NAME` are both set, an office/home status line at
  the top of each day: 🏢 for whoever's in the office that day, 🏠 for whoever's
  home, combined onto one line when you're both in the same state (e.g.
  `🏠 YourName & PartnerName`) or split onto two lines when you're not. Driven
  entirely by all-day calendar events named `"<name> office day"`
  (case-insensitive, matched against whatever `PERSONAL_NAME`/`PARTNER_NAME` are
  set to) — put them on whichever calendar you like, they're matched by name only,
  and don't show up in the regular event list since the status line
  already covers them. With neither name set, this line doesn't appear at all.
- Chore status — anything overdue, and anything coming due within the next few days.

Run **`/refresh_this_week`** any time to rebuild it immediately instead of waiting
for the next morning — handy right after setup, or after adding/removing a calendar.
If a calendar can't be reached (not shared yet, bad ID), the embed still posts with
an error field instead of failing silently — pair it with `/check_calendar_setup`
to pin down which calendar needs attention. Confirming a `/task` or `/week` proposal
also triggers an immediate refresh, so newly-booked events show up right away.

## Scheduling one-off tasks: /task and /week

Recurring chores live in SQLite (see above); one-off action items live on the
calendar instead, via **`/task`** and **`/week`**. Both only ever propose times
inside a 9am–8pm window, and only the person who ran the command needs to confirm
— no partner sign-off required. If `SCHEDULE_BUILDER_CHANNEL_ID` is set, both
commands are confined to that channel; otherwise they work anywhere.

- **`/task <request>`** — the exact text becomes the task name, with an optional
  trailing day and time:
  - `/task call vet` — finds a free 30-minute slot anywhere this week and proposes it.
  - `/task call vet thursday` — finds a free slot specifically on Thursday.
  - `/task call vet thursday at 5pm` — skips the proposal entirely and adds it
    straight to the calendar at that exact time.
  - A proposal shows **Confirm** and **Pick Different Time** buttons. Confirm adds
    it to the calendar and refreshes `#this-week`; Pick Different Time replaces the
    message with up to 3 alternative time buttons — clicking one books it directly.
- **`/week`** — schedules up to 5 tasks at once via 5 separate text fields
  (`task_1`...`task_5`, only the first is required). Each field autocompletes
  against your real chore names as you type, but nothing stops you from typing
  something else entirely — it's a convenience, not a restriction. `/week` (like
  `/task`) doesn't touch the chores table at all: confirming a proposal only adds
  a calendar event, it never marks a chore as done via `/done`. Each task gets its
  own free-slot proposal and its own Confirm / Pick Different Time buttons, and
  tasks within the same `/week` call won't be proposed the same slot as each
  other even before any of them are confirmed.
- New events go on the shared **Family** calendar by default (or whichever calendar
  is configured if Family isn't set), overridable via `TASK_CALENDAR_ID` in `.env`.
- Default task duration is a fixed 30 minutes — there's no per-task duration input
  yet.
- Slot proposals never land in the past — "somewhere this week" only considers the
  current moment onward, never earlier today or an already-past day.
- When no specific day is requested and more than one slot is being proposed (the
  3 "Pick Different Time" alternatives, or multiple `/week` tasks in one call),
  results are spread across different days first rather than clustering into the
  same afternoon.
- Every proposal has a **Cancel** button alongside Confirm / Pick Different Time —
  a graceful way to back out without adding anything to the calendar.
- On any day flagged as an office day for either person (see the `#this-week`
  section above for how those are detected), proposals don't start until 5pm
  instead of 9am — the assumption being that either of you might not be home
  during the day, so it's safer to default chores/tasks to after work.

## Google Calendar setup

The bot reads (and will eventually write to) up to 4 calendars — your personal
calendar, your partner's personal calendar, a shared family calendar, and a separate
"Discord (Gaming)" calendar used to schedule game nights for a friends' Discord
server — using a single Google **service
account** rather than a per-user OAuth login. That means no browser consent screen
inside the bot and no refresh tokens to manage; instead, the bot has its own Google
identity, and each calendar owner does a one-time share, the same way you'd share a
calendar with another person. Any subset of the 4 can be configured — there's no
requirement to have all of them set up before the bot is useful.

1. **Create a Google Cloud project.** Go to
   [console.cloud.google.com](https://console.cloud.google.com), create a new project
   (any name, e.g. "Household Hub Bot").
2. **Enable the Calendar API.** In that project, go to *APIs & Services → Library*,
   search "Google Calendar API", and enable it.
3. **Create a service account.** *APIs & Services → Credentials → Create Credentials
   → Service account*. Give it any name (e.g. `household-hub-bot`) — no roles needed.
4. **Create a key for it.** Open the new service account → *Keys → Add Key → Create
   new key → JSON*. This downloads a `.json` file — save it as
   `google-service-account.json` in the project root (already covered by
   `.gitignore`, so it won't get committed). **Never commit or share this file** —
   it's a live credential.
5. **Copy the service account's email.** It looks like
   `household-hub-bot@your-project-id.iam.gserviceaccount.com` — find it on the
   service account's details page.
6. **Share each calendar with that email**, once per calendar (yours, your
   partner's, the shared family one, and/or the Discord gaming one): open Google
   Calendar → hover the calendar → ⋮ → *Settings and sharing* → *Share with
   specific people* → paste the service account's email → set permission to
   **"Make changes to events"** (needed so `/week` and `/task` can create events,
   not just read).
7. **Find each calendar's ID.** Same *Settings and sharing* page, under
   "Integrate calendar" → **Calendar ID**. For a personal calendar this is usually
   just the Gmail address; for a created shared calendar it looks like
   `abc123@group.calendar.google.com`.
8. Set these in `.env`:
   ```
   GOOGLE_SERVICE_ACCOUNT_FILE=google-service-account.json   # optional, this is the default
   PERSONAL_CALENDAR_ID=you@gmail.com
   PARTNER_CALENDAR_ID=partner@gmail.com
   FAMILY_CALENDAR_ID=abc123@group.calendar.google.com
   DISCORD_CALENDAR_ID=def456@group.calendar.google.com
   ```
   All 4 are optional and independent — set however many are ready. Run
   `/check_calendar_setup` afterward to confirm the bot can actually reach each one
   (a calendar that hasn't been shared yet, or a typo'd ID, shows up there instead of
   failing silently later).

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

OurGroceries has no official public API. `/shopping_list` and `/grocery_list` use the
community-maintained [`ourgroceries`](https://pypi.org/project/ourgroceries/)
package, which reverse-engineers the same endpoints their mobile app uses
(username/password login — there's no API key system to speak of). This is
unofficial and response shapes aren't guaranteed by anyone; it was built
against `ourgroceries==1.5.4` and cross-checked against Home Assistant's
production integration (which uses the same library), and has since been
verified live against a real account. If something errors, that's the first
place to look — see [`services/grocery_list.py`](services/grocery_list.py).

Two non-obvious things this project ran into while reverse-engineering the response
shapes (crossed-off status living under a different field than the library's own
default assumes, and item text appearing under two different keys depending on the
response path) are written up in
[`docs/ourgroceries-api-notes.md`](docs/ourgroceries-api-notes.md), in case it saves
someone else the same digging.

Set these in `.env` to enable it (see Setup below):
```
OURGROCERIES_USERNAME=your-ourgroceries-email
OURGROCERIES_PASSWORD=your-ourgroceries-password
```
`/shopping_list` fails gracefully with a clear message if these aren't set.

## Project layout

```
bot.py                     Entry point: loads the cogs, syncs slash commands, initializes the DB

commands/
    recipe_commands.py     Recipe box slash commands + modals/views
    chore_commands.py      /done + the background nudge scheduler
    schedule_commands.py   Calendar diagnostics, the #this-week refresh loop, and
                            the /task and /week scheduling flows

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
    chores.py                Pure chore-overdue logic (no Discord, no SQLite)
    google_calendar.py       Google Calendar service-account integration
    schedule.py               Pure event date-math/dedup/free-slot-finding/formatting logic
    this_week_embed.py        Builds the #this-week embed layout
    image_layout.py          Decides thumbnail vs. full-size image based on aspect ratio
    time_parser.py           Parses "PT1H30M" / "2 hours" / "20" into minutes
    database.py              SQLite schema, migrations, and all persistence

config/
    discord_tags.py          Maps logical tag keys to Discord forum tag names/emoji
    recipe_keywords.py       Include/exclude keyword rules per tag
    chores.py                Default chores and their nudge thresholds

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
   NUDGES_CHANNEL_ID=123456789012345678   # optional, enables chore nudges
   GOOGLE_SERVICE_ACCOUNT_FILE=google-service-account.json   # optional, see below
   PERSONAL_CALENDAR_ID=you@gmail.com                        # optional, see below
   PARTNER_CALENDAR_ID=partner@gmail.com                     # optional, see below
   FAMILY_CALENDAR_ID=abc123@group.calendar.google.com       # optional, see below
   DISCORD_CALENDAR_ID=def456@group.calendar.google.com      # optional, see below
   THIS_WEEK_CHANNEL_ID=123456789012345678                   # optional, enables #this-week
   SCHEDULE_BUILDER_CHANNEL_ID=123456789012345678             # optional, confines /task + /week to one channel
   TASK_CALENDAR_ID=abc123@group.calendar.google.com          # optional, defaults to the Family calendar
   PERSONAL_NAME=YourName                                     # optional, enables office/home status - see #this-week
   PARTNER_NAME=PartnerName                                   # optional, enables office/home status - see #this-week
   ```
   `RECIPE_FORUM_ID` is the channel ID of your Discord **forum channel** where
   recipes get posted. The bot needs forum tags matching your logical tags
   (`beef`, `chicken`, `dessert`, `needs_review`, `favorite`, etc. — see
   [`config/discord_tags.py`](config/discord_tags.py) for the full list) already
   created on that forum. Run `/check_setup` after creating them to confirm
   they're recognized correctly.

   `NUDGES_CHANNEL_ID` is the channel ID of a plain text channel (e.g. `#nudges`)
   where overdue-chore reminders get posted. Without it, `/done` still works —
   the background nudge check just has nowhere to post, so it silently no-ops.
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
- Household hub — ✅ chore tracking (`/done`, nudges), ✅ Google Calendar
  credentials/access (`/check_calendar_setup`), ✅ reading + deduplicating events
  across all 4 calendars, ✅ the daily `#this-week` summary embed, ✅ `/task` and
  `/week` scheduling flows (including a Cancel button on every proposal), ✅
  office-day-aware scheduling (5pm-only proposals on a day either person is
  marked in-office, plus an office/home status line on `#this-week`). All
  originally-scoped pieces are built; possible next steps if useful later:
  - Per-task duration instead of a fixed 30 minutes; editing or cancelling an
    already-confirmed task/event from Discord (not just an unconfirmed proposal)
  - Mark a one-off `/task`/`/week` item as actually completed via a ✅ reaction on
    its confirmation message, separate from the recurring-chore `/done` system
