import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from googleapiclient.errors import HttpError

from commands import schedule_commands
from services import open_tasks
from services.open_tasks import (
    build_open_task_embeds,
    format_open_tasks,
    look_up_events,
    message_link,
    removed_note,
    summarize,
)

TZ = timezone(timedelta(hours=-5))
NOW = datetime(2026, 11, 14, 12, 0, tzinfo=TZ)
GUILD = 111


def _task(name="call vet", days_due_offset=None, **overrides):
    task = {
        "task_name": name,
        "message_id": 333,
        "channel_id": 222,
        "event_id": "e1",
        "calendar_id": "cal",
        "booked_at": (NOW - timedelta(days=30)).isoformat(),
        "booked_by": "Joe",
        "due": None if days_due_offset is None else NOW + timedelta(days=days_due_offset),
        "event_deleted": False,
        "message_deleted": False,
    }
    task.update(overrides)
    return task


class MessageLinkTests(unittest.TestCase):
    def test_builds_a_discord_jump_link(self):
        self.assertEqual(message_link(111, 222, 333), "https://discord.com/channels/111/222/333")


class FormatOpenTasksTests(unittest.TestCase):
    def test_links_the_task_name_to_its_message(self):
        line = format_open_tasks([_task("clean kitchen cart", -70)], NOW, GUILD)[0]

        self.assertIn("[clean kitchen cart](https://discord.com/channels/111/222/333)", line)
        self.assertIn("Overdue", line)
        self.assertIn("booked by Joe", line)

    def test_upcoming_task_is_not_called_overdue(self):
        line = format_open_tasks([_task("dust shelves", 2)], NOW, GUILD)[0]

        self.assertNotIn("Overdue", line)

    def test_a_deleted_calendar_event_is_flagged_but_the_task_is_kept(self):
        line = format_open_tasks([_task("ghost", event_deleted=True)], NOW, GUILD)[0]

        self.assertIn("calendar event deleted", line)
        self.assertIn("[ghost](", line)

    def test_unknown_due_time_is_said_plainly(self):
        line = format_open_tasks([_task("mystery")], NOW, GUILD)[0]

        self.assertIn("due time unknown", line)

    def test_most_overdue_comes_first_and_undated_last(self):
        tasks = [
            _task("recent", -2),
            _task("undated"),
            _task("ancient", -90),
            _task("ghost", event_deleted=True),
        ]

        names = [line.split("]")[0].lstrip("• [") for line in format_open_tasks(tasks, NOW, GUILD)]

        self.assertEqual(names[:2], ["ancient", "recent"])
        self.assertEqual(set(names[2:]), {"undated", "ghost"})

    def test_markdown_in_a_name_cannot_break_the_link(self):
        line = format_open_tasks([_task("fix [shelf] *now*", -1)], NOW, GUILD)[0]

        self.assertIn(r"[fix \[shelf\] \*now\*](https://discord.com/channels/111/222/333)", line)

    def test_empty(self):
        self.assertEqual(format_open_tasks([], NOW, GUILD), [])


class SummarizeTests(unittest.TestCase):
    def test_counts_total_and_past_due(self):
        summary = summarize([_task("a", -5), _task("b", -1), _task("c", 3)], NOW)

        self.assertIn("**3** tasks never completed", summary)
        self.assertIn("2 past due", summary)

    def test_singular_and_no_extras_when_nothing_is_overdue(self):
        self.assertEqual(summarize([_task("a", 3)], NOW), "**1** task never completed")


class RemovedNoteTests(unittest.TestCase):
    def test_names_the_removed_tasks_and_says_calendar_events_are_untouched(self):
        note = removed_note(["Archive wedding website", "UPS package"])

        self.assertIn("Removed **2** tasks", note)
        self.assertIn("Archive wedding website, UPS package", note)
        self.assertIn("calendar events", note)

    def test_singular(self):
        self.assertIn("Removed **1** task whose", removed_note(["only one"]))

    def test_markdown_in_names_is_escaped(self):
        self.assertIn(r"fix \*it\*", removed_note(["fix *it*"]))

    def test_a_huge_cleanup_is_capped(self):
        note = removed_note([f"task number {i}" for i in range(500)])

        self.assertLess(len(note), 700)
        self.assertIn("…", note)


