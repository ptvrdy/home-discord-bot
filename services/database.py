"""SQLite persistence for Rosie's Recipe Box."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from config.recipe_keywords import RECIPE_KEYWORDS
from models.recipe_card import Recipe
from services.recipe_tags import matches_keyword


DATABASE_PATH = Path(__file__).resolve().parents[1] / "data" / "rosies_recipe_box.db"


def _connect(database_path: Path = DATABASE_PATH) -> sqlite3.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def _database_connection(database_path: Path = DATABASE_PATH):
    """Commit successful work and always release the SQLite file handle."""
    connection = _connect(database_path)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _ensure_column(connection: sqlite3.Connection, table: str, column: str, column_type: str) -> None:
    """Add a column to an existing table if an earlier version of the schema lacks it."""
    existing_columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in existing_columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


def initialize_database(database_path: Path = DATABASE_PATH) -> None:
    """Create the durable recipe-box tables when they do not yet exist."""
    with _database_connection(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS recipes (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                source_url TEXT NOT NULL,
                source_name TEXT,
                instructions TEXT,
                ingredients_json TEXT NOT NULL,
                prep_time TEXT,
                cook_time TEXT,
                total_time TEXT,
                total_minutes INTEGER,
                yields TEXT,
                image_url TEXT,
                human_status TEXT NOT NULL DEFAULT 'needs_review',
                discord_thread_id INTEGER UNIQUE,
                journal_message_id INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS recipe_tags (
                recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
                tag TEXT NOT NULL,
                PRIMARY KEY (recipe_id, tag)
            );

            CREATE TABLE IF NOT EXISTS cooking_log (
                id INTEGER PRIMARY KEY,
                recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
                made_at TEXT NOT NULL,
                activity TEXT NOT NULL,
                status TEXT NOT NULL,
                rating INTEGER,
                notes TEXT,
                next_time TEXT,
                author_name TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        _ensure_column(connection, "recipes", "journal_message_id", "INTEGER")
        _ensure_column(connection, "cooking_log", "rating", "INTEGER")
        _ensure_column(connection, "cooking_log", "author_name", "TEXT")


def save_recipe(
    recipe: Recipe,
    discord_thread_id: int,
    database_path: Path = DATABASE_PATH,
) -> int:
    """Create or refresh a recipe record and return its database ID."""
    initialize_database(database_path)
    with _database_connection(database_path) as connection:
        connection.execute(
            """
            INSERT INTO recipes (
                title, source_url, source_name, instructions, ingredients_json,
                prep_time, cook_time, total_time, total_minutes, yields, image_url,
                human_status, discord_thread_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(discord_thread_id) DO UPDATE SET
                title = excluded.title,
                source_name = excluded.source_name,
                instructions = excluded.instructions,
                ingredients_json = excluded.ingredients_json,
                prep_time = excluded.prep_time,
                cook_time = excluded.cook_time,
                total_time = excluded.total_time,
                total_minutes = excluded.total_minutes,
                yields = excluded.yields,
                image_url = excluded.image_url,
                human_status = excluded.human_status,
                discord_thread_id = excluded.discord_thread_id
            """,
            (
                recipe.title,
                recipe.source_url,
                recipe.source_name,
                recipe.instructions,
                json.dumps(recipe.ingredients),
                recipe.prep_time,
                recipe.cook_time,
                recipe.total_time,
                recipe.total_minutes,
                recipe.yields,
                recipe.image_url,
                next((tag for tag in recipe.tags if tag in {
                    "needs_review", "made_before", "make_again", "favorite",
                }), "needs_review"),
                discord_thread_id,
            ),
        )
        recipe_id = connection.execute(
            "SELECT id FROM recipes WHERE discord_thread_id = ?",
            (discord_thread_id,),
        ).fetchone()[0]
        connection.execute("DELETE FROM recipe_tags WHERE recipe_id = ?", (recipe_id,))
        connection.executemany(
            "INSERT INTO recipe_tags (recipe_id, tag) VALUES (?, ?)",
            [(recipe_id, tag) for tag in dict.fromkeys(recipe.tags)],
        )
        return recipe_id


def _set_human_status(connection: sqlite3.Connection, recipe_id: int, status: str) -> None:
    connection.execute(
        "UPDATE recipes SET human_status = ? WHERE id = ?",
        (status, recipe_id),
    )
    connection.execute(
        "DELETE FROM recipe_tags WHERE recipe_id = ? AND tag IN (?, ?, ?, ?)",
        (recipe_id, "needs_review", "made_before", "make_again", "favorite"),
    )
    connection.execute(
        "INSERT OR IGNORE INTO recipe_tags (recipe_id, tag) VALUES (?, ?)",
        (recipe_id, status),
    )


def update_recipe_status(
    discord_thread_id: int,
    status: str,
    database_path: Path = DATABASE_PATH,
) -> bool:
    """Update a recipe status, returning false for threads not yet in the database."""
    initialize_database(database_path)
    with _database_connection(database_path) as connection:
        recipe_row = connection.execute(
            "SELECT id FROM recipes WHERE discord_thread_id = ?",
            (discord_thread_id,),
        ).fetchone()
        if recipe_row is None:
            return False

        _set_human_status(connection, recipe_row[0], status)
        return True


def add_cooking_log(
    discord_thread_id: int,
    made_at: datetime,
    activity: str,
    status: str,
    notes: str | None,
    next_time: str | None,
    rating: int | None,
    author_name: str,
    database_path: Path = DATABASE_PATH,
) -> bool:
    """Store one journal entry, returning false for recipes imported before SQLite."""
    initialize_database(database_path)
    with _database_connection(database_path) as connection:
        recipe_row = connection.execute(
            "SELECT id FROM recipes WHERE discord_thread_id = ?",
            (discord_thread_id,),
        ).fetchone()
        if recipe_row is None:
            return False

        recipe_id = recipe_row[0]
        _set_human_status(connection, recipe_id, status)
        connection.execute(
            """
            INSERT INTO cooking_log (
                recipe_id, made_at, activity, status, notes, next_time, rating, author_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                recipe_id,
                made_at.isoformat(),
                activity,
                status,
                notes or None,
                next_time or None,
                rating,
                author_name,
            ),
        )
        return True


