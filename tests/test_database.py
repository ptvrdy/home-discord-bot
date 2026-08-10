import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from models.recipe_card import Recipe
from services.database import (
    add_cooking_log,
    delete_booked_task,
    get_all_chores,
    get_booked_task,
    get_chore_completions_between,
    get_chore_completions_by_person,
    get_chore_log_entries,
    add_meal_plan_item,
    clear_meal_plan,
    get_chore_names,
    get_completed_tasks_between,
    get_cooking_log_entries,
    get_meal_plan_items,
    get_cooking_stats,
    get_journal_message_id,
    get_random_recipe,
    get_random_recipes,
    get_recipe_by_thread,
    get_recipe_by_title,
    get_recipe_by_url,
    get_recipe_tags,
    get_recipes_needing_review,
    get_open_wishlist_items,
    get_state,
    get_wishlist_item,
    initialize_database,
    mark_chore_done,
    mark_nudge_sent,
    mark_task_completed,
    mark_wishlist_item_bought,
    record_booked_task,
    record_wishlist_item,
    save_recipe,
    set_state,
    search_recipe_titles,
    search_recipes,
    set_journal_message_id,
    undo_last_done,
    set_recipe_tags,
    update_recipe_status,
)


class DatabaseTests(unittest.TestCase):
    def test_saves_a_recipe_tags_status_and_cooking_log(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            recipe = Recipe(
                title="Tomato Pasta",
                ingredients=["pasta", "tomatoes"],
                instructions="Cook and serve.",
                source_url="https://example.com/tomato-pasta",
                tags=["needs_review", "pasta", "vegetarian"],
            )

            initialize_database(database_path)
            recipe_id = save_recipe(recipe, 12345, database_path)
            self.assertGreater(recipe_id, 0)
            self.assertTrue(update_recipe_status(12345, "favorite", database_path))
            self.assertTrue(
                add_cooking_log(
                    12345,
                    datetime(2026, 7, 17, tzinfo=timezone.utc),
                    "Made",
                    "favorite",
                    "Used extra basil.",
                    "Add more garlic.",
                    5,
                    "Peyton",
                    database_path,
                )
            )

            connection = sqlite3.connect(database_path)
            try:
                status = connection.execute(
                    "SELECT human_status FROM recipes WHERE id = ?", (recipe_id,)
                ).fetchone()[0]
                tags = connection.execute(
                    "SELECT tag FROM recipe_tags WHERE recipe_id = ? ORDER BY tag", (recipe_id,)
                ).fetchall()
                log_entry = connection.execute(
                    "SELECT activity, status, notes, rating, author_name FROM cooking_log WHERE recipe_id = ?",
                    (recipe_id,),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(status, "favorite")
            self.assertEqual(tags, [("favorite",), ("pasta",), ("vegetarian",)])
            self.assertEqual(
                log_entry, ("Made", "favorite", "Used extra basil.", 5, "Peyton")
            )

    def test_cooking_log_entries_are_returned_oldest_first(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            recipe = Recipe(title="Chili", ingredients=["beef", "beans"], source_url="https://example.com/chili")

            initialize_database(database_path)
            save_recipe(recipe, 555, database_path)
            add_cooking_log(
                555, datetime(2026, 1, 1, tzinfo=timezone.utc), "Made", "made_before",
                "First try.", None, 3, "Peyton", database_path,
            )
            add_cooking_log(
                555, datetime(2026, 2, 1, tzinfo=timezone.utc), "Made", "make_again",
                "Better second time.", "More cumin.", 5, "Husband", database_path,
            )

            entries = get_cooking_log_entries(555, database_path)

            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0]["author_name"], "Peyton")
            self.assertEqual(entries[1]["author_name"], "Husband")

    def test_journal_message_id_round_trips(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            recipe = Recipe(title="Chili", ingredients=["beef"], source_url="https://example.com/chili")

            initialize_database(database_path)
            save_recipe(recipe, 777, database_path)

            self.assertIsNone(get_journal_message_id(777, database_path))

            set_journal_message_id(777, 999888777, database_path)

            self.assertEqual(get_journal_message_id(777, database_path), 999888777)

    def test_get_recipe_by_thread_returns_full_fields(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            recipe = Recipe(
                title="Chili",
                ingredients=["beef", "beans"],
                instructions="Simmer for an hour.",
                prep_time="10 minutes",
                cook_time="50 minutes",
                total_time="60 minutes",
                total_minutes=60,
                yields="6 servings",
                source_url="https://example.com/chili",
                source_name="Example Kitchen",
                tags=["beef", "soup"],
            )

            initialize_database(database_path)
            save_recipe(recipe, 321, database_path)

            self.assertIsNone(get_recipe_by_thread(999, database_path))

            stored = get_recipe_by_thread(321, database_path)

            self.assertEqual(stored["title"], "Chili")
            self.assertEqual(stored["ingredients"], ["beef", "beans"])
            self.assertEqual(stored["cook_time"], "50 minutes")
            self.assertEqual(stored["source_name"], "Example Kitchen")

    def test_get_random_recipe_filters_by_tag(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)

            self.assertIsNone(get_random_recipe(database_path=database_path))

            save_recipe(
                Recipe(title="Chili", ingredients=["beef"], source_url="https://example.com/chili", tags=["beef"]),
                111, database_path,
            )
            save_recipe(
                Recipe(title="Salad", ingredients=["lettuce"], source_url="https://example.com/salad", tags=["vegetarian"]),
                222, database_path,
            )

            self.assertIsNotNone(get_random_recipe(database_path=database_path))

            beef_pick = get_random_recipe("beef", database_path)
            self.assertEqual(beef_pick["title"], "Chili")

            self.assertIsNone(get_random_recipe("dessert", database_path))

    def test_get_random_recipes_returns_requested_count_with_ingredients(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            for i in range(5):
                save_recipe(
                    Recipe(title=f"Recipe {i}", ingredients=[f"ingredient {i}"], source_url=f"https://x.com/{i}"),
                    i, database_path,
                )

            results = get_random_recipes(3, database_path=database_path)

            self.assertEqual(len(results), 3)
            for result in results:
                self.assertIn("title", result)
                self.assertIn("discord_thread_id", result)
                self.assertTrue(result["ingredients"])

    def test_get_random_recipes_filters_by_tag(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            save_recipe(
                Recipe(title="Chili", ingredients=["beef"], source_url="https://x.com/1", tags=["beef"]),
                1, database_path,
            )
            save_recipe(
                Recipe(title="Salad", ingredients=["lettuce"], source_url="https://x.com/2", tags=["vegetarian"]),
                2, database_path,
            )

            results = get_random_recipes(5, tag="beef", database_path=database_path)

            self.assertEqual([r["title"] for r in results], ["Chili"])

    def test_get_random_recipes_returns_fewer_than_requested_if_not_enough_exist(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            save_recipe(
                Recipe(title="Chili", ingredients=["beef"], source_url="https://x.com/1"),
                1, database_path,
            )

            results = get_random_recipes(5, database_path=database_path)

            self.assertEqual(len(results), 1)

    def test_get_recipe_by_url_finds_existing_import(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)

            self.assertIsNone(get_recipe_by_url("https://example.com/chili", database_path))

            save_recipe(
                Recipe(title="Chili", ingredients=["beef"], source_url="https://example.com/chili"),
                444, database_path,
            )

            found = get_recipe_by_url("https://example.com/chili", database_path)
            self.assertEqual(found["title"], "Chili")
            self.assertEqual(found["discord_thread_id"], 444)

            self.assertIsNone(get_recipe_by_url("https://example.com/other", database_path))

    def test_get_recipes_needing_review_excludes_reviewed_recipes(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            save_recipe(
                Recipe(title="Chili", ingredients=["beef"], source_url="https://x.com/1"),
                1, database_path,
            )
            save_recipe(
                Recipe(title="Salad", ingredients=["lettuce"], source_url="https://x.com/2"),
                2, database_path,
            )
            update_recipe_status(2, "favorite", database_path)

            results = get_recipes_needing_review(database_path=database_path)

            self.assertEqual([r["title"] for r in results], ["Chili"])

    def test_get_recipes_needing_review_orders_oldest_first(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            save_recipe(
                Recipe(title="Newer", ingredients=["x"], source_url="https://x.com/1"),
                1, database_path,
            )
            save_recipe(
                Recipe(title="Older", ingredients=["x"], source_url="https://x.com/2"),
                2, database_path,
            )

            connection = sqlite3.connect(database_path)
            connection.execute("UPDATE recipes SET created_at = '2020-01-01' WHERE discord_thread_id = 2")
            connection.commit()
            connection.close()

            results = get_recipes_needing_review(database_path=database_path)

            self.assertEqual([r["title"] for r in results], ["Older", "Newer"])

    def test_get_recipes_needing_review_respects_limit(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            for i in range(5):
                save_recipe(
                    Recipe(title=f"Recipe {i}", ingredients=["x"], source_url=f"https://x.com/{i}"),
                    i, database_path,
                )

            results = get_recipes_needing_review(limit=3, database_path=database_path)

            self.assertEqual(len(results), 3)

    def test_get_cooking_stats_on_empty_database(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)

            stats = get_cooking_stats(database_path=database_path)

            self.assertEqual(stats["total_recipes"], 0)
            self.assertEqual(stats["needs_review_count"], 0)
            self.assertEqual(stats["top_rated"], [])
            self.assertEqual(stats["most_cooked"], [])
            self.assertEqual(stats["by_author"], [])

    def test_get_cooking_stats_aggregates_ratings_and_authors(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)

            save_recipe(
                Recipe(title="Chili", ingredients=["beef"], source_url="https://x.com/1"),
                1, database_path,
            )
            save_recipe(
                Recipe(title="Salad", ingredients=["lettuce"], source_url="https://x.com/2"),
                2, database_path,
            )
            save_recipe(
                Recipe(title="Untouched Soup", ingredients=["broth"], source_url="https://x.com/3"),
                3, database_path,
            )
            update_recipe_status(2, "favorite", database_path)

            add_cooking_log(
                1, datetime(2026, 1, 1, tzinfo=timezone.utc), "Made", "made_before",
                None, None, 4, "Peyton", database_path,
            )
            add_cooking_log(
                1, datetime(2026, 1, 15, tzinfo=timezone.utc), "Made", "make_again",
                None, None, 5, "Husband", database_path,
            )
            add_cooking_log(
                2, datetime(2026, 1, 10, tzinfo=timezone.utc), "Reviewed", "favorite",
                None, None, 3, "Peyton", database_path,
            )

            stats = get_cooking_stats(database_path=database_path)

            self.assertEqual(stats["total_recipes"], 3)
            # Chili moved to "make_again" and Salad to "favorite" via the
            # logging above; only the untouched Soup is still needs_review.
            self.assertEqual(stats["needs_review_count"], 1)

            self.assertEqual(len(stats["top_rated"]), 2)
            self.assertEqual(stats["top_rated"][0]["title"], "Chili")
            self.assertAlmostEqual(stats["top_rated"][0]["avg_rating"], 4.5)

            # "Reviewed" isn't "Made", so Salad shouldn't count as cooked.
            self.assertEqual([r["title"] for r in stats["most_cooked"]], ["Chili"])
            self.assertEqual(stats["most_cooked"][0]["times_made"], 2)

            author_counts = {a["author_name"]: a["entry_count"] for a in stats["by_author"]}
            self.assertEqual(author_counts, {"Peyton": 2, "Husband": 1})

    def test_set_recipe_tags_replaces_non_human_tags_but_preserves_status(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            recipe = Recipe(
                title="Salmon Burgers",
                ingredients=["salmon"],
                source_url="https://example.com/salmon-burgers",
                tags=["needs_review", "seafood"],
            )

            initialize_database(database_path)
            save_recipe(recipe, 888, database_path)
            update_recipe_status(888, "favorite", database_path)

            self.assertTrue(set_recipe_tags(888, ["seafood", "dinner"], database_path))

            stored_tags = set(get_recipe_tags(888, database_path))
            self.assertEqual(stored_tags, {"favorite", "seafood", "dinner"})

            # Removing "seafood" from the manual selection should actually remove it.
            set_recipe_tags(888, ["dinner"], database_path)
            self.assertEqual(set(get_recipe_tags(888, database_path)), {"favorite", "dinner"})

    def test_set_recipe_tags_returns_false_for_unknown_thread(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)

            self.assertFalse(set_recipe_tags(999, ["dinner"], database_path))
            self.assertEqual(get_recipe_tags(999, database_path), [])

    def test_search_recipes_matches_title_or_ingredients(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            save_recipe(
                Recipe(title="Chicken Soup", ingredients=["chicken broth", "carrots"], source_url="https://x.com/1"),
                1, database_path,
            )
            save_recipe(
                Recipe(title="Beef Chili", ingredients=["ground beef", "50% lean"], source_url="https://x.com/2"),
                2, database_path,
            )
            save_recipe(
                Recipe(title="Salad", ingredients=["lettuce"], source_url="https://x.com/3"),
                3, database_path,
            )

            title_match = search_recipes("chicken", database_path=database_path)
            self.assertEqual([r["title"] for r in title_match], ["Chicken Soup"])

            ingredient_match = search_recipes("carrots", database_path=database_path)
            self.assertEqual([r["title"] for r in ingredient_match], ["Chicken Soup"])

            no_match = search_recipes("pineapple", database_path=database_path)
            self.assertEqual(no_match, [])

    def test_search_recipes_matches_words_split_across_title_and_ingredients(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            save_recipe(
                Recipe(
                    title="Slow Cooker Chicken",
                    ingredients=["4 bone-in thighs", "onion"],
                    source_url="https://x.com/1",
                ),
                1, database_path,
            )
            save_recipe(
                Recipe(
                    title="Weeknight Stir Fry",
                    ingredients=["2 lbs chicken thighs, sliced"],
                    source_url="https://x.com/2",
                ),
                2, database_path,
            )
            save_recipe(
                Recipe(title="Salad", ingredients=["lettuce"], source_url="https://x.com/3"),
                3, database_path,
            )

            results = search_recipes("chicken thighs", database_path=database_path)

            self.assertEqual(
                {r["title"] for r in results},
                {"Slow Cooker Chicken", "Weeknight Stir Fry"},
            )

    def test_search_recipes_requires_every_word_to_match_somewhere(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            save_recipe(
                Recipe(title="Beef Tacos", ingredients=["ground beef"], source_url="https://x.com/1"),
                1, database_path,
            )
            save_recipe(
                Recipe(title="Beef Stew", ingredients=["chuck roast"], source_url="https://x.com/2"),
                2, database_path,
            )

            results = search_recipes("ground beef", database_path=database_path)

            self.assertEqual([r["title"] for r in results], ["Beef Tacos"])

    def test_search_recipes_returns_empty_for_blank_query(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            save_recipe(
                Recipe(title="Salad", ingredients=["lettuce"], source_url="https://x.com/1"),
                1, database_path,
            )

            self.assertEqual(search_recipes("", database_path=database_path), [])
            self.assertEqual(search_recipes("   ", database_path=database_path), [])

    def test_search_recipes_reuses_tag_exclude_guardrails(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            save_recipe(
                Recipe(title="Beef Stir Fry", ingredients=["flank steak", "soy sauce"], source_url="https://x.com/1"),
                1, database_path,
            )
            save_recipe(
                Recipe(
                    title="Vegetable Soup",
                    ingredients=["beef broth", "carrots", "celery"],
                    source_url="https://x.com/2",
                ),
                2, database_path,
            )

            results = search_recipes("beef", database_path=database_path)

            # A recipe whose only "beef" text is "beef broth" shouldn't match,
            # same guardrail used when auto-tagging a recipe as "beef".
            self.assertEqual([r["title"] for r in results], ["Beef Stir Fry"])

    def test_search_recipes_picks_up_tag_synonyms(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            save_recipe(
                Recipe(title="Ribeye Steak Dinner", ingredients=["ribeye", "butter"], source_url="https://x.com/1"),
                1, database_path,
            )
            save_recipe(
                Recipe(title="Salad", ingredients=["lettuce"], source_url="https://x.com/2"),
                2, database_path,
            )

            # "ribeye" is one of the "beef" tag's include synonyms, so a search
            # for "beef" should find it even though the word never appears.
            results = search_recipes("beef", database_path=database_path)

            self.assertEqual([r["title"] for r in results], ["Ribeye Steak Dinner"])

    def test_search_recipes_treats_percent_sign_literally(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            save_recipe(
                Recipe(title="Beef Chili", ingredients=["ground beef", "50% lean"], source_url="https://x.com/1"),
                1, database_path,
            )
            save_recipe(
                Recipe(title="Salad", ingredients=["lettuce"], source_url="https://x.com/2"),
                2, database_path,
            )

            # A literal "%" in the query should not act as a wildcard matching everything.
            results = search_recipes("50%", database_path=database_path)
            self.assertEqual([r["title"] for r in results], ["Beef Chili"])

    def test_search_recipes_respects_limit(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            for i in range(5):
                save_recipe(
                    Recipe(title=f"Pasta {i}", ingredients=["pasta"], source_url=f"https://x.com/{i}"),
                    i, database_path,
                )

            results = search_recipes("pasta", limit=3, database_path=database_path)
            self.assertEqual(len(results), 3)

    def test_search_recipe_titles_matches_substring_case_insensitively(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            save_recipe(
                Recipe(title="Chicken Soup", ingredients=["chicken"], source_url="https://x.com/1"),
                1, database_path,
            )
            save_recipe(
                Recipe(title="Beef Chili", ingredients=["beef"], source_url="https://x.com/2"),
                2, database_path,
            )

            self.assertEqual(
                search_recipe_titles("chick", database_path=database_path), ["Chicken Soup"]
            )
            self.assertEqual(
                search_recipe_titles("CHILI", database_path=database_path), ["Beef Chili"]
            )
            self.assertEqual(search_recipe_titles("pineapple", database_path=database_path), [])

    def test_search_recipe_titles_respects_limit(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            for i in range(5):
                save_recipe(
                    Recipe(title=f"Pasta {i}", ingredients=["pasta"], source_url=f"https://x.com/{i}"),
                    i, database_path,
                )

            results = search_recipe_titles("pasta", limit=3, database_path=database_path)
            self.assertEqual(len(results), 3)


class ChoreDatabaseTests(unittest.TestCase):
    def test_initialize_database_seeds_default_chores(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)

            names = get_chore_names(database_path)

            self.assertIn("Mop", names)
            self.assertIn("Wash bed sheets", names)
            self.assertEqual(len(names), len(set(names)))

    def test_seeding_never_overwrites_existing_progress(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            mark_chore_done("Mop", "Peyton", datetime(2026, 1, 1, tzinfo=timezone.utc), database_path)

            # Re-running initialize_database (as happens on every bot start)
            # must not reset a chore that's already been logged.
            initialize_database(database_path)

            chores = {c["name"]: c for c in get_all_chores(database_path)}
            self.assertEqual(chores["Mop"]["last_done_by"], "Peyton")

    def test_mark_chore_done_updates_history_and_clears_pending_nudge(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            mark_nudge_sent("Mop", datetime(2026, 1, 1, tzinfo=timezone.utc), database_path)

            done_at = datetime(2026, 1, 15, tzinfo=timezone.utc)
            updated = mark_chore_done("mop", "Husband", done_at, database_path)

            self.assertEqual(updated["name"], "Mop")
            self.assertEqual(updated["last_done_by"], "Husband")
            self.assertEqual(updated["last_done_at"], done_at.isoformat())
            self.assertIsNone(updated["nudge_sent_at"])

    def test_mark_chore_done_returns_none_for_unknown_chore(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)

            result = mark_chore_done(
                "Not A Real Chore", "Peyton", datetime.now(timezone.utc), database_path
            )

            self.assertIsNone(result)

    def test_mark_nudge_sent_stamps_the_chore(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            sent_at = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)

            mark_nudge_sent("Mop", sent_at, database_path)

            chores = {c["name"]: c for c in get_all_chores(database_path)}
            self.assertEqual(chores["Mop"]["nudge_sent_at"], sent_at.isoformat())


class ChoreLogTests(unittest.TestCase):
    def test_mark_chore_done_logs_an_entry(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            done_at = datetime(2026, 1, 15, tzinfo=timezone.utc)

            mark_chore_done("Mop", "Peyton", done_at, database_path)

            entries = get_chore_log_entries("Mop", database_path)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["done_at"], done_at.isoformat())
            self.assertEqual(entries[0]["done_by"], "Peyton")

    def test_multiple_completions_all_logged_oldest_first(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            mark_chore_done("Mop", "Peyton", datetime(2026, 1, 1, tzinfo=timezone.utc), database_path)
            mark_chore_done("Mop", "Husband", datetime(2026, 1, 15, tzinfo=timezone.utc), database_path)

            entries = get_chore_log_entries("Mop", database_path)

            self.assertEqual([e["done_by"] for e in entries], ["Peyton", "Husband"])

    def test_backdated_entry_out_of_order_still_resolves_current_state_correctly(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            # Log the more recent completion first, then backfill an older one.
            mark_chore_done("Mop", "Peyton", datetime(2026, 1, 15, tzinfo=timezone.utc), database_path)
            mark_chore_done("Mop", "Husband", datetime(2026, 1, 1, tzinfo=timezone.utc), database_path)

            chores = {c["name"]: c for c in get_all_chores(database_path)}
            # Current state should reflect the chronologically latest
            # completion (Jan 15, Peyton), not whichever was logged last.
            self.assertEqual(chores["Mop"]["last_done_by"], "Peyton")
            self.assertEqual(chores["Mop"]["last_done_at"], datetime(2026, 1, 15, tzinfo=timezone.utc).isoformat())

    def test_get_chore_log_entries_empty_for_unknown_chore(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)

            self.assertEqual(get_chore_log_entries("Not A Chore", database_path), [])

    def test_get_chore_completions_by_person_aggregates_across_all_chores(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            mark_chore_done("Mop", "Peyton", datetime(2026, 1, 1, tzinfo=timezone.utc), database_path)
            mark_chore_done("Vacuum couch", "Peyton", datetime(2026, 1, 2, tzinfo=timezone.utc), database_path)
            mark_chore_done("Wash bed sheets", "Husband", datetime(2026, 1, 3, tzinfo=timezone.utc), database_path)

            counts = {row["done_by"]: row["entry_count"] for row in get_chore_completions_by_person(database_path)}

            self.assertEqual(counts, {"Peyton": 2, "Husband": 1})


class GetChoreCompletionsBetweenTests(unittest.TestCase):
    def test_returns_completions_within_range_across_chores(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            mark_chore_done("Mop", "Peyton", datetime(2026, 1, 10, tzinfo=timezone.utc), database_path)
            mark_chore_done("Vacuum couch", "Husband", datetime(2026, 1, 12, tzinfo=timezone.utc), database_path)

            entries = get_chore_completions_between(
                datetime(2026, 1, 1, tzinfo=timezone.utc),
                datetime(2026, 1, 20, tzinfo=timezone.utc),
                database_path,
            )

            self.assertEqual(len(entries), 2)
            self.assertEqual([e["chore_name"] for e in entries], ["Mop", "Vacuum couch"])
            self.assertEqual(entries[0]["done_by"], "Peyton")

    def test_excludes_completions_outside_range(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            mark_chore_done("Mop", "Peyton", datetime(2025, 12, 1, tzinfo=timezone.utc), database_path)

            entries = get_chore_completions_between(
                datetime(2026, 1, 1, tzinfo=timezone.utc),
                datetime(2026, 1, 20, tzinfo=timezone.utc),
                database_path,
            )

            self.assertEqual(entries, [])

    def test_end_is_exclusive(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            boundary = datetime(2026, 1, 20, tzinfo=timezone.utc)
            mark_chore_done("Mop", "Peyton", boundary, database_path)

            entries = get_chore_completions_between(
                datetime(2026, 1, 1, tzinfo=timezone.utc), boundary, database_path
            )

            self.assertEqual(entries, [])

    def test_empty_when_nothing_logged(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)

            entries = get_chore_completions_between(
                datetime(2026, 1, 1, tzinfo=timezone.utc),
                datetime(2026, 1, 20, tzinfo=timezone.utc),
                database_path,
            )

            self.assertEqual(entries, [])


class UndoLastDoneTests(unittest.TestCase):
    def test_removes_the_most_recently_logged_entry(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            mark_chore_done("Mop", "Peyton", datetime(2026, 1, 1, tzinfo=timezone.utc), database_path)
            mark_chore_done("Mop", "Husband", datetime(2026, 1, 15, tzinfo=timezone.utc), database_path)

            result = undo_last_done("Mop", database_path)

            self.assertEqual(result["removed"]["done_by"], "Husband")
            entries = get_chore_log_entries("Mop", database_path)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["done_by"], "Peyton")

    def test_reverts_current_state_to_the_remaining_entry(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            mark_chore_done("Mop", "Peyton", datetime(2026, 1, 1, tzinfo=timezone.utc), database_path)
            mark_chore_done("Mop", "Husband", datetime(2026, 1, 15, tzinfo=timezone.utc), database_path)

            result = undo_last_done("Mop", database_path)

            self.assertEqual(result["chore"]["last_done_by"], "Peyton")
            self.assertEqual(result["chore"]["last_done_at"], datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat())

    def test_undoing_the_only_entry_clears_current_state(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            mark_chore_done("Mop", "Peyton", datetime(2026, 1, 1, tzinfo=timezone.utc), database_path)

            result = undo_last_done("Mop", database_path)

            self.assertIsNone(result["chore"]["last_done_at"])
            self.assertIsNone(result["chore"]["last_done_by"])

    def test_returns_none_when_chore_has_no_history(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)

            self.assertIsNone(undo_last_done("Mop", database_path))

    def test_returns_none_for_unknown_chore(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)

            self.assertIsNone(undo_last_done("Not A Chore", database_path))


class BotStateTests(unittest.TestCase):
    def test_returns_none_for_unset_key(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)

            self.assertIsNone(get_state("this_week_message_id", database_path))

    def test_round_trips_a_value(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)

            set_state("this_week_message_id", "12345", database_path)

            self.assertEqual(get_state("this_week_message_id", database_path), "12345")

    def test_setting_again_overwrites_the_previous_value(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)

            set_state("this_week_message_id", "111", database_path)
            set_state("this_week_message_id", "222", database_path)

            self.assertEqual(get_state("this_week_message_id", database_path), "222")

    def test_get_recipe_by_title_finds_exact_case_insensitive_match(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            save_recipe(
                Recipe(title="Chicken Soup", ingredients=["chicken", "broth"], source_url="https://x.com/1"),
                1, database_path,
            )

            found = get_recipe_by_title("chicken soup", database_path=database_path)
            self.assertEqual(found["title"], "Chicken Soup")
            self.assertEqual(found["ingredients"], ["chicken", "broth"])

            self.assertIsNone(get_recipe_by_title("Chicken Sou", database_path=database_path))


class BookedTaskTests(unittest.TestCase):
    def test_round_trips_a_booked_task(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            booked_at = datetime(2026, 8, 10, tzinfo=timezone.utc)

            record_booked_task(
                111, 222, "call vet", "event-abc", "fam@example.com", booked_at, "Peyton", database_path
            )

            task = get_booked_task(111, database_path)
            self.assertEqual(task["task_name"], "call vet")
            self.assertEqual(task["event_id"], "event-abc")
            self.assertEqual(task["calendar_id"], "fam@example.com")
            self.assertEqual(task["booked_by"], "Peyton")
            self.assertIsNone(task["completed_at"])
            self.assertIsNone(task["completed_by"])

    def test_returns_none_for_unknown_message(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)

            self.assertIsNone(get_booked_task(999, database_path))

    def test_mark_task_completed_sets_completion_fields(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            booked_at = datetime(2026, 8, 10, tzinfo=timezone.utc)
            record_booked_task(
                111, 222, "call vet", "event-abc", "fam@example.com", booked_at, "Peyton", database_path
            )
            completed_at = datetime(2026, 8, 11, tzinfo=timezone.utc)

            result = mark_task_completed(111, completed_at, "Joe", database_path)

            self.assertEqual(result["completed_by"], "Joe")
            self.assertEqual(result["completed_at"], completed_at.isoformat())

    def test_mark_task_completed_returns_none_for_unknown_message(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)

            self.assertIsNone(mark_task_completed(999, datetime.now(timezone.utc), "Joe", database_path))

    def test_mark_task_completed_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            booked_at = datetime(2026, 8, 10, tzinfo=timezone.utc)
            record_booked_task(
                111, 222, "call vet", "event-abc", "fam@example.com", booked_at, "Peyton", database_path
            )
            mark_task_completed(111, datetime(2026, 8, 11, tzinfo=timezone.utc), "Joe", database_path)

            # A second reaction shouldn't overwrite who/when it was first completed.
            second = mark_task_completed(111, datetime(2026, 8, 12, tzinfo=timezone.utc), "Peyton", database_path)

            self.assertIsNone(second)
            task = get_booked_task(111, database_path)
            self.assertEqual(task["completed_by"], "Joe")

    def test_delete_booked_task_removes_it(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            booked_at = datetime(2026, 8, 10, tzinfo=timezone.utc)
            record_booked_task(
                111, 222, "call vet", "event-abc", "fam@example.com", booked_at, "Peyton", database_path
            )

            delete_booked_task(111, database_path)

            self.assertIsNone(get_booked_task(111, database_path))

    def test_delete_booked_task_is_a_no_op_for_unknown_message(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)

            delete_booked_task(999, database_path)  # should not raise


class GetCompletedTasksBetweenTests(unittest.TestCase):
    def test_returns_only_tasks_completed_in_range(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            booked_at = datetime(2026, 8, 1, tzinfo=timezone.utc)
            record_booked_task(
                111, 222, "call vet", "event-1", "fam@example.com", booked_at, "Peyton", database_path
            )
            record_booked_task(
                333, 222, "buy dog food", "event-2", "fam@example.com", booked_at, "Joe", database_path
            )
            mark_task_completed(111, datetime(2026, 8, 10, tzinfo=timezone.utc), "Peyton", database_path)
            mark_task_completed(333, datetime(2026, 8, 20, tzinfo=timezone.utc), "Joe", database_path)

            results = get_completed_tasks_between(
                datetime(2026, 8, 5, tzinfo=timezone.utc),
                datetime(2026, 8, 15, tzinfo=timezone.utc),
                database_path,
            )

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["task_name"], "call vet")
            self.assertEqual(results[0]["completed_by"], "Peyton")

    def test_excludes_uncompleted_tasks(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            booked_at = datetime(2026, 8, 1, tzinfo=timezone.utc)
            record_booked_task(
                111, 222, "call vet", "event-1", "fam@example.com", booked_at, "Peyton", database_path
            )

            results = get_completed_tasks_between(
                datetime(2026, 7, 1, tzinfo=timezone.utc),
                datetime(2026, 9, 1, tzinfo=timezone.utc),
                database_path,
            )

            self.assertEqual(results, [])


class WishlistItemTests(unittest.TestCase):
    def test_round_trips_a_wishlist_item(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            added_at = datetime(2026, 8, 10, tzinfo=timezone.utc)

            record_wishlist_item(
                111,
                222,
                "Dish Drying Rack",
                "https://example.com/item",
                "https://example.com/pic.jpg",
                "24.99",
                "Peyton",
                added_at,
                database_path,
            )

            item = get_wishlist_item(111, database_path)
            self.assertEqual(item["title"], "Dish Drying Rack")
            self.assertEqual(item["url"], "https://example.com/item")
            self.assertEqual(item["image_url"], "https://example.com/pic.jpg")
            self.assertEqual(item["price"], "24.99")
            self.assertEqual(item["added_by"], "Peyton")
            self.assertIsNone(item["bought_at"])
            self.assertIsNone(item["bought_by"])

    def test_returns_none_for_unknown_message(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)

            self.assertIsNone(get_wishlist_item(999, database_path))

    def test_mark_wishlist_item_bought_sets_completion_fields(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            added_at = datetime(2026, 8, 10, tzinfo=timezone.utc)
            record_wishlist_item(
                111, 222, "Dish Drying Rack", "https://example.com/item", None, None, "Peyton", added_at, database_path
            )
            bought_at = datetime(2026, 8, 11, tzinfo=timezone.utc)

            result = mark_wishlist_item_bought(111, bought_at, "Joe", database_path)

            self.assertEqual(result["bought_by"], "Joe")
            self.assertEqual(result["bought_at"], bought_at.isoformat())

    def test_mark_wishlist_item_bought_returns_none_for_unknown_message(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)

            self.assertIsNone(mark_wishlist_item_bought(999, datetime.now(timezone.utc), "Joe", database_path))

    def test_mark_wishlist_item_bought_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            added_at = datetime(2026, 8, 10, tzinfo=timezone.utc)
            record_wishlist_item(
                111, 222, "Dish Drying Rack", "https://example.com/item", None, None, "Peyton", added_at, database_path
            )
            mark_wishlist_item_bought(111, datetime(2026, 8, 11, tzinfo=timezone.utc), "Joe", database_path)

            second = mark_wishlist_item_bought(111, datetime(2026, 8, 12, tzinfo=timezone.utc), "Peyton", database_path)

            self.assertIsNone(second)
            item = get_wishlist_item(111, database_path)
            self.assertEqual(item["bought_by"], "Joe")

    def test_get_open_wishlist_items_excludes_bought_items(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            added_at = datetime(2026, 8, 10, tzinfo=timezone.utc)
            record_wishlist_item(
                111, 222, "Dish Drying Rack", "https://example.com/1", None, None, "Peyton", added_at, database_path
            )
            record_wishlist_item(
                222, 222, "Sheets", "https://example.com/2", None, None, "Joe", added_at, database_path
            )
            mark_wishlist_item_bought(111, datetime(2026, 8, 11, tzinfo=timezone.utc), "Joe", database_path)

            open_items = get_open_wishlist_items(database_path)

            self.assertEqual(len(open_items), 1)
            self.assertEqual(open_items[0]["title"], "Sheets")

    def test_get_open_wishlist_items_ordered_oldest_first(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            record_wishlist_item(
                111, 222, "Second", "https://example.com/2",
                None, None, "Peyton", datetime(2026, 8, 11, tzinfo=timezone.utc), database_path,
            )
            record_wishlist_item(
                222, 222, "First", "https://example.com/1",
                None, None, "Joe", datetime(2026, 8, 10, tzinfo=timezone.utc), database_path,
            )

            open_items = get_open_wishlist_items(database_path)

            self.assertEqual([item["title"] for item in open_items], ["First", "Second"])


class MealPlanItemTests(unittest.TestCase):
    def test_round_trips_a_meal_plan_item(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            week_start = date(2026, 8, 10)
            added_at = datetime(2026, 8, 10, tzinfo=timezone.utc)

            add_meal_plan_item(week_start, "dinner", "Tacos", "Peyton", added_at, database_path)

            items = get_meal_plan_items(week_start, database_path)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["meal_type"], "dinner")
            self.assertEqual(items[0]["recipe_title"], "Tacos")
            self.assertEqual(items[0]["added_by"], "Peyton")

    def test_only_returns_items_for_the_given_week(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            added_at = datetime(2026, 8, 10, tzinfo=timezone.utc)

            add_meal_plan_item(date(2026, 8, 10), "dinner", "Tacos", "Peyton", added_at, database_path)
            add_meal_plan_item(date(2026, 8, 17), "dinner", "Pizza", "Joe", added_at, database_path)

            items = get_meal_plan_items(date(2026, 8, 10), database_path)

            self.assertEqual([item["recipe_title"] for item in items], ["Tacos"])

    def test_no_items_for_a_week_with_nothing_planned(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)

            self.assertEqual(get_meal_plan_items(date(2026, 8, 10), database_path), [])

    def test_clear_meal_plan_removes_items_for_the_week_and_returns_count(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)
            added_at = datetime(2026, 8, 10, tzinfo=timezone.utc)
            add_meal_plan_item(date(2026, 8, 10), "dinner", "Tacos", "Peyton", added_at, database_path)
            add_meal_plan_item(date(2026, 8, 10), "breakfast", "Pancakes", "Joe", added_at, database_path)
            add_meal_plan_item(date(2026, 8, 17), "dinner", "Pizza", "Joe", added_at, database_path)

            removed = clear_meal_plan(date(2026, 8, 10), database_path)

            self.assertEqual(removed, 2)
            self.assertEqual(get_meal_plan_items(date(2026, 8, 10), database_path), [])
            self.assertEqual(len(get_meal_plan_items(date(2026, 8, 17), database_path)), 1)

    def test_clear_meal_plan_returns_zero_when_nothing_to_clear(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "recipes.db"
            initialize_database(database_path)

            self.assertEqual(clear_meal_plan(date(2026, 8, 10), database_path), 0)
