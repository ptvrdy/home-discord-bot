import unittest

from services.pantry_parser import (
    ADD,
    CONSUME,
    CONSUME_ALL,
    FREEZE,
    OPEN,
    SPOIL,
    PantryAction,
    parse_pantry_message,
)


def actions(message: str) -> list[PantryAction]:
    return parse_pantry_message(message).actions


class PantryParserTests(unittest.TestCase):
    def test_two_actions_joined_by_and(self):
        self.assertEqual(
            actions("finished the milk and used 4 eggs"),
            [PantryAction(CONSUME_ALL, "milk"), PantryAction(CONSUME, "eggs", 4.0)],
        )

    def test_list_continuations_reuse_the_verb(self):
        self.assertEqual(
            actions("bought milk, 2 avocados, eggs"),
            [PantryAction(ADD, "milk"), PantryAction(ADD, "avocados", 2.0), PantryAction(ADD, "eggs")],
        )

    def test_a_dozen(self):
        self.assertEqual(actions("bought a dozen eggs"), [PantryAction(ADD, "eggs", 12.0)])

    def test_out_of(self):
        self.assertEqual(actions("we're out of olive oil"), [PantryAction(CONSUME_ALL, "olive oil")])
        self.assertEqual(actions("Rosie, milk is gone"), [PantryAction(CONSUME_ALL, "milk")])

    def test_spoiled(self):
        self.assertEqual(actions("the spinach went bad"), [PantryAction(SPOIL, "spinach")])
        self.assertEqual(actions("threw out 2 peppers"), [PantryAction(SPOIL, "peppers", 2.0)])

    def test_used_some_marks_opened(self):
        self.assertEqual(actions("used some butter"), [PantryAction(OPEN, "butter")])

    def test_freeze(self):
        self.assertEqual(actions("froze the chicken thighs"), [PantryAction(FREEZE, "chicken thighs")])
        self.assertEqual(actions("put the ground beef in the freezer"), [PantryAction(FREEZE, "ground beef")])

    def test_compound_items_are_not_split(self):
        self.assertEqual(
            actions("used the last of the mac and cheese"),
            [PantryAction(CONSUME_ALL, "mac and cheese")],
        )

    def test_a_means_one(self):
        self.assertEqual(actions("ate a banana"), [PantryAction(CONSUME, "banana", 1.0)])

    def test_unrecognized_text_is_reported(self):
        result = parse_pantry_message("hello there")
        self.assertEqual(result.actions, [])
        self.assertEqual(result.unparsed, ["hello there"])


if __name__ == "__main__":
    unittest.main()
