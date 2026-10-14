import unittest

from models.recipe_card import Recipe
from services.embed import build_instructions_embed, create_recipe_embed
from services.recipe_sync import find_mismatches, recipe_from_post, tag_keys_from_forum_tags
from config.discord_tags import DISCORD_TAGS
from unittest.mock import patch


def _post(recipe: Recipe):
    """What Discord hands back for a post: the card as a dict, and the
    instructions message's text."""
    with patch("services.embed.should_use_thumbnail", return_value=False):
        card = create_recipe_embed(recipe).to_dict()
    instructions = build_instructions_embed(recipe)
    return card, instructions.description if instructions else None


class FindMismatchesTests(unittest.TestCase):
    def test_both_directions(self):
        threads = {1: "Tacos", 2: "Pad Thai", 3: "Chili"}
        rows = [{"title": "Tacos", "discord_thread_id": 1}, {"title": "Old Soup", "discord_thread_id": 9}]
        missing_in_db, missing_in_forum = find_mismatches(threads, rows)
        self.assertEqual(missing_in_db, [(3, "Chili"), (2, "Pad Thai")])
        self.assertEqual([row["title"] for row in missing_in_forum], ["Old Soup"])

    def test_in_sync(self):
        self.assertEqual(find_mismatches({1: "A"}, [{"title": "A", "discord_thread_id": 1}]), ([], []))


class RecipeFromPostTests(unittest.TestCase):
    def test_round_trip_of_a_full_recipe(self):
        original = Recipe(
            title="Lemon Chicken",
            ingredients=["2 lbs chicken thighs", "1 lemon, juiced", "2 cloves garlic"],
            instructions="Marinate the chicken.\nRoast at 425°F for 30 minutes.",
            prep_time="10 minutes", cook_time="30 minutes", total_time="40 minutes",
            yields="4 servings",
            image_url="https://example.com/chicken.jpg",
            source_url="https://example.com/lemon-chicken",
            source_name="Example Kitchen",
            tags=["favorite", "chicken", "dinner"],
        )
        card, instructions = _post(original)
        tag_names = [DISCORD_TAGS[key]["discord_name"] for key in original.tags if key in DISCORD_TAGS]

        rebuilt, complete = recipe_from_post(card, instructions, tag_names)

        self.assertTrue(complete)
        self.assertEqual(rebuilt.title, "Lemon Chicken")
        self.assertEqual(rebuilt.ingredients, original.ingredients)
        self.assertEqual(rebuilt.instructions, original.instructions)
        self.assertEqual((rebuilt.prep_time, rebuilt.cook_time, rebuilt.total_time), ("10 minutes", "30 minutes", "40 minutes"))
        self.assertEqual(rebuilt.total_minutes, 40)
        self.assertEqual(rebuilt.yields, "4 servings")
        self.assertEqual(rebuilt.source_url, "https://example.com/lemon-chicken")
        self.assertEqual(rebuilt.source_name, "Example Kitchen")
        self.assertEqual(rebuilt.image_url, "https://example.com/chicken.jpg")
        self.assertEqual(sorted(rebuilt.tags), sorted(original.tags))

    def test_handwritten_recipe_with_no_link_or_status(self):
        card, instructions = _post(Recipe(title="Grandma's Soup", ingredients=["1 onion"], source_url="", source_name="Handwritten from Sarah"))
        rebuilt, complete = recipe_from_post(card, instructions, [])
        self.assertEqual(rebuilt.source_url, "")
        self.assertEqual(rebuilt.source_name, "Handwritten from Sarah")
        self.assertIsNone(rebuilt.instructions)
        self.assertEqual(rebuilt.tags, ["needs_review"])
        self.assertTrue(complete)

    def test_cut_off_ingredients_are_flagged(self):
        card, instructions = _post(Recipe(title="Huge", ingredients=[f"ingredient number {i} " * 3 for i in range(80)]))
        rebuilt, complete = recipe_from_post(card, instructions, [])
        self.assertFalse(complete)
        self.assertGreater(len(rebuilt.ingredients), 5)

    def test_photo_saved_on_the_card_keeps_a_stable_reference(self):
        card = {"title": "🍒 Toast", "image": {"url": "https://cdn.discordapp.com/attachments/1/2/recipe-image-thumb.jpg?ex=abc&is=def"}}
        rebuilt, _ = recipe_from_post(card, None, [])
        self.assertEqual(rebuilt.image_url, "attachment://recipe-image-thumb.jpg")

    def test_forum_tags_to_keys(self):
        names = [DISCORD_TAGS["beef"]["discord_name"], "Some Unknown Tag"]
        self.assertEqual(tag_keys_from_forum_tags(names), ["beef"])