def get_cooking_log_entries(
    discord_thread_id: int,
    database_path: Path = DATABASE_PATH,
) -> list[dict]:
    """Return every journal entry for a recipe, oldest first."""
    initialize_database(database_path)
    with _database_connection(database_path) as connection:
        connection.row_factory = sqlite3.Row
        recipe_row = connection.execute(
            "SELECT id FROM recipes WHERE discord_thread_id = ?",
            (discord_thread_id,),
        ).fetchone()
        if recipe_row is None:
            return []

        rows = connection.execute(
            """
            SELECT made_at, activity, status, rating, notes, next_time, author_name
            FROM cooking_log
            WHERE recipe_id = ?
            ORDER BY made_at ASC
            """,
            (recipe_row["id"],),
        ).fetchall()
        return [dict(row) for row in rows]


def get_journal_message_id(
    discord_thread_id: int,
    database_path: Path = DATABASE_PATH,
) -> int | None:
    """Return the Discord message ID of a recipe's persistent journal message, if any."""
    initialize_database(database_path)
    with _database_connection(database_path) as connection:
        row = connection.execute(
            "SELECT journal_message_id FROM recipes WHERE discord_thread_id = ?",
            (discord_thread_id,),
        ).fetchone()
        return row[0] if row else None


def set_journal_message_id(
    discord_thread_id: int,
    journal_message_id: int,
    database_path: Path = DATABASE_PATH,
) -> None:
    """Remember which message holds a recipe's journal so future reviews can edit it."""
    initialize_database(database_path)
    with _database_connection(database_path) as connection:
        connection.execute(
            "UPDATE recipes SET journal_message_id = ? WHERE discord_thread_id = ?",
            (journal_message_id, discord_thread_id),
        )


def get_recipe_by_thread(
    discord_thread_id: int,
    database_path: Path = DATABASE_PATH,
) -> dict | None:
    """Return a recipe's full stored fields, keyed for rebuilding a Recipe object."""
    initialize_database(database_path)
    with _database_connection(database_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT * FROM recipes WHERE discord_thread_id = ?",
            (discord_thread_id,),
        ).fetchone()
        if row is None:
            return None

        data = dict(row)
        data["ingredients"] = json.loads(data.pop("ingredients_json"))
        return data


def get_random_recipe(
    tag: str | None = None,
    database_path: Path = DATABASE_PATH,
) -> dict | None:
    """Return a random recipe's title and thread ID, optionally filtered by tag."""
    initialize_database(database_path)
    with _database_connection(database_path) as connection:
        connection.row_factory = sqlite3.Row
        if tag:
            row = connection.execute(
                """
                SELECT r.title, r.discord_thread_id
                FROM recipes r
                JOIN recipe_tags rt ON rt.recipe_id = r.id
                WHERE rt.tag = ?
                ORDER BY RANDOM()
                LIMIT 1
                """,
                (tag,),
            ).fetchone()
        else:
            row = connection.execute(
                "SELECT title, discord_thread_id FROM recipes ORDER BY RANDOM() LIMIT 1"
            ).fetchone()
        return dict(row) if row else None


def get_recipe_by_url(
    source_url: str,
    database_path: Path = DATABASE_PATH,
) -> dict | None:
    """Return a recipe's title and thread ID if this exact URL was already imported."""
    initialize_database(database_path)
    with _database_connection(database_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT title, discord_thread_id FROM recipes WHERE source_url = ?",
            (source_url,),
        ).fetchone()
        return dict(row) if row else None


