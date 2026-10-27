import unittest
from datetime import date, datetime, time, timezone, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from services import timezone as tzmod
from services.timezone import (
    describe_timezone,
    household_timezone,
    timezone_name,
    timezone_warning,
)

NY = ZoneInfo("America/New_York")


class HouseholdTimezoneTests(unittest.TestCase):
    def setUp(self):
        tzmod.clear_cache()
        self.addCleanup(tzmod.clear_cache)

    def test_defaults_to_new_york(self):
        with patch.dict("os.environ", {}, clear=True):
            tz = household_timezone()
        self.assertEqual(timezone_name(tz), "America/New_York")
        self.assertIsNone(timezone_warning())

    def test_env_var_overrides_the_default(self):
        with patch.dict("os.environ", {"HOUSEHOLD_TIMEZONE": "America/Chicago"}, clear=True):
            self.assertEqual(timezone_name(household_timezone()), "America/Chicago")

    def test_missing_database_falls_back_but_warns_loudly(self):
        with patch.dict("os.environ", {}, clear=True), patch.object(
            tzmod, "ZoneInfo", side_effect=ZoneInfoNotFoundError("no data")
        ), self.assertLogs("services.timezone", level="WARNING") as logs:
            tz = household_timezone()
            warning = timezone_warning()
        self.assertIsNone(timezone_name(tz))  # a fixed offset has no IANA name
        self.assertIn("pip install tzdata", warning)
        self.assertIn("daylight-saving", warning)
        self.assertEqual(len(logs.records), 1)

    def test_warning_is_logged_once_not_once_per_caller(self):
        with patch.dict("os.environ", {}, clear=True), patch.object(
            tzmod, "ZoneInfo", side_effect=ZoneInfoNotFoundError("no data")
        ), self.assertLogs("services.timezone", level="WARNING") as logs:
            for _ in range(5):
                household_timezone()
        self.assertEqual(len(logs.records), 1)

    def test_a_misspelled_zone_name_is_treated_the_same_way(self):
        with patch.dict("os.environ", {"HOUSEHOLD_TIMEZONE": "Not/A_Zone"}, clear=True), self.assertLogs(
            "services.timezone", level="WARNING"
        ):
            tz = household_timezone()
        self.assertIsNone(timezone_name(tz))

    def test_describe_shows_name_abbreviation_and_offset(self):
        summer = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
        winter = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(describe_timezone(NY, now=summer), "America/New_York (EDT, UTC-04:00)")
        self.assertEqual(describe_timezone(NY, now=winter), "America/New_York (EST, UTC-05:00)")

    def test_describe_flags_a_fixed_offset(self):
        fixed = timezone(timedelta(hours=-4), "EDT")
        self.assertIn("no tz database", describe_timezone(fixed, now=datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)))


class DaylightSavingTests(unittest.TestCase):
    """The clocks go back on Sunday Nov 1 2026 at 2:00 AM. With the real zone,
    a wall-clock time keeps meaning the same thing on both sides of the change."""

    def test_9am_means_9am_before_and_after_the_change(self):
        before = datetime.combine(date(2026, 10, 30), time(9, 0), tzinfo=NY)   # Friday, still EDT
        after = datetime.combine(date(2026, 11, 2), time(9, 0), tzinfo=NY)     # Monday, now EST
        self.assertEqual(before.utcoffset(), timedelta(hours=-4))
        self.assertEqual(after.utcoffset(), timedelta(hours=-5))
        self.assertEqual(before.astimezone(timezone.utc).hour, 13)
        self.assertEqual(after.astimezone(timezone.utc).hour, 14)

    def test_a_fixed_offset_gets_it_wrong_after_the_change(self):
        """What the old silent fallback did: freeze today's offset (-04:00)."""
        frozen = timezone(timedelta(hours=-4), "EDT")
        after = datetime.combine(date(2026, 11, 2), time(9, 0), tzinfo=frozen)
        self.assertEqual(after.astimezone(timezone.utc).hour, 13)  # should be 14: an hour early


if __name__ == "__main__":
    unittest.main()
