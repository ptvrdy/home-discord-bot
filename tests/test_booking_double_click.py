import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from commands import schedule_commands
from commands.schedule_commands import TaskAlternativeButton, TaskAlternativesView, TaskSlotView

START = datetime(2026, 11, 20, 18, 0)
END = START + timedelta(minutes=30)


def _click():
    interaction = MagicMock()
    interaction.response.defer = AsyncMock()
    return interaction


class DoubleClickTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_second_click_on_confirm_books_nothing_and_changes_nothing(self):
        view = TaskSlotView("Dishes", START, END, START.date(), 1, START.date())
        with patch.object(schedule_commands, "_confirm_and_book", AsyncMock()) as book:
            first, second = _click(), _click()
            await view.confirm.callback(first)
            await view.confirm.callback(second)

        book.assert_awaited_once()
        second.response.defer.assert_awaited_once()  # acknowledged, so no "interaction failed"
        second.edit_original_response.assert_not_called()  # the success message is left alone

    async def test_a_second_click_on_an_alternative_time_is_ignored_too(self):
        view = TaskAlternativesView("Dishes", [(START, END)], 1, START.date())
        button = next(item for item in view.children if isinstance(item, TaskAlternativeButton))
        with patch.object(schedule_commands, "_confirm_and_book", AsyncMock()) as book:
            await button.callback(_click())
            await button.callback(_click())
        book.assert_awaited_once()

    async def test_confirm_and_alternatives_in_different_messages_are_independent(self):
        one = TaskSlotView("A", START, END, START.date(), 1, START.date())
        two = TaskSlotView("B", START, END, START.date(), 1, START.date())
        with patch.object(schedule_commands, "_confirm_and_book", AsyncMock()) as book:
            await one.confirm.callback(_click())
            await two.confirm.callback(_click())
        self.assertEqual(book.await_count, 2)


if __name__ == "__main__":
    unittest.main()
