import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from services.backup import backup_database, prune_old_backups


class BackupDatabaseTests(unittest.TestCase):
    def test_copies_the_database_with_a_timestamped_name(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source_path = Path(temporary_directory) / "rosies_recipe_box.db"
            source_path.write_text("fake db contents")
            backup_dir = Path(temporary_directory) / "backups"
            now = datetime(2026, 8, 10, 15, 30, 0)

            backup_path = backup_database(source_path, backup_dir, now)

            self.assertEqual(backup_path.name, "rosies_recipe_box_20260810_153000.db")
            self.assertEqual(backup_path.read_text(), "fake db contents")

    def test_creates_the_backup_directory_if_missing(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source_path = Path(temporary_directory) / "rosies_recipe_box.db"
            source_path.write_text("fake db contents")
            backup_dir = Path(temporary_directory) / "nested" / "backups"

            backup_path = backup_database(source_path, backup_dir, datetime(2026, 8, 10))

            self.assertTrue(backup_path.exists())

    def test_raises_when_source_database_does_not_exist(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source_path = Path(temporary_directory) / "missing.db"
            backup_dir = Path(temporary_directory) / "backups"

            with self.assertRaises(FileNotFoundError):
                backup_database(source_path, backup_dir, datetime(2026, 8, 10))


class PruneOldBackupsTests(unittest.TestCase):
    def test_keeps_only_the_most_recent_n_backups(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            backup_dir = Path(temporary_directory)
            names = [f"rosies_recipe_box_2026081{i}_000000.db" for i in range(5)]
            for name in names:
                (backup_dir / name).write_text("x")

            removed = prune_old_backups(backup_dir, keep=2)

            remaining = sorted(p.name for p in backup_dir.glob("*.db"))
            self.assertEqual(remaining, names[-2:])
            self.assertEqual(len(removed), 3)

    def test_does_nothing_when_under_the_keep_limit(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            backup_dir = Path(temporary_directory)
            (backup_dir / "rosies_recipe_box_20260810_000000.db").write_text("x")

            removed = prune_old_backups(backup_dir, keep=14)

            self.assertEqual(removed, [])
            self.assertEqual(len(list(backup_dir.glob("*.db"))), 1)

    def test_returns_empty_list_when_backup_dir_does_not_exist(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            backup_dir = Path(temporary_directory) / "does-not-exist"

            self.assertEqual(prune_old_backups(backup_dir, keep=14), [])


if __name__ == "__main__":
    unittest.main()
