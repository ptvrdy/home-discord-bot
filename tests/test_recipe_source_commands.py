import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from commands import recipe_commands, recipe_sync_commands
from commands.recipe_commands import NoLinkRecipeModal, ManualRecipeModal, reply_to_final_step
from commands.recipe_sync_commands import (
    FIX_SOURCES_BATCH, ForgetButton, ReimportView, RecipeSync, edit_card, post_is_gone,
)
from models.recipe_card import Recipe
from services.database import (
    add_cooking_log,
    delete_recipe_by_thread,
    get_recipe_by_thread,
    get_recipe_sources,
    get_recipe_tags,
    save_recipe,
    update_recipe_source,
    update_recipe_status,
)

YOUTUBE = "https://www.youtube.com/watch?v=okZl55RUJbI"


class RecipeSourceDatabaseTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.path = Path(self._dir.name) / "recipes.db"

    def _save(self, title, thread_id, url="", name=None):
        recipe = Recipe(
            title=title, ingredients=["a"], instructions="b",
            source_url=url, source_name=name, tags=["needs_review", "pasta"],
        )
        save_recipe(recipe, thread_id, self.path)

    def test_lists_each_recipes_source_in_title_order(self):
        self._save("Zucchini", 2, YOUTUBE)
        self._save("Apple", 1, "", "Hand-entered")
        rows = get_recipe_sources(self.path)
        self.assertEqual([r["title"] for r in rows], ["Apple", "Zucchini"])
        self.assertEqual(rows[1]["source_url"], YOUTUBE)
        self.assertEqual(rows[0]["source_name"], "Hand-entered")

    def test_updating_the_source_touches_nothing_else(self):
        self._save("Corn", 7, "", YOUTUBE)
        update_recipe_status(7, "favorite", self.path)
        before = get_recipe_by_thread(7, self.path)
        tags_before = get_recipe_tags(7, self.path)

        self.assertTrue(update_recipe_source(7, "YouTube", YOUTUBE, self.path))

        after = get_recipe_by_thread(7, self.path)
        self.assertEqual(after["source_name"], "YouTube")
        self.assertEqual(after["source_url"], YOUTUBE)
        for key in before:
            if key not in ("source_name", "source_url"):
                self.assertEqual(after[key], before[key], key)
        self.assertEqual(get_recipe_tags(7, self.path), tags_before)

    def test_updating_an_unknown_post_reports_false(self):
        self.assertFalse(update_recipe_source(404, "YouTube", YOUTUBE, self.path))


def _modal_interaction(kind):
    interaction = MagicMock()
    interaction.type = kind
    interaction.edit_original_response = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


class ReplyToFinalStepTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_form_submit_writes_into_the_private_message(self):
        interaction = _modal_interaction(discord.InteractionType.modal_submit)
        await reply_to_final_step(interaction, "✅ Recipe added!")
        interaction.edit_original_response.assert_awaited_once_with(content="✅ Recipe added!", view=None)
        interaction.followup.send.assert_not_awaited()

    async def test_falls_back_to_a_followup_if_that_edit_fails(self):
        interaction = _modal_interaction(discord.InteractionType.modal_submit)
        interaction.edit_original_response.side_effect = discord.HTTPException(MagicMock(status=404), "gone")
        await reply_to_final_step(interaction, "✅ Recipe added!")
        interaction.followup.send.assert_awaited_once_with("✅ Recipe added!")

    async def test_a_slash_command_just_sends_a_followup(self):
        interaction = _modal_interaction(discord.InteractionType.application_command)
        await reply_to_final_step(interaction, "✅ Recipe added!")
        interaction.edit_original_response.assert_not_awaited()
        interaction.followup.send.assert_awaited_once_with("✅ Recipe added!")


def _text(value):
    return SimpleNamespace(value=value)


