"""SQLite persistence for Rosie's Recipe Box."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from models.recipe_card import Recipe


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
                notes TEXT,
                next_time TEXT,
                discord_message_id INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )


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
    discord_message_id: int | None = None,
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
                recipe_id, made_at, activity, status, notes, next_time, discord_message_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                recipe_id,
                made_at.isoformat(),
                activity,
                status,
                notes or None,
                next_time or None,
                discord_message_id,
            ),
        )
        return True