class BuildEmbedsTests(unittest.TestCase):
    def test_a_short_list_is_one_embed_with_title_summary_and_footer(self):
        (embed,) = build_open_task_embeds(["• a", "• b"], "**2** tasks never completed")

        self.assertEqual(embed.title, "📌 Unfinished tasks")
        self.assertIn("**2** tasks never completed", embed.description)
        self.assertIn("• a", embed.description)
        self.assertIn("✅", embed.footer.text)

    def test_the_removed_note_goes_in_the_header_of_the_first_embed(self):
        (embed,) = build_open_task_embeds(["• a"], "**1** task never completed", removed=["gone one"])

        self.assertIn("Removed **1** task", embed.description)
        self.assertLess(embed.description.index("Removed"), embed.description.index("• a"))

    def test_no_removed_note_when_nothing_was_removed(self):
        (embed,) = build_open_task_embeds(["• a"], "**1** task never completed", removed=[])

        self.assertNotIn("Removed", embed.description)

    def test_a_long_list_splits_across_embeds_within_discords_limit(self):
        lines = [f"• {'x' * 150} {i}" for i in range(80)]

        embeds = build_open_task_embeds(lines, "**80** tasks never completed")

        self.assertGreater(len(embeds), 1)
        self.assertTrue(all(len(e.description) <= 4096 for e in embeds))
        self.assertEqual(embeds[0].title, "📌 Unfinished tasks")
        self.assertIsNone(embeds[1].title)
        self.assertIsNone(embeds[0].footer.text)
        self.assertIsNotNone(embeds[-1].footer.text)
        joined = "\n".join(e.description for e in embeds)
        self.assertEqual(sum(f" {i}" in joined for i in range(80)), 80)  # nothing lost


def _http_error(status):
    response = MagicMock()
    response.status = status
    response.reason = "x"
    return HttpError(response, b"")


RAW = {"summary": "call vet", "start": {"dateTime": "2026-11-13T09:00:00-05:00"}, "end": {"dateTime": "2026-11-13T09:30:00-05:00"}}


class LookUpEventsTests(unittest.TestCase):
    def _rows(self):
        return [dict(_task(n), event_id=n) for n in ("ok", "gone", "cancelled", "flaky")]

    def _get_event(self, event_id, calendar_id, service=None):
        if event_id == "ok":
            return RAW
        if event_id == "gone":
            raise _http_error(404)
        if event_id == "cancelled":
            return {"status": "cancelled"}
        raise _http_error(500)

    def test_keeps_every_task_and_flags_deleted_events(self):
        with patch.object(open_tasks, "get_event", side_effect=self._get_event):
            results = {t["event_id"]: t for t in look_up_events(self._rows(), service=object())}

        self.assertEqual(len(results), 4)
        self.assertIsNotNone(results["ok"]["due"])
        self.assertFalse(results["ok"]["event_deleted"])
        self.assertTrue(results["gone"]["event_deleted"])
        self.assertTrue(results["cancelled"]["event_deleted"])

    def test_a_calendar_error_leaves_due_unknown_without_claiming_it_was_deleted(self):
        with patch.object(open_tasks, "get_event", side_effect=self._get_event):
            flaky = [t for t in look_up_events(self._rows(), service=object()) if t["event_id"] == "flaky"][0]

        self.assertIsNone(flaky["due"])
        self.assertFalse(flaky["event_deleted"])

    def test_no_rows_means_no_calendar_connection(self):
        with patch.object(open_tasks, "get_service", side_effect=AssertionError("must not be called")):
            self.assertEqual(look_up_events([]), [])

    def test_one_calendar_connection_is_shared_across_all_tasks(self):
        with patch.object(open_tasks, "get_event", return_value=RAW) as get_event, \
             patch.object(open_tasks, "get_service", return_value="the-service") as get_service:
            look_up_events(self._rows())

        get_service.assert_called_once()
        self.assertTrue(all(call.kwargs["service"] == "the-service" for call in get_event.call_args_list))


