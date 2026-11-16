import unittest
from types import SimpleNamespace

from config.discord_tags import DISCORD_TAGS
from services.forum import (
    diagnose_tags,
    forum_tag_label,
    get_matching_tags,
    keep_single_human_tag,
    tags_with_human_status,
)


class ForumTagTests(unittest.TestCase):
    def test_applies_no_more_than_five_prioritized_tags(self):
        tag_keys = [
            "dinner",
            "quick",
            "one_pot",
            "pasta",
            "chicken",
            "needs_review",
        ]
        channel = SimpleNamespace(
            available_tags=[
                SimpleNamespace(name=DISCORD_TAGS[tag_key]["discord_name"])
                for tag_key in tag_keys
            ]
        )

        tags = get_matching_tags(channel, tag_keys)

        self.assertEqual(len(tags), 5)
        self.assertEqual(
            [tag.name for tag in tags],
            [
                DISCORD_TAGS["needs_review"]["discord_name"],
                DISCORD_TAGS["chicken"]["discord_name"],
                DISCORD_TAGS["pasta"]["discord_name"],
                DISCORD_TAGS["one_pot"]["discord_name"],
                DISCORD_TAGS["quick"]["discord_name"],
            ],
        )

    def test_keeps_only_the_highest_priority_human_status_tag(self):
        tag_keys = ["needs_review", "made_before", "make_again", "favorite", "pasta"]
        channel = SimpleNamespace(
            available_tags=[
                SimpleNamespace(name=DISCORD_TAGS[tag_key]["discord_name"])
                for tag_key in tag_keys
            ]
        )

        tags = get_matching_tags(channel, tag_keys)

        self.assertEqual(
            [tag.name for tag in tags],
            [
                DISCORD_TAGS["favorite"]["discord_name"],
                DISCORD_TAGS["pasta"]["discord_name"],
            ],
        )

    def test_removes_extra_human_status_tags_from_existing_post(self):
        tags = [
            SimpleNamespace(name=DISCORD_TAGS["needs_review"]["discord_name"]),
            SimpleNamespace(name=DISCORD_TAGS["made_before"]["discord_name"]),
            SimpleNamespace(name=DISCORD_TAGS["favorite"]["discord_name"]),
            SimpleNamespace(name=DISCORD_TAGS["pasta"]["discord_name"]),
        ]

        filtered_tags = keep_single_human_tag(tags)

        self.assertEqual(
            [tag.name for tag in filtered_tags],
            [
                DISCORD_TAGS["favorite"]["discord_name"],
                DISCORD_TAGS["pasta"]["discord_name"],
            ],
        )

    def test_matches_tags_even_when_forum_has_an_extra_variation_selector(self):
        # Discord's actual forum tag may or may not carry the invisible emoji
        # variation-selector character, e.g. "⏱️" (with U+FE0F) vs. "⏱"
        # (without it), both meaning the same emoji. Our config is plain; this
        # simulates the forum tag carrying the extra selector our config lacks.
        base_name = DISCORD_TAGS["quick"]["discord_name"]
        decorated_name = base_name[0] + chr(0xFE0F) + base_name[1:]
        channel = SimpleNamespace(
            available_tags=[
                SimpleNamespace(name=DISCORD_TAGS["needs_review"]["discord_name"]),
                SimpleNamespace(name=decorated_name),
            ]
        )

        tags = get_matching_tags(channel, ["needs_review", "quick"])

        self.assertEqual(
            [tag.name for tag in tags],
            [DISCORD_TAGS["needs_review"]["discord_name"], decorated_name],
        )

    def test_replaces_a_human_status_tag_and_preserves_recipe_tags(self):
        available_tags = [
            SimpleNamespace(name=DISCORD_TAGS[tag_key]["discord_name"])
            for tag_key in ["needs_review", "favorite", "pasta", "quick"]
        ]
        channel = SimpleNamespace(available_tags=available_tags)
        current_tags = [available_tags[0], available_tags[2], available_tags[3]]

        updated_tags = tags_with_human_status(channel, current_tags, "favorite")

        self.assertEqual(
            [tag.name for tag in updated_tags],
            [
                DISCORD_TAGS["favorite"]["discord_name"],
                DISCORD_TAGS["pasta"]["discord_name"],
                DISCORD_TAGS["quick"]["discord_name"],
            ],
        )

    def test_matches_a_tag_made_with_discords_emoji_picker(self):
        # Discord stores a picker-made tag as name "Thanksgiving" + a separate
        # emoji field, not "🦃 Thanksgiving" like the tags typed with the emoji in
        # the name. Matching on `.name` alone silently never applied it.
        channel = SimpleNamespace(
            available_tags=[
                SimpleNamespace(name="Thanksgiving", emoji=SimpleNamespace(name="🦃", id=None)),
                SimpleNamespace(name=DISCORD_TAGS["needs_review"]["discord_name"]),
            ]
        )

        tags = get_matching_tags(channel, ["needs_review", "thanksgiving"])

        self.assertEqual([tag.name for tag in tags], [DISCORD_TAGS["needs_review"]["discord_name"], "Thanksgiving"])

    def test_thanksgiving_outranks_the_proteins_under_the_five_tag_cap(self):
        keys = ["needs_review", "beef", "pasta", "one_pot", "quick", "dinner", "thanksgiving"]
        channel = SimpleNamespace(
            available_tags=[SimpleNamespace(name=DISCORD_TAGS[key]["discord_name"]) for key in keys]
        )

        tags = get_matching_tags(channel, keys)

        self.assertEqual(len(tags), 5)
        self.assertIn(DISCORD_TAGS["thanksgiving"]["discord_name"], [tag.name for tag in tags])

    def test_a_retired_tag_still_in_the_database_is_skipped_not_fatal(self):
        # "vegetarian" was dropped from the config but old recipes still carry it.
        channel = SimpleNamespace(
            available_tags=[SimpleNamespace(name=DISCORD_TAGS["needs_review"]["discord_name"])]
        )

        tags = get_matching_tags(channel, ["needs_review", "vegetarian"])

        self.assertEqual([tag.name for tag in tags], [DISCORD_TAGS["needs_review"]["discord_name"]])

    def test_diagnose_reports_a_picker_made_tag_as_matching_not_missing(self):
        tag = SimpleNamespace(name="Thanksgiving", emoji=SimpleNamespace(name="🦃", id=None))
        names = [DISCORD_TAGS[key]["discord_name"] for key in DISCORD_TAGS if key != "thanksgiving"]

        result = diagnose_tags(names + [forum_tag_label(tag)])

        self.assertNotIn(DISCORD_TAGS["thanksgiving"]["discord_name"], result["missing"])

    def test_diagnose_tags_reports_ok_mismatched_and_missing(self):
        base_name = DISCORD_TAGS["quick"]["discord_name"]
        decorated_quick = base_name[0] + chr(0xFE0F) + base_name[1:]
        available_tag_names = [
            DISCORD_TAGS["needs_review"]["discord_name"],  # exact match
            decorated_quick,  # matches only after normalization
            # "long" is entirely absent
        ]

        result = diagnose_tags(available_tag_names)

        self.assertIn(DISCORD_TAGS["needs_review"]["discord_name"], result["ok"])
        self.assertIn(
            (DISCORD_TAGS["quick"]["discord_name"], decorated_quick),
            result["mismatched"],
        )
        self.assertIn(DISCORD_TAGS["long"]["discord_name"], result["missing"])

    def test_diagnose_tags_reports_all_ok_when_everything_matches(self):
        available_tag_names = [info["discord_name"] for info in DISCORD_TAGS.values()]

        result = diagnose_tags(available_tag_names)

        self.assertEqual(len(result["ok"]), len(DISCORD_TAGS))
        self.assertEqual(result["mismatched"], [])
        self.assertEqual(result["missing"], [])


if __name__ == "__main__":
    unittest.main()


class ForumTagLabelTests(unittest.TestCase):
    def test_plain_name_is_unchanged(self):
        self.assertEqual(forum_tag_label(SimpleNamespace(name="🥩 Beef")), "🥩 Beef")

    def test_picker_emoji_is_put_in_front_of_the_name(self):
        tag = SimpleNamespace(name="Thanksgiving", emoji=SimpleNamespace(name="🦃", id=None))
        self.assertEqual(forum_tag_label(tag), "🦃 Thanksgiving")

    def test_emoji_already_in_the_name_is_not_doubled(self):
        tag = SimpleNamespace(name="🦃 Thanksgiving", emoji=SimpleNamespace(name="🦃", id=None))
        self.assertEqual(forum_tag_label(tag), "🦃 Thanksgiving")

    def test_no_emoji_field(self):
        self.assertEqual(forum_tag_label(SimpleNamespace(name="Soup", emoji=None)), "Soup")

    def test_custom_server_emoji_is_not_prefixed(self):
        # A custom emoji can't be written into the config, so there's nothing to match on.
        tag = SimpleNamespace(name="Soup", emoji=SimpleNamespace(name="soupy", id=123))
        self.assertEqual(forum_tag_label(tag), "Soup")
