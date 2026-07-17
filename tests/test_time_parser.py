import unittest

from services.time_parser import parse_minutes


class TimeParserTests(unittest.TestCase):
    def test_parses_bare_numbers_as_minutes(self):
        self.assertEqual(parse_minutes("20"), 20)
        self.assertEqual(parse_minutes(" 5 "), 5)

    def test_parses_iso_durations(self):
        self.assertEqual(parse_minutes("PT1H30M"), 90)
        self.assertEqual(parse_minutes("PT45M"), 45)

    def test_parses_text_durations(self):
        self.assertEqual(parse_minutes("2 hours 30 minutes"), 150)
        self.assertEqual(parse_minutes("45 minutes"), 45)

    def test_returns_none_for_missing_or_unparseable_values(self):
        self.assertIsNone(parse_minutes(None))
        self.assertIsNone(parse_minutes(""))
        self.assertIsNone(parse_minutes("ready when it's ready"))


if __name__ == "__main__":
    unittest.main()
