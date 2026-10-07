import unittest

from services.embed import HELP_SECTIONS, build_help_embed


class HelpSectionsTests(unittest.TestCase):
    def test_every_entry_is_a_command_and_description(self):
        # A section accidentally nested inside another one still "works" as a
        # list, but renders as garbage in /help.
        for section_name, commands in HELP_SECTIONS:
            for entry in commands:
                self.assertEqual(len(entry), 2, f"{section_name}: {entry!r}")
                name, description = entry
                self.assertTrue(name.startswith("/") or name.startswith("**"), f"{section_name}: {name!r}")
                self.assertIsInstance(description, str, f"{section_name}: {name!r}")

    def test_pantry_section_is_listed(self):
        self.assertIn("🥫 Pantry", [name for name, _ in HELP_SECTIONS])

    def test_fits_discord_limits(self):
        embed = build_help_embed()
        self.assertLessEqual(len(embed), 6000)
        self.assertLessEqual(len(embed.fields), 25)
        for field in embed.fields:
            self.assertLessEqual(len(field.value), 1024, field.name)


if __name__ == "__main__":
    unittest.main()
