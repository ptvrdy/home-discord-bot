import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from services.pantry_status import (
    FAIL,
    OFF,
    OK,
    WARN,
    Check,
    age_label,
    backup_check,
    build_status_embed,
    overall_status,
    parse_time,
)

NOW = datetime(2026, 10, 8, 12, 0)


class AgeLabelTests(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(age_label(None, NOW), "never")
        self.assertEqual(age_label(NOW - timedelta(seconds=30), NOW), "just now")
        self.assertEqual(age_label(NOW - timedelta(minutes=12), NOW), "12 min ago")
        self.assertEqual(age_label(NOW - timedelta(hours=5), NOW), "5 hours ago")
        self.assertEqual(age_label(NOW - timedelta(days=3), NOW), "3 days ago")

    def test_parse_time_drops_the_timezone_and_tolerates_junk(self):
        self.assertEqual(parse_time("2026-10-08T11:00:00-04:00"), datetime(2026, 10, 8, 11, 0))
        self.assertIsNone(parse_time(None))
        self.assertIsNone(parse_time("yesterday-ish"))


class BackupCheckTests(unittest.TestCase):
    def test_fresh_stale_and_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            self.assertEqual(backup_check("Grocy's backups", folder, "grocy_*", NOW).detail, "no backups yet")

            backup = folder / "grocy_20261008_033000"
            backup.mkdir()
            fresh = datetime.now() - timedelta(hours=8)
            os.utime(backup, (time.time(), fresh.timestamp()))
            check = backup_check("Grocy's backups", folder, "grocy_*", datetime.now())
            self.assertEqual((check.status, check.detail), (OK, "newest 8 hours ago"))

            old = datetime.now() - timedelta(days=3)
            os.utime(backup, (time.time(), old.timestamp()))
            self.assertEqual(backup_check("Grocy's backups", folder, "grocy_*", datetime.now()).status, WARN)

        missing = backup_check("Grocy's backups", Path(directory) / "nope", "grocy_*", NOW)
        self.assertEqual(missing.status, WARN)
        self.assertIn("no backup folder", missing.detail)


class EmbedTests(unittest.TestCase):
    def test_worst_status_wins(self):
        self.assertEqual(overall_status([Check("a", OK, ""), Check("b", OFF, "")]), OK)
        self.assertEqual(overall_status([Check("a", OK, ""), Check("b", WARN, "")]), WARN)
        self.assertEqual(overall_status([Check("a", WARN, ""), Check("b", FAIL, "")]), FAIL)

    def test_embed(self):
        embed = build_status_embed(
            [Check("Grocy", OK, "version 4.7.1"), Check("Channels", WARN, "not set: #pantry")],
            "11 products · 9 in stock",
        )
        self.assertIn("mostly working", embed.title)
        self.assertEqual(embed.description, "✅ **Grocy** — version 4.7.1\n⚠️ **Channels** — not set: #pantry")
        self.assertEqual(embed.fields[0].value, "11 products · 9 in stock")


class PluginCheckTests(unittest.IsolatedAsyncioTestCase):
    CATALOG = [{"sku": "083372", "name": "Garlic Butter Nut Mix", "category": "Snacks & Sweets"}]

    def _grocy(self, plugin="TraderJoesBarcodeLookupPlugin", groups=("Snacks & Sweets",), lookup=None):
        grocy = MagicMock()
        grocy.system_config = AsyncMock(return_value={"STOCK_BARCODE_LOOKUP_PLUGIN": plugin})
        grocy.get_objects = AsyncMock(return_value=[{"name": name} for name in groups])
        grocy.external_barcode_lookup = AsyncMock(return_value=lookup)
        return grocy

    async def run_check(self, grocy):
        from commands.pantry_commands import Pantry

        with patch("commands.pantry_commands.get_tj_catalog", return_value=self.CATALOG):
            return await Pantry._plugin_check(MagicMock(), grocy)

    async def test_plugin_reading_rosies_catalog(self):
        grocy = self._grocy(lookup={"name": "Garlic Butter Nut Mix"})
        check = await self.run_check(grocy)
        self.assertEqual(check.status, OK)
        grocy.external_barcode_lookup.assert_awaited_once_with("00833721")

    async def test_plugin_that_cant_see_the_catalog(self):
        check = await self.run_check(self._grocy(lookup={"name": "Some Open Food Facts Name"}))
        self.assertEqual(check.status, WARN)
        self.assertIn("ROSIE_DATA_DIR", check.detail)

    async def test_other_plugin(self):
        check = await self.run_check(self._grocy(plugin="OpenFoodFactsBarcodeLookupPlugin"))
        self.assertEqual(check.status, WARN)

    async def test_no_lookup_until_a_section_exists(self):
        grocy = self._grocy(groups=())
        check = await self.run_check(grocy)
        self.assertEqual(check.status, OK)
        grocy.external_barcode_lookup.assert_not_awaited()  # would create a product group


if __name__ == "__main__":
    unittest.main()
