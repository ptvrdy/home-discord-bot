# Commands

Run `/help` in Discord any time for this same list. Commands marked **(run in its thread)**
only work inside a recipe's forum thread — run them from within that specific thread, not
from `#general` or anywhere else.

## 📥 Import

| Command | What it does |
|---|---|
| `/recipe <url>` | Imports a recipe from the web, or opens a hand-entry modal for TikTok links / anything that can't be scraped. Checks for an existing import by URL first. |
| `/manual_recipe` | Add a recipe with no source at all — a handwritten card, a friend's text, etc. Same two-step hand-entry flow as `/recipe`'s fallback, minus the URL requirement. |

## 🏷️ Organize & Fix

| Command | What it does |
|---|---|
| `/tags` **(run in its thread)** | Manually add or remove any of this recipe's tags via a checkbox menu. |
| `/fix` **(run in its thread)** | Correct a recipe's name, prep/cook/total time, or servings — the fields most likely to come back wrong from a bad scrape. |
| `/fix_image` **(run in its thread)** | Add or correct a recipe's image — separate from `/fix` since Discord modals cap out at 5 fields and that one's already full. Leave the URL blank to remove an image entirely. |

## 🔍 Find

| Command | What it does |
|---|---|
| `/find_ingredient <query>` | Search recipes by title or ingredient. Each word in the query is matched independently, and tag-name words reuse the same include/exclude rules as auto-tagging. |
| `/random [tag]` | Suggest a random recipe, optionally filtered to one tag. |
| `/needs_review` | List every recipe still marked 📝 Needs Review, oldest first. |

## ⭐ Review & Stats

| Command | What it does |
|---|---|
| `/review` **(run in its thread)** | Log that you made or reviewed a recipe: pick a status, rate it 1–5 stars, leave notes. Appends to that recipe's single growing journal message. |
| `/cooking_stats` | Box size, review backlog, top-rated recipes, most-cooked recipes, and per-person activity. |

## 🛒 Grocery Shopping

| Command | What it does |
|---|---|
| `/shopping_list` **(run in its thread)** | Add a recipe's ingredients to an OurGroceries list. Pick which list, then uncheck anything you already have (pre-unchecked if it's already on *any* list, or a common pantry staple). An Undo button appears after adding. |
| `/combine_recipes` | Pick up to 5 recipes (autocomplete search by title) and combine their ingredients into one deduplicated shopping list, then add to whichever OurGroceries list you choose. |
| `/meal_plan` | Suggest 1-5 random recipes (optionally filtered by tag) and combine their ingredients into one shopping list, same as `/combine_recipes` but picked for you. |
| `/grocery_list` | View what's currently on one of your OurGroceries lists, without leaving Discord. |

## 🧹 Household Chores

| Command | What it does |
|---|---|
| `/done <chore>` | Log a chore as completed (autocomplete search by name). Optionally attribute it to someone else instead of yourself, or backdate it with `days_ago` (e.g. 3 for "3 days ago"). Chore reminders post automatically in #nudges at 9am and 5pm once a chore passes its threshold. Refreshes #this-week immediately. |
| `/undo_done <chore>` | Remove the most recent `/done` you logged for a chore, reverting its current state to whatever history remains. |
| `/chore_stats` | Chore board size, overdue/coming-up counts, the single most overdue chore, a completions-per-person breakdown both all-time and over the last 30 days, and a "Whose Turn?" callout for any chore one person has done 3+ times in a row. |
| `/weekly_digest` | Manually post the weekly recap (chores completed and by whom, one-off tasks completed, combined leaderboard, still overdue) instead of waiting for the automatic Sunday 8pm post. |
| `/random_chore` | Suggest what to do today, weighted toward whatever's most overdue. Congratulates you if nothing's currently overdue. |

## 🛍️ House Wishlist

| Command | What it does |
|---|---|
| `/want <url>` | Add a link to the house wishlist — pulls the title, image, and price from the page when available and posts it as a card. React ✅ once it's bought to mark it off (anyone can). |
| `/wishlist` | See everything still on the wishlist, oldest first. |

## 🍽️ Meal Plan

| Command | What it does |
|---|---|
| `/plan_meal <meal> <recipe>` | Add a recipe to this week's Breakfast/Lunch/Dinner list — deliberately *not* tied to a specific day, since dinner plans shift (takeout, forgot to defrost, ran out of an ingredient). Autocomplete suggests your saved recipes, but you can type anything. Shows up in the "🍽️ This Week's Food" section of #this-week, and auto-clears every Monday. |
| `/clear_meal_plan` | Clear this week's food list and start over. |

## 📅 Schedule

| Command | What it does |
|---|---|
| `/task <request>` | Schedule a quick one-off task. `/task call vet` finds a free slot anywhere this week; `/task call vet thursday` finds a free slot that day; `/task call vet thursday at 5pm` skips the proposal and adds it straight to the calendar, still checking for a conflict first (nothing gets added if that slot's already taken). Also understands `today` and `next <day>` (e.g. `call vet next monday at 5pm` means the *following* Monday, not today even if today is Monday). A day that's already passed this week automatically rolls to its upcoming occurrence — it never books into the past. Proposals show Confirm / Pick Different Time buttons — only the person who ran the command can respond. |
| `/week` | Schedule up to 5 one-off tasks this week in one go — 5 separate text fields, each with autocomplete suggesting your real chore names as you type (you can still type anything). Proposes a free slot for each, each with its own Confirm / Pick Different Time buttons. |
| `/refresh_this_week` | Manually rebuild the single #this-week schedule embed (events across every configured calendar, deduplicated, chore status, this week's food plan) instead of waiting for the daily 6am refresh. |
| **Edit Task Time** (right-click a confirmation message → Apps) | Change an already-booked task's time, day, and/or duration in place, instead of undoing and rebooking it. |

Once a task is booked, its confirmation message gets a ✅ reaction pre-added — react to
it once you've actually done the task to mark it completed (anyone in the server can,
not just whoever booked it). This also prefixes the event's title on the calendar
itself with ✅, so it's visibly distinguished if you check Google Calendar directly.
The completion message shows the event's *current* date/time (re-fetched from Google
Calendar), so it stays accurate even if you'd manually rescheduled the task there
since it was originally booked.

Overdue/coming-up chores on #this-week (and the "Whose Turn?" list in `/chore_stats`,
and the `#nudges` reminder) get a "whose turn?" callout whenever one household member
has logged a chore's last 3+ completions in a row (only when `PERSONAL_NAME`/
`PARTNER_NAME` are both configured) — a nudge to keep chores from quietly settling
onto one person. If `PERSONAL_DISCORD_ID`/`PARTNER_DISCORD_ID` are also set, it's a
real @-mention that pings them; otherwise it just prints their name.

## ⚙️ Admin

| Command | What it does |
|---|---|
| `/check_setup` | Compares every configured tag against what's actually on the recipe forum channel and reports mismatches or missing tags. |
| `/check_calendar_setup` | Verifies the Google service account can reach each configured calendar (i.e. it's actually been shared), and reports the calendar name or the error for each. |
| `/backup_now` | Manually back up the database right now instead of waiting for the automatic daily 3am backup. Keeps the most recent 14 backups in `data/backups/`, pruning older ones. |

---

For implementation details, see the main [README](../README.md) and
[`services/grocery_list.py`](../services/grocery_list.py) /
[`docs/ourgroceries-api-notes.md`](ourgroceries-api-notes.md) for the OurGroceries
integration specifically.