def _not_found(code):
    """discord.NotFound as Discord really sends it: a 404 with a JSON error code."""
    return discord.NotFound(MagicMock(status=404, reason="Not Found"), {"code": code, "message": "x"})


def _bot_with_channel(fetch_message):
    channel = MagicMock(spec=discord.TextChannel)
    channel.fetch_message = fetch_message
    bot = MagicMock()
    bot.get_channel.return_value = channel
    return bot


class CollectOpenTasksTests(unittest.IsolatedAsyncioTestCase):
    async def _collect(self, bot):
        with patch.object(schedule_commands, "look_up_events", return_value=[_task("a")]):
            (task,) = await schedule_commands.collect_open_tasks(bot, [_task("a")])
        return task

    async def test_flags_a_task_whose_message_is_unknown_to_discord(self):
        task = await self._collect(_bot_with_channel(AsyncMock(side_effect=_not_found(10008))))

        self.assertTrue(task["message_deleted"])

    async def test_flags_a_task_whose_channel_is_gone(self):
        task = await self._collect(_bot_with_channel(AsyncMock(side_effect=_not_found(10003))))

        self.assertTrue(task["message_deleted"])

    async def test_some_other_404_is_not_taken_as_a_deleted_message(self):
        # This answer gets a task DELETED, so only Discord's explicit "unknown
        # message/channel" counts. (10015 = Unknown Webhook.)
        task = await self._collect(_bot_with_channel(AsyncMock(side_effect=_not_found(10015))))

        self.assertFalse(task["message_deleted"])

    async def test_a_discord_hiccup_is_not_mistaken_for_a_deleted_message(self):
        boom = discord.HTTPException(MagicMock(status=500, reason="boom"), "boom")
        task = await self._collect(_bot_with_channel(AsyncMock(side_effect=boom)))

        self.assertFalse(task["message_deleted"])

    async def test_no_access_is_not_mistaken_for_a_deleted_message(self):
        forbidden = discord.Forbidden(MagicMock(status=403, reason="Forbidden"), {"code": 50001, "message": "Missing Access"})
        task = await self._collect(_bot_with_channel(AsyncMock(side_effect=forbidden)))

        self.assertFalse(task["message_deleted"])

    async def test_an_existing_message_is_not_flagged(self):
        task = await self._collect(_bot_with_channel(AsyncMock(return_value=object())))

        self.assertFalse(task["message_deleted"])

    async def test_an_uncached_channel_is_not_flagged(self):
        bot = MagicMock()
        bot.get_channel.return_value = None

        self.assertFalse((await self._collect(bot))["message_deleted"])

    async def test_a_calendar_outage_still_returns_the_tasks(self):
        bot = _bot_with_channel(AsyncMock())
        with patch.object(schedule_commands, "look_up_events", side_effect=RuntimeError("calendar down")):
            tasks = await schedule_commands.collect_open_tasks(bot, [_task("a"), _task("b")])

        self.assertEqual(len(tasks), 2)
        self.assertTrue(all(t["due"] is None and not t["event_deleted"] for t in tasks))


