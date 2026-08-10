import unittest
from datetime import date, datetime, timedelta, timezone

from services.weekly_digest_embed import build_weekly_digest_embed

WEEK_START = date(2026, 7, 13)
NOW = datetime(2026, 7, 21, 9, 0, tzinfo=timezone.utc)


def _completion(chore_name, done_by, done_at):
    return {"chore_name": chore_name, "done_by": done_by, "done_at": done_at}


def _task(task_name, completed_by, completed_at):
    return {"task_name": task_name, "completed_by": completed_by, "completed_at": completed_at}


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


class BuildWeeklyDigestEmbedTests(unittest.TestCase):
    def test_title_shows_the_week_range(self):
        embed = build_weekly_digest_embed(WEEK_START, [], [], NOW)

        self.assertIn("Jul 13", embed.title)
        self.assertIn("Jul 19", embed.title)

    def test_empty_completions_shows_placeholder(self):
        embed = build_weekly_digest_embed(WEEK_START, [], [], NOW)

        fields = {f.name: f.value for f in embed.fields}
        self.assertIn("Nothing logged", fields["Chores Completed"])

    def test_lists_each_completion_with_person_and_day(self):
        completions = [
            _completion("Mop", "Peyton", datetime(2026, 7, 14, 9, 0, tzinfo=timezone.utc).isoformat()),
        ]

        embed = build_weekly_digest_embed(WEEK_START, completions, [], NOW)

        fields = {f.name: f.value for f in embed.fields}
        self.assertIn("Mop", fields["Chores Completed"])
        self.assertIn("Peyton", fields["Chores Completed"])
        self.assertIn("Jul 14", fields["Chores Completed"])

    def test_leaderboard_counts_by_person(self):
        completions = [
            _completion("Mop", "Peyton", datetime(2026, 7, 14, tzinfo=timezone.utc).isoformat()),
            _completion("Vacuum couch", "Peyton", datetime(2026, 7, 15, tzinfo=timezone.utc).isoformat()),
            _completion("Wash bed sheets", "Joe", datetime(2026, 7, 16, tzinfo=timezone.utc).isoformat()),
        ]

        embed = build_weekly_digest_embed(WEEK_START, completions, [], NOW)

        fields = {f.name: f.value for f in embed.fields}
        self.assertIn("Peyton: 2", fields["🏆 Last Week's Leaderboard"])
        self.assertIn("Joe: 1", fields["🏆 Last Week's Leaderboard"])

    def test_no_leaderboard_field_when_no_completions(self):
        embed = build_weekly_digest_embed(WEEK_START, [], [], NOW)

        self.assertNotIn("🏆 Last Week's Leaderboard", {f.name for f in embed.fields})

    def test_still_overdue_field_lists_overdue_chores(self):
        chores = [_chore(name="Clean oven", last_done_at=None)]

        embed = build_weekly_digest_embed(WEEK_START, [], chores, NOW)

        fields = {f.name: f.value for f in embed.fields}
        self.assertIn("Clean oven", fields["Still Overdue"])

    def test_no_still_overdue_field_when_nothing_overdue(self):
        last_done = (NOW - timedelta(days=1)).isoformat()
        chores = [_chore(name="Mop", threshold_days=14, last_done_at=last_done)]

        embed = build_weekly_digest_embed(WEEK_START, [], chores, NOW)

        self.assertNotIn("Still Overdue", {f.name for f in embed.fields})

    def test_no_tasks_completed_field_when_no_tasks(self):
        embed = build_weekly_digest_embed(WEEK_START, [], [], NOW)

        self.assertNotIn("📦 Tasks Completed", {f.name for f in embed.fields})

    def test_lists_each_completed_task_with_person_and_day(self):
        tasks = [
            _task("Call vet", "Joe", datetime(2026, 7, 14, 9, 0, tzinfo=timezone.utc).isoformat()),
        ]

        embed = build_weekly_digest_embed(WEEK_START, [], [], NOW, tasks=tasks)

        fields = {f.name: f.value for f in embed.fields}
        self.assertIn("Call vet", fields["📦 Tasks Completed"])
        self.assertIn("Joe", fields["📦 Tasks Completed"])
        self.assertIn("Jul 14", fields["📦 Tasks Completed"])

    def test_leaderboard_combines_chores_and_tasks(self):
        completions = [
            _completion("Mop", "Peyton", datetime(2026, 7, 14, tzinfo=timezone.utc).isoformat()),
        ]
        tasks = [
            _task("Call vet", "Peyton", datetime(2026, 7, 15, tzinfo=timezone.utc).isoformat()),
            _task("Buy dog food", "Joe", datetime(2026, 7, 16, tzinfo=timezone.utc).isoformat()),
        ]

        embed = build_weekly_digest_embed(WEEK_START, completions, [], NOW, tasks=tasks)

        fields = {f.name: f.value for f in embed.fields}
        self.assertIn("Peyton: 2", fields["🏆 Last Week's Leaderboard"])
        self.assertIn("Joe: 1", fields["🏆 Last Week's Leaderboard"])


if __name__ == "__main__":
    unittest.main()
