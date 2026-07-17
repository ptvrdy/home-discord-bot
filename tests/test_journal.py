import unittest

from services.journal import build_journal_embed


def make_entry(made_at, author_name, status="made_before", rating=None, notes=None, next_time=None):
    return {
        "made_at": made_at,
        "activity": "Made",
        "status": status,
        "rating": rating,
        "notes": notes,
        "next_time": next_time,
        "author_name": author_name,
    }


class JournalTests(unittest.TestCase):
    def test_empty_entries_show_a_placeholder(self):
        embed = build_journal_embed([])

        self.assertEqual(embed.description, "No entries yet.")

    def test_entry_includes_star_rating_notes_and_author(self):
        entry = make_entry(
            "2026-07-17T12:00:00+00:00",
            "Peyton",
            rating=4,
            notes="Used chicken sausage.",
            next_time="Add more garlic.",
        )

        embed = build_journal_embed([entry])

        self.assertIn("Peyton", embed.description)
        self.assertIn("⭐⭐⭐⭐☆", embed.description)
        self.assertIn("Used chicken sausage.", embed.description)
        self.assertIn("Add more garlic.", embed.description)
        self.assertIn("July 17, 2026", embed.description)

    def test_multiple_entries_are_separated_and_kept_in_order(self):
        entries = [
            make_entry("2026-07-01T12:00:00+00:00", "Peyton", rating=3),
            make_entry("2026-07-10T12:00:00+00:00", "Husband", rating=5),
        ]

        embed = build_journal_embed(entries)

        first_index = embed.description.index("Peyton")
        second_index = embed.description.index("Husband")
        self.assertLess(first_index, second_index)
        self.assertIn("\n\n", embed.description)

    def test_oldest_entries_are_dropped_when_the_embed_would_overflow(self):
        entries = [
            make_entry(f"2026-01-{day:02d}T12:00:00+00:00", "Peyton", notes="x" * 2000)
            for day in range(1, 4)
        ]

        embed = build_journal_embed(entries)

        self.assertLessEqual(len(embed.description), 4096)
        self.assertNotIn("2026-01-01", embed.description)


if __name__ == "__main__":
    unittest.main()