class OpenTasksCommandTests(unittest.IsolatedAsyncioTestCase):
    def _interaction(self, guild_id=GUILD):
        interaction = MagicMock()
        interaction.guild_id = guild_id
        interaction.response.defer = AsyncMock()
        interaction.response.send_message = AsyncMock()
        interaction.followup.send = AsyncMock()
        return interaction

    async def _run(self, interaction, rows, tasks=None):
        # Skip __init__: it starts the cog's background loops, and the command only needs .bot
        cog = object.__new__(schedule_commands.Schedule)
        cog.bot = MagicMock()
        with patch.object(schedule_commands, "get_open_booked_tasks", return_value=rows), \
             patch.object(schedule_commands, "collect_open_tasks", AsyncMock(return_value=tasks or [])), \
             patch.object(schedule_commands, "delete_open_booked_task") as delete:
            await schedule_commands.Schedule.open_tasks.callback(cog, interaction)
        return delete

    def _sent_text(self, interaction):
        parts = []
        for call in interaction.followup.send.await_args_list:
            parts.append(call.args[0] if call.args else "")
            if "embed" in call.kwargs:
                parts.append(call.kwargs["embed"].description)
        return "\n".join(parts)

    async def test_refuses_outside_a_server(self):
        interaction = self._interaction(guild_id=None)

        await self._run(interaction, [])

        interaction.response.send_message.assert_awaited_once()
        interaction.response.defer.assert_not_awaited()

    async def test_says_so_when_everything_is_done(self):
        interaction = self._interaction()

        await self._run(interaction, [])

        self.assertIn("completed", interaction.followup.send.await_args.args[0])

    async def test_lists_open_tasks_privately_with_working_links(self):
        interaction = self._interaction()
        tasks = [_task("clean kitchen cart", -70)]

        delete = await self._run(interaction, [{"x": 1}], tasks)

        interaction.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        call = interaction.followup.send.await_args
        self.assertTrue(call.kwargs["ephemeral"])
        self.assertIn("https://discord.com/channels/111/222/333", call.kwargs["embed"].description)
        delete.assert_not_called()

    async def test_tasks_whose_message_was_deleted_are_removed_from_the_database_and_not_listed(self):
        interaction = self._interaction()
        tasks = [
            _task("kept task", -5, message_id=333),
            _task("deleted one", -50, message_id=444, message_deleted=True),
        ]

        delete = await self._run(interaction, [{"x": 1}, {"x": 2}], tasks)

        delete.assert_called_once_with(444)
        text = self._sent_text(interaction)
        self.assertIn("kept task", text)
        self.assertNotIn("/444)", text)  # no (dead) link to the deleted one
        self.assertIn("Removed **1** task", text)
        self.assertIn("deleted one", text)

    async def test_when_every_open_task_was_deleted_it_says_so_instead_of_an_empty_list(self):
        interaction = self._interaction()
        tasks = [_task("gone", -5, message_id=444, message_deleted=True)]

        delete = await self._run(interaction, [{"x": 1}], tasks)

        delete.assert_called_once_with(444)
        text = self._sent_text(interaction)
        self.assertIn("No unfinished tasks left", text)
        self.assertIn("Removed **1** task", text)

    async def test_no_removed_note_when_nothing_was_deleted(self):
        interaction = self._interaction()

        await self._run(interaction, [{"x": 1}], [_task("fine", -5)])

        self.assertNotIn("Removed", self._sent_text(interaction))


class MessageDeleteListenerTests(unittest.IsolatedAsyncioTestCase):
    def _cog(self):
        cog = object.__new__(schedule_commands.Schedule)
        cog.bot = MagicMock()
        return cog

    async def test_deleting_a_tasks_message_drops_the_open_task(self):
        with patch.object(schedule_commands, "delete_open_booked_task", return_value=True) as delete:
            await self._cog().on_raw_message_delete(SimpleNamespace(message_id=333))

        delete.assert_called_once_with(333)

    async def test_deleting_any_other_message_is_harmless(self):
        with patch.object(schedule_commands, "delete_open_booked_task", return_value=False) as delete:
            await self._cog().on_raw_message_delete(SimpleNamespace(message_id=999))

        delete.assert_called_once_with(999)

    async def test_a_bulk_delete_drops_every_matching_open_task(self):
        payload = SimpleNamespace(message_ids={1, 2, 3})
        with patch.object(schedule_commands, "delete_open_booked_task", return_value=False) as delete:
            await self._cog().on_raw_bulk_message_delete(payload)

        self.assertEqual({call.args[0] for call in delete.call_args_list}, {1, 2, 3})


if __name__ == "__main__":
    unittest.main()
