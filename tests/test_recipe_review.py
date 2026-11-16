import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from commands import recipe_commands
from commands.recipe_commands import RECIPE_NOT_IN_BOX_MESSAGE, RecipeReviewModal

THREAD_ID = 555


def _modal():
    thread = MagicMock(spec=discord.Thread)
    thread.id = THREAD_ID
    thread.parent = MagicMock(spec=discord.ForumChannel)
    thread.applied_tags = []
    thread.edit = AsyncMock()
    thread.send = AsyncMock(return_value=SimpleNamespace(id=999))

    modal = RecipeReviewModal(thread, "made_before")
    modal.rating = SimpleNamespace(value="5")
    modal.notes = SimpleNamespace(value="Loved it")
    modal.next_time = SimpleNamespace(value="")
    return modal, thread


def _interaction():
    interaction = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.send_modal = AsyncMock()
    interaction.followup.send = AsyncMock()
    interaction.user.display_name = "Peyton"
    return interaction


def _sent(interaction) -> list[str]:
    return [call.args[0] for call in interaction.followup.send.await_args_list]


class ReviewModalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.recipe = patch.object(recipe_commands, "get_recipe_by_thread", return_value={"ingredients": []}).start()
        self.add_log = patch.object(recipe_commands, "add_cooking_log", return_value=True).start()
        patch.object(recipe_commands, "tags_with_human_status", return_value=[]).start()
        patch.object(recipe_commands, "get_cooking_log_entries", return_value=[]).start()
        patch.object(recipe_commands, "get_journal_message_id", return_value=None).start()
        patch.object(recipe_commands, "set_journal_message_id").start()
        patch.object(recipe_commands, "offer_recipe_consumption", AsyncMock()).start()
        self.addCleanup(patch.stopall)

    async def test_saves_the_review_and_posts_the_journal(self):
        modal, thread = _modal()
        interaction = _interaction()

        await modal.on_submit(interaction)

        self.add_log.assert_called_once()
        self.assertIn("✅ Review saved!", _sent(interaction))
        thread.send.assert_awaited_once()  # the journal message

    async def test_a_recipe_missing_from_the_database_is_refused_before_anything_changes(self):
        # Regression: this used to reply "✅ Review saved!" and post an empty
        # "No entries yet" journal, silently throwing the typed review away.
        self.recipe.return_value = None
        modal, thread = _modal()
        interaction = _interaction()

        await modal.on_submit(interaction)

        self.assertEqual(_sent(interaction), [RECIPE_NOT_IN_BOX_MESSAGE])
        self.add_log.assert_not_called()
        thread.edit.assert_not_awaited()  # forum tags left alone too
        thread.send.assert_not_awaited()  # no empty journal posted

    async def test_a_save_that_stores_nothing_is_never_reported_as_saved(self):
        # The row can vanish between the up-front check and the write.
        self.add_log.return_value = False
        modal, thread = _modal()
        interaction = _interaction()

        await modal.on_submit(interaction)

        self.assertEqual(_sent(interaction), [RECIPE_NOT_IN_BOX_MESSAGE])
        thread.send.assert_not_awaited()

    async def test_a_bad_rating_is_still_rejected_first(self):
        modal, thread = _modal()
        modal.rating = SimpleNamespace(value="9")
        interaction = _interaction()

        await modal.on_submit(interaction)

        interaction.response.send_message.assert_awaited_once()
        self.add_log.assert_not_called()


class ReviewCommandTests(unittest.IsolatedAsyncioTestCase):
    def _cog_and_thread(self):
        cog = recipe_commands.Recipe(MagicMock())
        cog.recipe_forum_id = 999
        thread = MagicMock(spec=discord.Thread)
        thread.id = THREAD_ID
        thread.parent_id = 999
        return cog, thread

    async def _run_review(self, recipe_row):
        cog, thread = self._cog_and_thread()
        interaction = _interaction()
        interaction.channel = thread
        with patch.object(recipe_commands, "get_recipe_by_thread", return_value=recipe_row):
            await recipe_commands.Recipe.review.callback(cog, interaction, SimpleNamespace(value="made_before"))
        return interaction

    async def test_opens_the_form_for_a_recipe_in_the_database(self):
        interaction = await self._run_review({"ingredients": []})

        interaction.response.send_modal.assert_awaited_once()
        interaction.response.send_message.assert_not_awaited()

    async def test_refuses_without_opening_the_form_when_the_recipe_isnt_in_the_database(self):
        interaction = await self._run_review(None)

        interaction.response.send_modal.assert_not_awaited()
        interaction.response.send_message.assert_awaited_once()
        self.assertEqual(interaction.response.send_message.await_args.args[0], RECIPE_NOT_IN_BOX_MESSAGE)
        self.assertTrue(interaction.response.send_message.await_args.kwargs["ephemeral"])


if __name__ == "__main__":
    unittest.main()
