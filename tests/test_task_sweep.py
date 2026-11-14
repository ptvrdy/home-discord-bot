import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from commands import schedule_commands
from services.task_sweep import recent_open_tasks

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)


def _task(days_ago: float, name: str = "call vet") -> dict:
    return {
        "message_id": 111,
        "channel_id": 222,
        "task_name": name,
        "event_id": "event-1",
        "calendar_id": "cal-1",
        "booked_at": (NOW - timedelta(days=days_ago)).isoformat(),
        "booked_by": "Peyton",
    }


class RecentOpenTasksTests(unittest.TestCase):
    def test_keeps_tasks_inside_the_window_and_drops_older_ones(self):
        tasks = [_task(1, "new"), _task(13.9, "edge"), _task(14.1, "old"), _task(70, "ancient")]

        kept = recent_open_tasks(tasks, NOW, window_days=14)

        self.assertEqual([t["task_name"] for t in kept], ["new", "edge"])

    def test_empty_list(self):
        self.assertEqual(recent_open_tasks([], NOW, 14), [])

    def test_naive_booked_at_is_read_in_nows_time_zone(self):
        task = _task(1)
        task["booked_at"] = (NOW - timedelta(days=1)).replace(tzinfo=None).isoformat()

        self.assertEqual(recent_open_tasks([task], NOW, 14), [task])


class FakeReaction:
    def __init__(self, emoji, users):
        self.emoji = emoji
        self._users = users

    def users(self):
        async def generate():
            for user in self._users:
                yield user

        return generate()


def _person(name):
    return SimpleNamespace(bot=False, display_name=name)


ROSIE = SimpleNamespace(bot=True, display_name="Rosie")


def _bot_and_channel(reactions, fetch_error=None):
    message = SimpleNamespace(reactions=reactions, edit=AsyncMock())
    channel = MagicMock(spec=discord.TextChannel)
    channel.fetch_message = AsyncMock(return_value=message, side_effect=fetch_error)
    bot = MagicMock()
    bot.get_channel.return_value = channel
    return bot, channel, message


class CatchUpTaskTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, reactions, **kwargs):
        bot, channel, message = _bot_and_channel(reactions, **kwargs)
        task = _task(3)
        with patch.object(schedule_commands, "complete_booked_task", AsyncMock(return_value=True)) as complete:
            result = await schedule_commands.catch_up_task(bot, task)
        return result, complete, bot, channel, task

    async def test_completes_when_a_person_checked_it(self):
        result, complete, bot, channel, task = await self._run([FakeReaction("✅", [ROSIE, _person("Joe")])])

        self.assertTrue(result)
        complete.assert_awaited_once_with(bot, channel, task, "Joe")

    async def test_ignores_rosies_own_pre_added_check_mark(self):
        result, complete, *_ = await self._run([FakeReaction("✅", [ROSIE])])

        self.assertFalse(result)
        complete.assert_not_awaited()

    async def test_no_check_mark_at_all(self):
        result, complete, *_ = await self._run([FakeReaction("👍", [_person("Joe")])])

        self.assertFalse(result)
        complete.assert_not_awaited()

    async def test_ignores_other_emoji_when_looking_for_the_check_mark(self):
        result, complete, *_ = await self._run(
            [FakeReaction("👍", [_person("Sam")]), FakeReaction("✅", [ROSIE, _person("Joe")])]
        )

        self.assertTrue(result)
        self.assertEqual(complete.await_args.args[3], "Joe")

    async def test_a_deleted_message_is_skipped_quietly(self):
        gone = discord.NotFound(MagicMock(status=404, reason="Not Found"), "gone")
        result, complete, *_ = await self._run([], fetch_error=gone)

        self.assertFalse(result)
        complete.assert_not_awaited()

    async def test_unknown_channel_is_skipped_without_fetching(self):
        bot = MagicMock()
        bot.get_channel.return_value = None
        with patch.object(schedule_commands, "complete_booked_task", AsyncMock()) as complete:
            self.assertFalse(await schedule_commands.catch_up_task(bot, _task(3)))
        complete.assert_not_awaited()

    async def test_reports_what_completing_returned(self):
        # complete_booked_task returns False if the live handler beat the sweep to it.
        bot, channel, message = _bot_and_channel([FakeReaction("✅", [_person("Joe")])])
        with patch.object(schedule_commands, "complete_booked_task", AsyncMock(return_value=False)):
            self.assertFalse(await schedule_commands.catch_up_task(bot, _task(3)))


RAW_EVENT = {
    "summary": "call vet",
    "start": {"dateTime": "2026-09-06T14:30:00-04:00"},
    "end": {"dateTime": "2026-09-06T15:00:00-04:00"},
}


class CompleteBookedTaskTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mark = patch.object(schedule_commands, "mark_task_completed", return_value={"id": 1}).start()
        self.get_event = patch.object(schedule_commands, "get_event", return_value=RAW_EVENT).start()
        self.rename = patch.object(schedule_commands, "rename_event").start()
        self.refresh = patch.object(schedule_commands, "refresh_this_week", AsyncMock()).start()
        self.addCleanup(patch.stopall)
        self.bot, self.channel, self.message = _bot_and_channel([])

    async def test_already_completed_does_nothing_more(self):
        self.mark.return_value = None

        result = await schedule_commands.complete_booked_task(self.bot, self.channel, _task(3), "Joe")

        self.assertFalse(result)
        self.get_event.assert_not_called()
        self.message.edit.assert_not_awaited()
        self.rename.assert_not_called()
        self.refresh.assert_not_awaited()

    async def test_records_who_completed_it_against_the_right_message(self):
        await schedule_commands.complete_booked_task(self.bot, self.channel, _task(3), "Joe")

        args = self.mark.call_args.args
        self.assertEqual(args[0], 111)
        self.assertEqual(args[2], "Joe")

    async def test_updates_message_calendar_and_this_week(self):
        result = await schedule_commands.complete_booked_task(self.bot, self.channel, _task(3), "Joe")

        self.assertTrue(result)
        content = self.message.edit.await_args.kwargs["content"]
        self.assertIn("call vet", content)
        self.assertIn("marked done by Joe", content)
        self.assertIn("2:30 PM", content)  # the event's CURRENT time, not the stale message text
        self.assertIsNone(self.message.edit.await_args.kwargs["view"])
        self.rename.assert_called_once_with("event-1", "✅ call vet", calendar_id="cal-1")
        self.refresh.assert_awaited_once_with(self.bot)

    async def test_still_completes_when_the_event_cant_be_looked_up(self):
        self.get_event.side_effect = RuntimeError("calendar down")

        result = await schedule_commands.complete_booked_task(self.bot, self.channel, _task(3), "Joe")

        self.assertTrue(result)
        self.assertEqual(
            self.message.edit.await_args.kwargs["content"], "✅ **call vet** — marked done by Joe."
        )

    async def test_a_failed_message_edit_does_not_block_the_calendar_or_this_week(self):
        self.message.edit.side_effect = discord.HTTPException(MagicMock(status=500, reason="boom"), "boom")

        result = await schedule_commands.complete_booked_task(self.bot, self.channel, _task(3), "Joe")

        self.assertTrue(result)
        self.rename.assert_called_once()
        self.refresh.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
