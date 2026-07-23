import unittest

from services.chore_stats_embed import build_chore_stats_embed


def _stats(**overrides):
    stats = {
        "total": 0,
        "overdue_count": 0,
        "upcoming_count": 0,
        "never_done_count": 0,
        "worst_offender": None,
        "worst_offender_days_late": None,
        "by_person": {},
    }
    stats.update(overrides)
    return stats


class BuildChoreStatsEmbedTests(unittest.TestCase):
    def test_shows_chore_board_summary(self):
        embed = build_chore_stats_embed(_stats(total=18, overdue_count=2, upcoming_count=3))
        fields = {field.name: field.value for field in embed.fields}

        normalized = fields["🧹 Chore Board"].replace("\xa0", " ")
        self.assertIn("18 chores", normalized)
        self.assertIn("2 overdue", normalized)
        self.assertIn("3 coming up", normalized)

    def test_no_never_logged_field_when_zero(self):
        embed = build_chore_stats_embed(_stats(never_done_count=0))
        self.assertNotIn("Never Logged", {f.name for f in embed.fields})

    def test_never_logged_field_when_present(self):
        embed = build_chore_stats_embed(_stats(never_done_count=4))
        fields = {field.name: field.value for field in embed.fields}
        self.assertIn("4 chore(s)", fields["Never Logged"])

    def test_no_worst_offender_field_when_none(self):
        embed = build_chore_stats_embed(_stats(worst_offender=None))
        self.assertNotIn("Most Overdue", {f.name for f in embed.fields})

    def test_worst_offender_field_when_present(self):
        stats = _stats(worst_offender={"name": "Clean oven"}, worst_offender_days_late=16)
        embed = build_chore_stats_embed(stats)
        fields = {field.name: field.value for field in embed.fields}
        self.assertIn("Clean oven", fields["Most Overdue"])
        self.assertIn("16 days", fields["Most Overdue"])

    def test_worst_offender_uses_singular_day(self):
        stats = _stats(worst_offender={"name": "Mop"}, worst_offender_days_late=1)
        embed = build_chore_stats_embed(stats)
        fields = {field.name: field.value for field in embed.fields}
        self.assertIn("1 day ", fields["Most Overdue"])
        self.assertNotIn("1 days", fields["Most Overdue"])

    def test_by_person_sorted_descending(self):
        stats = _stats(by_person={"Sam": 1, "Alex": 3})
        embed = build_chore_stats_embed(stats)
        fields = {field.name: field.value for field in embed.fields}
        value = fields["Most Recently Responsible For"]
        self.assertLess(value.index("Alex"), value.index("Sam"))

    def test_no_by_person_field_when_empty(self):
        embed = build_chore_stats_embed(_stats(by_person={}))
        self.assertNotIn("Most Recently Responsible For", {f.name for f in embed.fields})


if __name__ == "__main__":
    unittest.main()
