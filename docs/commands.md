# Commands

Run `/help` in Discord any time for this same list. Commands marked **(run in its thread)**
only work inside a recipe's forum thread — run them from within that specific thread, not
from `#general` or anywhere else.

## 📥 Import

| Command | What it does |
|---|---|
| `/recipe <url>` | Imports a recipe from the web, or opens a hand-entry modal for TikTok links / anything that can't be scraped. Checks for an existing import by URL first. |

## 🏷️ Organize & Fix

| Command | What it does |
|---|---|
| `/tags` **(run in its thread)** | Manually add or remove any of this recipe's tags via a checkbox menu. |
| `/fix` **(run in its thread)** | Correct a recipe's name, prep/cook/total time, or servings — the fields most likely to come back wrong from a bad scrape. |

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
| `/done <chore>` | Mark a chore as completed (autocomplete search by name). Optionally attribute it to someone else instead of yourself, or backdate it with `days_ago` (e.g. 3 for "3 days ago"). Chore reminders post automatically in #nudges at 9am and 5pm once a chore passes its threshold. |
| `/chore_stats` | Chore board size, overdue/coming-up counts, the single most overdue chore, and who most recently completed each chore. A snapshot of current state, not lifetime totals — the chores table only tracks each chore's last completion. |

## 📅 Schedule

| Command | What it does |
|---|---|
| `/task <request>` | Schedule a quick one-off task. `/task call vet` finds a free slot anywhere this week; `/task call vet thursday` finds a free slot that day; `/task call vet thursday at 5pm` skips the proposal and adds it straight to the calendar. Proposals show Confirm / Pick Different Time buttons — only the person who ran the command can respond. |
| `/week` | Schedule up to 5 one-off tasks this week in one go — 5 separate text fields, each with autocomplete suggesting your real chore names as you type (you can still type anything). Proposes a free slot for each, each with its own Confirm / Pick Different Time buttons. |
| `/refresh_this_week` | Manually rebuild the single #this-week schedule embed (events across every configured calendar, deduplicated, plus chore status) instead of waiting for the daily 6am refresh. |

## ⚙️ Admin

| Command | What it does |
|---|---|
| `/check_setup` | Compares every configured tag against what's actually on the recipe forum channel and reports mismatches or missing tags. |
| `/check_calendar_setup` | Verifies the Google service account can reach each configured calendar (i.e. it's actually been shared), and reports the calendar name or the error for each. |

---

For implementation details, see the main [README](../README.md) and
[`services/grocery_list.py`](../services/grocery_list.py) /
[`docs/ourgroceries-api-notes.md`](ourgroceries-api-notes.md) for the OurGroceries
integration specifically.