class _History:
    def __init__(self, messages):
        self.messages = messages

    def __aiter__(self):
        self._iter = iter(self.messages)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


def _thread(recipe: Recipe, thread_id=42, tag_names=()):
    import discord
    from unittest.mock import AsyncMock, MagicMock

    with patch("services.embed.should_use_thumbnail", return_value=False):
        card = create_recipe_embed(recipe)
    instructions = build_instructions_embed(recipe)
    starter = MagicMock(embeds=[card])
    follow_up = MagicMock(embeds=[instructions] if instructions else [])
    thread = MagicMock(spec=discord.Thread)
    thread.id = thread_id
    thread.applied_tags = [MagicMock(name=name) for name in tag_names]
    for tag, name in zip(thread.applied_tags, tag_names):
        tag.name = name
    thread.fetch_message = AsyncMock(return_value=starter)
    thread.history = MagicMock(return_value=_History([starter, follow_up]))
    return thread


class ReimportThreadTests(unittest.IsolatedAsyncioTestCase):
    RECIPE = Recipe(
        title="My Renamed Tacos", ingredients=["1 lb ground beef"], instructions="Brown the beef.",
        source_url="https://example.com/tacos", source_name="Example", tags=["favorite", "beef"],
    )

    async def test_reimports_from_the_link_keeping_title_and_status(self):
        from commands.recipe_sync_commands import reimport_thread

        scraped = Recipe(title="Best Beef Tacos", ingredients=["1 lb ground beef", "8 tortillas", "salsa"],
                         instructions="Brown the beef.\nWarm the tortillas.", source_url="https://example.com/tacos")
        thread = _thread(self.RECIPE, tag_names=[DISCORD_TAGS["favorite"]["discord_name"], DISCORD_TAGS["beef"]["discord_name"]])
        with patch("commands.recipe_sync_commands.scrape_recipe", return_value=scraped), \
                patch("commands.recipe_sync_commands.save_recipe") as save:
            line = await reimport_thread(thread)
        saved, thread_id = save.call_args.args
        self.assertEqual(thread_id, 42)
        self.assertEqual(saved.title, "My Renamed Tacos")  # the /fix rename survives
        self.assertEqual(saved.ingredients, ["1 lb ground beef", "8 tortillas", "salsa"])
        self.assertEqual(saved.tags[0], "favorite")
        self.assertIn("beef", saved.tags)
        self.assertIn("re-imported from the original link", line)

    async def test_falls_back_to_the_post_when_the_site_blocks_scraping(self):
        from commands.recipe_sync_commands import reimport_thread

        thread = _thread(self.RECIPE)
        with patch("commands.recipe_sync_commands.scrape_recipe", side_effect=RuntimeError("403")), \
                patch("commands.recipe_sync_commands.save_recipe") as save:
            line = await reimport_thread(thread)
        saved = save.call_args.args[0]
        self.assertEqual(saved.ingredients, ["1 lb ground beef"])
        self.assertEqual(saved.instructions, "Brown the beef.")
        self.assertIn("rebuilt from the post", line)


class PostThenSaveTests(unittest.IsolatedAsyncioTestCase):
    async def test_instructions_failing_does_not_stop_the_save(self):
        import discord
        from unittest.mock import AsyncMock, MagicMock
        from services.forum import create_recipe_post

        thread = MagicMock()
        thread.send = AsyncMock(side_effect=discord.HTTPException(MagicMock(status=500), "boom"))
        channel = MagicMock()
        channel.available_tags = []
        channel.create_thread = AsyncMock(return_value=MagicMock(thread=thread))
        recipe = Recipe(title="Soup", ingredients=["water"], instructions="Boil.")
        with patch("services.embed.should_use_thumbnail", return_value=False):
            self.assertIs(await create_recipe_post(channel, recipe), thread)


if __name__ == "__main__":
    unittest.main()