def _no_link_modal(source):
    modal = object.__new__(NoLinkRecipeModal)
    modal.cog = MagicMock()
    modal.recipe_name, modal.ingredients = _text("Corn"), _text("corn\nbutter")
    modal.instructions, modal.image_url, modal.source = _text(""), _text(""), _text(source)
    return modal


async def _submit(modal):
    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()
    await modal.on_submit(interaction)
    return interaction.response.send_message.await_args.kwargs["view"].partial_recipe


class ModalSourceTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_youtube_link_in_the_source_box_becomes_a_link(self):
        recipe = await _submit(_no_link_modal(YOUTUBE))
        self.assertEqual((recipe["source_url"], recipe["source_name"]), (YOUTUBE, "YouTube"))

    async def test_a_link_from_an_unknown_site_is_kept_as_a_link_without_a_name(self):
        recipe = await _submit(_no_link_modal("https://example.com/x"))
        self.assertEqual((recipe["source_url"], recipe["source_name"]), ("https://example.com/x", None))

    async def test_a_written_attribution_stays_a_name(self):
        recipe = await _submit(_no_link_modal("Handwritten from Sarah"))
        self.assertEqual((recipe["source_url"], recipe["source_name"]), ("", "Handwritten from Sarah"))

    async def test_a_blank_source_is_hand_entered(self):
        recipe = await _submit(_no_link_modal(""))
        self.assertEqual((recipe["source_url"], recipe["source_name"]), ("", "Hand-entered"))

    async def test_the_manual_modal_names_youtube_too(self):
        modal = object.__new__(ManualRecipeModal)
        modal.cog = MagicMock()
        modal.recipe_name, modal.ingredients = _text("Corn"), _text("corn")
        modal.instructions, modal.image_url, modal.video_url = _text(""), _text(""), _text(YOUTUBE)
        recipe = await _submit(modal)
        self.assertEqual(recipe["source_name"], "YouTube")


def _thread(thread_id=10, archived=False):
    thread = MagicMock(spec=discord.Thread)
    thread.id = thread_id
    thread.archived = archived
    thread.edit = AsyncMock()
    starter = MagicMock()
    starter.edit = AsyncMock()
    thread.fetch_message = AsyncMock(return_value=starter)
    thread.starter = starter
    return thread


class EditCardTests(unittest.IsolatedAsyncioTestCase):
    async def test_edits_an_open_post_without_touching_its_archive_state(self):
        thread = _thread()
        self.assertFalse(await edit_card(thread, "embed"))
        thread.starter.edit.assert_awaited_once_with(embed="embed")
        thread.edit.assert_not_awaited()

    async def test_reopens_then_rearchives_an_archived_post(self):
        thread = _thread(archived=True)
        self.assertTrue(await edit_card(thread, "embed"))
        self.assertEqual([c.kwargs for c in thread.edit.await_args_list], [{"archived": False}, {"archived": True}])

    async def test_rearchives_even_when_the_edit_fails(self):
        thread = _thread(archived=True)
        thread.starter.edit.side_effect = RuntimeError("boom")
        with self.assertRaises(RuntimeError):
            await edit_card(thread, "embed")
        self.assertEqual(thread.edit.await_args_list[-1].kwargs, {"archived": True})


def _row(thread_id, url=YOUTUBE, name=None, title=None):
    return {"discord_thread_id": thread_id, "title": title or f"R{thread_id}", "source_url": url, "source_name": name}


