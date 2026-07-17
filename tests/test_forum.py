import unittest
from types import SimpleNamespace

from config.discord_tags import DISCORD_TAGS
from services.forum import (
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


if __name__ == "__main__":
    unittest.main()
