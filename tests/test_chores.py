import unittest
from datetime import datetime, timedelta, timezone

from services.chores import (
    chore_stats,
    chores_due_soon,
    chores_needing_nudge,
    days_since,
    format_nudge_message,
    is_overdue,
)


NOW = datetime(2026, 7, 21, 9, 0, tzinfo=timezone.utc)


def _chore(**overrides):
    chore = {
        "name": "Mop",
        "threshold_days": 14,
        "last_done_at": None,
        "last_done_by": None,
        "nudge_sent_at": None,
    }
    chore.update(overrides)
    return chore


class DaysSinceTests(unittest.TestCase):
    def test_none_when_never_done(self):
        self.assertIsNone(days_since(None, NOW))

    def test_counts_whole_days(self):
        last_done = (NOW - timedelta(days=5)).isoformat()
        self.assertEqual(days_since(last_done, NOW), 5)


class IsOverdueTests(unittest.TestCase):
    def test_never_done_is_always_overdue(self):
        self.assertTrue(is_overdue(_chore(last_done_at=None), NOW))

    def test_not_overdue_within_threshold(self):
        last_done = (NOW - timedelta(days=5)).isoformat()
        self.assertFalse(is_overdue(_chore(threshold_days=14, last_done_at=last_done), NOW))

    def test_overdue_once_threshold_reached(self):
        last_done = (NOW - timedelta(days=14)).isoformat()
        self.assertTrue(is_overdue(_chore(threshold_days=14, last_done_at=last_done), NOW))

    def test_overdue_past_threshold(self):
        last_done = (NOW - timedelta(days=30)).isoformat()
        self.assertTrue(is_overdue(_chore(threshold_days=14, last_done_at=last_done), NOW))


class ChoresDueSoonTests(unittest.TestCase):
    def test_excludes_chores_already_overdue(self):
        chores = [_chore(name="Mop", threshold_days=14, last_done_at=None)]

        self.assertEqual(chores_due_soon(chores, NOW), [])

    def test_includes_chores_within_the_lookahead_window(self):
        last_done = (NOW - timedelta(days=12)).isoformat()
        chores = [_chore(name="Mop", threshold_days=14, last_done_at=last_done)]

        result = chores_due_soon(chores, NOW, lookahead_days=3)

        self.assertEqual([c["name"] for c in result], ["Mop"])

    def test_excludes_chores_outside_the_lookahead_window(self):
        last_done = (NOW - timedelta(days=5)).isoformat()
        chores = [_chore(name="Mop", threshold_days=14, last_done_at=last_done)]

        self.assertEqual(chores_due_soon(chores, NOW, lookahead_days=3), [])

    def test_excludes_never_done_chores(self):
        # Never-done chores are always overdue already, not "coming up".
        chores = [_chore(name="Clean oven", last_done_at=None)]

        self.assertEqual(chores_due_soon(chores, NOW), [])


class ChoresNeedingNudgeTests(unittest.TestCase):
    def test_excludes_chores_not_yet_overdue(self):
        chores = [_chore(name="Mop", last_done_at=(NOW - timedelta(days=1)).isoformat())]

        self.assertEqual(chores_needing_nudge(chores, NOW), [])

    def test_includes_overdue_chores_never_nudged(self):
        chores = [_chore(name="Mop", last_done_at=None, nudge_sent_at=None)]

        result = chores_needing_nudge(chores, NOW)

        self.assertEqual([c["name"] for c in result], ["Mop"])

    def test_excludes_overdue_chores_already_nudged(self):
        chores = [
            _chore(
                name="Mop",
                last_done_at=None,
                nudge_sent_at=(NOW - timedelta(hours=1)).isoformat(),
            )
        ]

        self.assertEqual(chores_needing_nudge(chores, NOW), [])

    def test_reincludes_a_chore_once_done_resets_its_nudge_flag(self):
        # Simulates /done clearing nudge_sent_at, then the chore going
        # overdue again later - it should re-enter the nudge list.
        chores = [
            _chore(
                name="Mop",
                last_done_at=(NOW - timedelta(days=20)).isoformat(),
                nudge_sent_at=None,
            )
        ]

        result = chores_needing_nudge(chores, NOW)

        self.assertEqual([c["name"] for c in result], ["Mop"])


