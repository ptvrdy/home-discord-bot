import random
import unittest
from datetime import datetime, timedelta, timezone

from services.chores import (
    SYSTEM_ATTRIBUTION,
    chore_stats,
    chores_due_soon,
    chores_needing_nudge,
    count_completions_by_person,
    days_since,
    fairness_callout,
    filter_person_completions,
    format_nudge_message,
    is_overdue,
    mention_for_person,
    random_overdue_chore,
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

    def test_no_fairness_callout_line_by_default(self):
        chore = _chore(name="Mop", last_done_at=(NOW - timedelta(days=16)).isoformat(), last_done_by="Alex")

        message = format_nudge_message(chore, NOW)

        self.assertNotIn("your turn", message)

    def test_includes_fairness_callout_when_given(self):
        chore = _chore(name="Mop", last_done_at=(NOW - timedelta(days=16)).isoformat(), last_done_by="Alex")

        message = format_nudge_message(chore, NOW, next_person="Sam")

        self.assertIn("Sam", message)
        self.assertIn("your turn", message)


class FairnessCalloutTests(unittest.TestCase):
    def _entries(self, *doers):
        return [{"done_by": doer, "done_at": f"2026-07-{10 + i:02d}"} for i, doer in enumerate(doers)]

    def test_returns_other_person_after_streak(self):
        entries = self._entries("Peyton", "Peyton", "Peyton")

        self.assertEqual(fairness_callout(entries, "Peyton", "Joe"), "Joe")

    def test_returns_other_person_when_streak_at_end_of_longer_history(self):
        entries = self._entries("Joe", "Peyton", "Peyton", "Peyton")

        self.assertEqual(fairness_callout(entries, "Peyton", "Joe"), "Joe")

    def test_none_when_streak_is_mixed(self):
        entries = self._entries("Peyton", "Joe", "Peyton")

        self.assertIsNone(fairness_callout(entries, "Peyton", "Joe"))

    def test_none_when_not_enough_history(self):
        entries = self._entries("Peyton", "Peyton")

        self.assertIsNone(fairness_callout(entries, "Peyton", "Joe"))

    def test_none_when_names_not_configured(self):
        entries = self._entries("Peyton", "Peyton", "Peyton")

        self.assertIsNone(fairness_callout(entries, None, None))
        self.assertIsNone(fairness_callout(entries, "Peyton", None))

    def test_ignores_system_attribution_entries(self):
        entries = self._entries(SYSTEM_ATTRIBUTION, "Peyton", "Peyton", "Peyton")

        self.assertEqual(fairness_callout(entries, "Peyton", "Joe"), "Joe")

    def test_none_when_streak_belongs_to_someone_other_than_the_two_named(self):
        entries = self._entries("Guest", "Guest", "Guest")

        self.assertIsNone(fairness_callout(entries, "Peyton", "Joe"))

    def test_custom_streak_length(self):
        entries = self._entries("Peyton", "Peyton")

        self.assertEqual(fairness_callout(entries, "Peyton", "Joe", streak=2), "Joe")


class MentionForPersonTests(unittest.TestCase):
    def test_maps_personal_name_to_personal_discord_id(self):
        result = mention_for_person("Peyton", "Peyton", "Joe", "111", "222")
        self.assertEqual(result, "<@111>")

    def test_maps_partner_name_to_partner_discord_id(self):
        result = mention_for_person("Joe", "Peyton", "Joe", "111", "222")
        self.assertEqual(result, "<@222>")

    def test_falls_back_to_plain_name_when_discord_id_not_configured(self):
        result = mention_for_person("Peyton", "Peyton", "Joe", None, "222")
        self.assertEqual(result, "Peyton")

    def test_falls_back_to_plain_name_when_neither_discord_id_configured(self):
        result = mention_for_person("Joe", "Peyton", "Joe", None, None)
        self.assertEqual(result, "Joe")

    def test_unrecognized_name_returned_as_is(self):
        result = mention_for_person("Guest", "Peyton", "Joe", "111", "222")
        self.assertEqual(result, "Guest")


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


class RandomOverdueChoreTests(unittest.TestCase):
    def test_returns_none_when_nothing_is_overdue(self):
        last_done = (NOW - timedelta(days=1)).isoformat()
        chores = [_chore(name="Mop", threshold_days=14, last_done_at=last_done)]

        self.assertIsNone(random_overdue_chore(chores, NOW))

    def test_only_picks_from_overdue_chores(self):
        chores = [
            _chore(name="Mop", threshold_days=14, last_done_at=(NOW - timedelta(days=1)).isoformat()),
            _chore(name="Clean oven", last_done_at=None),
        ]

        picked = random_overdue_chore(chores, NOW, rng=random.Random(0))

        self.assertEqual(picked["name"], "Clean oven")

    def test_is_deterministic_with_a_seeded_rng(self):
        chores = [
            _chore(name="Mop", last_done_at=None),
            _chore(name="Clean oven", last_done_at=None),
            _chore(name="Vacuum couch", last_done_at=None),
        ]

        first = random_overdue_chore(chores, NOW, rng=random.Random(42))
        second = random_overdue_chore(chores, NOW, rng=random.Random(42))

        self.assertEqual(first["name"], second["name"])

    def test_more_overdue_chores_are_weighted_higher(self):
        chores = [
            _chore(name="Barely overdue", threshold_days=14, last_done_at=(NOW - timedelta(days=14)).isoformat()),
            _chore(name="Very overdue", threshold_days=14, last_done_at=(NOW - timedelta(days=100)).isoformat()),
        ]

        counts = {"Barely overdue": 0, "Very overdue": 0}
        rng = random.Random(1)
        for _ in range(500):
            picked = random_overdue_chore(chores, NOW, rng=rng)
            counts[picked["name"]] += 1

        self.assertGreater(counts["Very overdue"], counts["Barely overdue"])

    def test_empty_chore_list_returns_none(self):
        self.assertIsNone(random_overdue_chore([], NOW))


class FilterPersonCompletionsTests(unittest.TestCase):
    def test_removes_system_attribution(self):
        by_person = {"Peyton": 2, SYSTEM_ATTRIBUTION: 1}

        self.assertEqual(filter_person_completions(by_person), {"Peyton": 2})

    def test_leaves_real_people_untouched(self):
        by_person = {"Peyton": 2, "Joe": 3}

        self.assertEqual(filter_person_completions(by_person), {"Peyton": 2, "Joe": 3})

    def test_empty_dict(self):
        self.assertEqual(filter_person_completions({}), {})

    def test_only_system_attribution(self):
        self.assertEqual(filter_person_completions({SYSTEM_ATTRIBUTION: 1}), {})


class CountCompletionsByPersonTests(unittest.TestCase):
    def test_counts_entries_per_person(self):
        entries = [
            {"done_by": "Peyton"},
            {"done_by": "Peyton"},
            {"done_by": "Joe"},
        ]

        self.assertEqual(count_completions_by_person(entries), {"Peyton": 2, "Joe": 1})

    def test_excludes_system_attribution(self):
        entries = [{"done_by": "Peyton"}, {"done_by": SYSTEM_ATTRIBUTION}]

        self.assertEqual(count_completions_by_person(entries), {"Peyton": 1})

    def test_empty_list(self):
        self.assertEqual(count_completions_by_person([]), {})


if __name__ == "__main__":
    unittest.main()