def get_recipes_needing_review(
    limit: int = 25,
    database_path: Path = DATABASE_PATH,
) -> list[dict]:
    """Return recipes still marked needs_review, oldest first."""
    initialize_database(database_path)
    with _database_connection(database_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT title, discord_thread_id
            FROM recipes
            WHERE human_status = 'needs_review'
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_recipe_tags(
    discord_thread_id: int,
    database_path: Path = DATABASE_PATH,
) -> list[str]:
    """Return every tag (human status included) currently stored for a recipe."""
    initialize_database(database_path)
    with _database_connection(database_path) as connection:
        recipe_row = connection.execute(
            "SELECT id FROM recipes WHERE discord_thread_id = ?",
            (discord_thread_id,),
        ).fetchone()
        if recipe_row is None:
            return []

        rows = connection.execute(
            "SELECT tag FROM recipe_tags WHERE recipe_id = ?",
            (recipe_row[0],),
        ).fetchall()
        return [row[0] for row in rows]


def set_recipe_tags(
    discord_thread_id: int,
    tags: list[str],
    database_path: Path = DATABASE_PATH,
) -> bool:
    """Replace a recipe's non-human tags with exactly this set, leaving its
    human status tag (set via /review) untouched. Returns false for recipes
    not yet in the database."""
    initialize_database(database_path)
    with _database_connection(database_path) as connection:
        recipe_row = connection.execute(
            "SELECT id FROM recipes WHERE discord_thread_id = ?",
            (discord_thread_id,),
        ).fetchone()
        if recipe_row is None:
            return False

        recipe_id = recipe_row[0]
        connection.execute(
            "DELETE FROM recipe_tags WHERE recipe_id = ? AND tag NOT IN (?, ?, ?, ?)",
            (recipe_id, "needs_review", "made_before", "make_again", "favorite"),
        )
        connection.executemany(
            "INSERT OR IGNORE INTO recipe_tags (recipe_id, tag) VALUES (?, ?)",
            [(recipe_id, tag) for tag in dict.fromkeys(tags)],
        )
        return True


def _word_matches(text: str, word: str) -> bool:
    """If the word is a known recipe tag (e.g. "beef"), reuse the exact same
    include/exclude guardrails used for auto-tagging, so a search for "beef"
    doesn't match a recipe whose only beef-related text is "beef broth" - and
    also picks up synonyms like "ribeye" or "brisket" for free. Otherwise,
    fall back to a plain substring check."""
    if word in RECIPE_KEYWORDS:
        return matches_keyword(text, word)
    return word in text


def search_recipes(
    query: str,
    limit: int = 10,
    database_path: Path = DATABASE_PATH,
) -> list[dict]:
    """Find recipes where every word in the query matches somewhere in the
    title or ingredients - not necessarily together, and not necessarily in
    the same field, so "chicken thighs" matches a recipe titled "Slow Cooker
    Chicken" whose ingredients just say "thighs"."""
    initialize_database(database_path)
    words = [word.lower() for word in query.split()]
    if not words:
        return []

    with _database_connection(database_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT title, discord_thread_id, ingredients_json FROM recipes ORDER BY title"
        ).fetchall()

    matches = []
    for row in rows:
        ingredients_text = " ".join(json.loads(row["ingredients_json"]))
        combined_text = f"{row['title']} {ingredients_text}".lower()

        if all(_word_matches(combined_text, word) for word in words):
            matches.append({"title": row["title"], "discord_thread_id": row["discord_thread_id"]})
        if len(matches) >= limit:
            break

    return matches


def get_cooking_stats(
    top_n: int = 5,
    database_path: Path = DATABASE_PATH,
) -> dict:
    """Aggregate the cooking-log history into household-wide stats: box size,
    review backlog, top-rated and most-cooked recipes, and how many entries
    each person has logged."""
    initialize_database(database_path)
    with _database_connection(database_path) as connection:
        connection.row_factory = sqlite3.Row

        total_recipes = connection.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]
        needs_review_count = connection.execute(
            "SELECT COUNT(*) FROM recipes WHERE human_status = 'needs_review'"
        ).fetchone()[0]

        top_rated = connection.execute(
            """
            SELECT r.title, r.discord_thread_id,
                   AVG(cl.rating) AS avg_rating, COUNT(cl.rating) AS times_rated
            FROM recipes r
            JOIN cooking_log cl ON cl.recipe_id = r.id
            WHERE cl.rating IS NOT NULL
            GROUP BY r.id
            ORDER BY avg_rating DESC, times_rated DESC
            LIMIT ?
            """,
            (top_n,),
        ).fetchall()

        most_cooked = connection.execute(
            """
            SELECT r.title, r.discord_thread_id, COUNT(cl.id) AS times_made
            FROM recipes r
            JOIN cooking_log cl ON cl.recipe_id = r.id
            WHERE cl.activity = 'Made'
            GROUP BY r.id
            ORDER BY times_made DESC
            LIMIT ?
            """,
            (top_n,),
        ).fetchall()

        by_author = connection.execute(
            """
            SELECT author_name, COUNT(*) AS entry_count
            FROM cooking_log
            GROUP BY author_name
            ORDER BY entry_count DESC
            """
        ).fetchall()

        return {
            "total_recipes": total_recipes,
            "needs_review_count": needs_review_count,
            "top_rated": [dict(row) for row in top_rated],
            "most_cooked": [dict(row) for row in most_cooked],
            "by_author": [dict(row) for row in by_author],
        }
