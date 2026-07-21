import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from models.recipe_card import Recipe
from services.database import (
    add_cooking_log,
    get_cooking_log_entries,
    get_cooking_stats,
    get_journal_message_id,
    get_random_recipe,
    get_recipe_by_thread,
    get_recipe_by_title,
    get_recipe_by_url,
    get_recipe_tags,
    get_recipes_needing_review,
    initialize_database,
    save_recipe,
    search_recipe_titles,
    search_recipes,
    set_journal_message_id,
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