class FixSourcesCommandTests(unittest.IsolatedAsyncioTestCase):
    def _cog(self, threads):
        cog = object.__new__(RecipeSync)
        forum = MagicMock(spec=discord.ForumChannel)
        cog.bot = MagicMock()
        cog.bot.get_channel.return_value = forum
        cog.recipe_forum_id = 1
        self.threads = threads
        return cog

    def _interaction(self):
        interaction = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.response.send_message = AsyncMock()
        interaction.followup.send = AsyncMock()
        return interaction

    def _run_patches(self, rows, events):
        full = {"title": "t", "ingredients": ["a"], "instructions": "b", "source_url": "", "source_name": None}
        return (
            patch.object(recipe_sync_commands, "get_recipe_sources", return_value=rows),
            patch.object(recipe_sync_commands, "forum_threads", AsyncMock(return_value=self.threads)),
            patch.object(recipe_sync_commands, "get_recipe_by_thread", return_value=full),
            patch.object(recipe_sync_commands, "get_recipe_tags", return_value=[]),
            patch.object(recipe_sync_commands, "create_recipe_embed", return_value="embed"),
            patch.object(recipe_sync_commands, "update_recipe_source",
                         side_effect=lambda *a: events.append(("db", a[0]))),
        )

    async def _invoke(self, rows, threads):
        events = []
        cog = self._cog(threads)
        interaction = self._interaction()
        for thread in threads.values():
            original = thread.starter.edit
            original.side_effect = lambda *a, _id=thread.id, **k: events.append(("card", _id))
        patches = self._run_patches(rows, events)
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        await RecipeSync.fix_sources.callback(cog, interaction)
        sent = " ".join(c.args[0] for c in interaction.followup.send.await_args_list)
        return events, sent

    async def test_updates_the_card_before_the_database(self):
        events, sent = await self._invoke([_row(10)], {10: _thread(10)})
        self.assertEqual(events, [("card", 10), ("db", 10)])
        self.assertIn("YouTube", sent)

    async def test_a_failed_card_edit_leaves_the_database_alone_so_it_retries(self):
        thread = _thread(10)
        events = []
        cog = self._cog({10: thread})
        interaction = self._interaction()
        thread.starter.edit.side_effect = RuntimeError("no permission")
        patches = self._run_patches([_row(10)], events)
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        await RecipeSync.fix_sources.callback(cog, interaction)
        self.assertEqual(events, [])
        self.assertIn("couldn't update", interaction.followup.send.await_args.args[0])

    async def test_a_recipe_whose_post_is_gone_is_reported_not_fatal(self):
        events, sent = await self._invoke([_row(10), _row(11)], {11: _thread(11)})
        self.assertEqual(events, [("card", 11), ("db", 11)])
        self.assertIn("wasn't found", sent)

    async def test_nothing_to_do_says_so(self):
        events, sent = await self._invoke([_row(10, name="Hand-entered")], {10: _thread(10)})
        self.assertEqual(events, [])
        self.assertIn("already labelled", sent)

    async def test_lists_sites_it_has_no_name_for_even_when_nothing_needs_fixing(self):
        row = _row(10, url="https://www.organizeyourselfskinny.com/tuna/", title="Tuna Salad")
        events, sent = await self._invoke([row], {10: _thread(10)})
        self.assertEqual(events, [])
        self.assertIn("organizeyourselfskinny.com", sent)
        self.assertIn("Tuna Salad", sent)

    async def test_stops_at_the_batch_limit_and_says_to_run_again(self):
        count = FIX_SOURCES_BATCH + 3
        threads = {i: _thread(i) for i in range(count)}
        events, sent = await self._invoke([_row(i) for i in range(count)], threads)
        self.assertEqual(len([e for e in events if e[0] == "db"]), FIX_SOURCES_BATCH)
        self.assertIn("3 more", sent)


