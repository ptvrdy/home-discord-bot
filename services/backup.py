"""Periodic backups of the SQLite database - cheap insurance against losing
everything to a server move, disk failure, or an accidental delete, since
the entire bot's state (recipes, chores, wishlist, meal plan, schedule
bookings) lives in one file."""

import shutil
from datetime import datetime
from pathlib import Path

from services.database import DATABASE_PATH

BACKUP_DIR = DATABASE_PATH.parent / "backups"
BACKUP_RETENTION = 14  # keep the most recent N backups, prune the rest


def backup_database(
    source_path: Path = DATABASE_PATH,
    backup_dir: Path = BACKUP_DIR,
    now: datetime | None = None,
) -> Path:
    """Copy the database file into backup_dir with a timestamped name.
    Returns the path to the new backup."""
    if not source_path.exists():
        raise FileNotFoundError(f"No database found at {source_path}")

    backup_dir.mkdir(parents=True, exist_ok=True)
    now = now or datetime.now()
    backup_path = backup_dir / f"{source_path.stem}_{now.strftime('%Y%m%d_%H%M%S')}{source_path.suffix}"
    shutil.copy2(source_path, backup_path)
    return backup_path


def prune_old_backups(backup_dir: Path = BACKUP_DIR, keep: int = BACKUP_RETENTION) -> list[Path]:
    """Delete all but the `keep` most recent backups - the timestamped
    filename sorts chronologically, so a plain name sort is enough. Returns
    the paths that were removed."""
    if not backup_dir.exists():
        return []

    backups = sorted(backup_dir.glob("*.db"))
    to_remove = backups[:-keep] if keep > 0 else backups
    for path in to_remove:
        path.unlink()
    return to_remove