class FormatNudgeMessageTests(unittest.TestCase):
    def test_mentions_never_done_history(self):
        message = format_nudge_message(_chore(name="Clean oven", last_done_at=None), NOW)

        self.assertIn("Clean oven", message)
        self.assertIn("never been logged", message)

    def test_mentions_who_and_how_long_ago(self):
        last_done = (NOW - timedelta(days=16)).isoformat()
        chore = _chore(name="Mop", last_done_at=last_done, last_done_by="Alex")

        message = format_nudge_message(chore, NOW)

        self.assertIn("Alex", message)
        self.assertIn("16 days ago", message)

    def test_uses_singular_day(self):
        last_done = (NOW - timedelta(days=1)).isoformat()
        chore = _chore(name="Wash bed sheets", threshold_days=1, last_done_at=last_done, last_done_by="Husband")

        message = format_nudge_message(chore, NOW)

        self.assertIn("1 day ago", message)
        self.assertNotIn("1 days ago", message)


class ChoreStatsTests(unittest.TestCase):
    def test_counts_total_overdue_upcoming_and_never_done(self):
        chores = [
            _chore(name="Mop", last_done_at=None),  # never done -> overdue
            _chore(name="Clean oven", threshold_days=14, last_done_at=(NOW - timedelta(days=12)).isoformat()),  # upcoming
            _chore(name="Vacuum", threshold_days=14, last_done_at=(NOW - timedelta(days=1)).isoformat()),  # fine
        ]

        stats = chore_stats(chores, NOW)

        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["overdue_count"], 1)
        self.assertEqual(stats["upcoming_count"], 1)
        self.assertEqual(stats["never_done_count"], 1)

    def test_worst_offender_is_the_most_overdue_chore(self):
        chores = [
            _chore(name="Mop", threshold_days=14, last_done_at=(NOW - timedelta(days=20)).isoformat()),  # 6 days late
            _chore(name="Clean oven", threshold_days=14, last_done_at=(NOW - timedelta(days=30)).isoformat()),  # 16 days late
        ]

        stats = chore_stats(chores, NOW)

        self.assertEqual(stats["worst_offender"]["name"], "Clean oven")
        self.assertEqual(stats["worst_offender_days_late"], 16)

    def test_never_done_chores_excluded_from_worst_offender_ranking(self):
        chores = [_chore(name="Mop", last_done_at=None)]

        stats = chore_stats(chores, NOW)

        self.assertIsNone(stats["worst_offender"])
        self.assertIsNone(stats["worst_offender_days_late"])

    def test_no_worst_offender_when_nothing_is_overdue(self):
        chores = [_chore(name="Mop", threshold_days=14, last_done_at=(NOW - timedelta(days=1)).isoformat())]

        stats = chore_stats(chores, NOW)

        self.assertIsNone(stats["worst_offender"])

    def test_by_person_counts_last_completions(self):
        chores = [
            _chore(name="Mop", last_done_by="Alex"),
            _chore(name="Clean oven", last_done_by="Alex"),
            _chore(name="Vacuum", last_done_by="Sam"),
            _chore(name="Wash bed sheets", last_done_by=None),
        ]

        stats = chore_stats(chores, NOW)

        self.assertEqual(stats["by_person"], {"Alex": 2, "Sam": 1})

    def test_empty_chore_list(self):
        stats = chore_stats([], NOW)

        self.assertEqual(stats["total"], 0)
        self.assertEqual(stats["overdue_count"], 0)
        self.assertEqual(stats["by_person"], {})
        self.assertIsNone(stats["worst_offender"])


if __name__ == "__main__":
    unittest.main()