class DeleteRecipeDatabaseTests(unittest.TestCase):
    def test_deleting_a_recipe_takes_its_tags_and_reviews_with_it(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recipes.db"
            for title, thread in [("Gone", 1), ("Kept", 2)]:
                save_recipe(Recipe(title=title, ingredients=["a"], instructions="b",
                                   source_url="", tags=["needs_review", "pasta"]), thread, path)
            add_cooking_log(1, __import__("datetime").datetime(2026, 7, 1, tzinfo=__import__("datetime").timezone.utc),
                            "Made", "favorite", "n", "t", 5, "Peyton", path)

            self.assertTrue(delete_recipe_by_thread(1, path))
            self.assertFalse(delete_recipe_by_thread(1, path))  # already gone

            self.assertIsNone(get_recipe_by_thread(1, path))
            self.assertEqual(get_recipe_tags(1, path), [])
            self.assertEqual(get_recipe_tags(2, path), ["needs_review", "pasta"])  # the other is untouched
            self.assertEqual([r["title"] for r in get_recipe_sources(path)], ["Kept"])


class ForgetButtonTests(unittest.IsolatedAsyncioTestCase):
    def _click(self, rows, fetch_effect):
        button = ForgetButton(rows)
        view = ReimportView([], rows)
        button._view = view
        interaction = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.response.send_message = AsyncMock()
        interaction.edit_original_response = AsyncMock()
        interaction.followup.send = AsyncMock()
        interaction.client.fetch_channel = AsyncMock(side_effect=fetch_effect)
        return button, interaction

    def _not_found(self):
        return discord.NotFound(MagicMock(status=404), "unknown channel")

    async def test_backs_up_first_then_forgets_a_post_discord_says_is_gone(self):
        order = []
        rows = [{"discord_thread_id": 5, "title": "Tarts"}]
        button, interaction = self._click(rows, self._not_found())
        with patch.object(recipe_sync_commands, "backup_database", side_effect=lambda: order.append("backup") or Path("recipes_1.db")),              patch.object(recipe_sync_commands, "delete_recipe_by_thread", side_effect=lambda t: order.append("delete") or True):
            await button.callback(interaction)
        self.assertEqual(order, ["backup", "delete"])
        self.assertIn("forgotten", interaction.edit_original_response.await_args.kwargs["content"])

    async def test_a_failed_backup_deletes_nothing(self):
        button, interaction = self._click([{"discord_thread_id": 5, "title": "Tarts"}], self._not_found())
        with patch.object(recipe_sync_commands, "backup_database", side_effect=OSError("disk full")),              patch.object(recipe_sync_commands, "delete_recipe_by_thread") as delete:
            await button.callback(interaction)
        delete.assert_not_called()
        self.assertIn("nothing was deleted", interaction.edit_original_response.await_args.kwargs["content"])

    async def test_a_post_that_may_still_exist_is_not_forgotten(self):
        # Not "Unknown Channel" - a hiccup or permissions problem isn't proof.
        button, interaction = self._click(
            [{"discord_thread_id": 5, "title": "Tarts"}], discord.HTTPException(MagicMock(status=500), "oops")
        )
        with patch.object(recipe_sync_commands, "backup_database", return_value=Path("b.db")),              patch.object(recipe_sync_commands, "delete_recipe_by_thread") as delete:
            await button.callback(interaction)
        delete.assert_not_called()
        self.assertIn("skipped", interaction.edit_original_response.await_args.kwargs["content"])

    async def test_a_second_click_does_not_run_it_twice(self):
        button, interaction = self._click([{"discord_thread_id": 5, "title": "Tarts"}], self._not_found())
        with patch.object(recipe_sync_commands, "backup_database", return_value=Path("b.db")) as backup,              patch.object(recipe_sync_commands, "delete_recipe_by_thread", return_value=True):
            await button.callback(interaction)
            await button.callback(interaction)
        backup.assert_called_once()

    async def test_post_is_gone_only_on_not_found(self):
        client = MagicMock()
        client.fetch_channel = AsyncMock(side_effect=self._not_found())
        self.assertTrue(await post_is_gone(client, 1))
        client.fetch_channel = AsyncMock(return_value=object())
        self.assertFalse(await post_is_gone(client, 1))

    def test_the_view_offers_forget_only_when_there_is_something_to_forget(self):
        self.assertEqual(len(ReimportView([], [{"discord_thread_id": 1, "title": "x"}]).children), 1)
        self.assertEqual(len(ReimportView([7], []).children), 1)
        self.assertEqual(len(ReimportView([7], [{"discord_thread_id": 1, "title": "x"}]).children), 2)


if __name__ == "__main__":
    unittest.main()
