"""Discord-limit checks for the pantry's buttons, without connecting to
Discord: every view is built at (or past) its maximum size and serialized
the way discord.py would send it. Discord rejects a message outright for
>25 components, >5 per row, >5 rows, or a label over 80 characters."""

import re
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from commands.pantry_commands import (
    AddToListButton,
    ChooseProductView,
    ExpiryActionButton,
    ExpiryNudgeView,
    PutAwayNudgeButton,
    PutAwayNudgeView,
    PutAwayView,
    RecipeConsumeView,
    ResultView,
    _claim,
    refresh_this_week_if_stale,
)
from services.pantry import PutAwayItem
from services.pantry_parser import ADD, CONSUME, PantryAction


def _buttons(view):
    rows = view.to_components()
    buttons = [component for row in rows for component in row["components"]]
    return rows, buttons


class ViewLimitsMixin:
    def assertSendable(self, view):
        rows, buttons = _buttons(view)
        self.assertLessEqual(len(rows), 5)
        self.assertLessEqual(len(buttons), 25)
        for row in rows:
            self.assertLessEqual(len(row["components"]), 5)
        for button in buttons:
            self.assertLessEqual(len(button.get("label", "")), 80, button.get("label"))
            self.assertLessEqual(len(button.get("custom_id", "")), 100)
        return buttons


class PantryViewTests(ViewLimitsMixin, unittest.IsolatedAsyncioTestCase):
    async def test_put_away_view_caps_at_25_components(self):
        long_name = "Organic Pasture Raised Large Brown Eggs With An Unreasonably Long Name Indeed"
        items = [
            PutAwayItem(str(index), "", "L", f"eggs {index}", None, {"sku": "1", "name": long_name})
            for index in range(40)
        ]
        buttons = self.assertSendable(PutAwayView(items, "L"))
        self.assertEqual(len(buttons), 25)
        self.assertEqual([button["label"] for button in buttons[-2:]], ["Put Away", "Cancel"])

    async def test_recipe_consume_view_starts_staples_unchecked(self):
        rows = [
            {"ingredient": "3 large eggs", "product": {"id": 1, "name": "Egg"}, "amount": 3.0},
            {"ingredient": "1 tsp kosher salt", "product": {"id": 2, "name": "Salt"}, "amount": 1},
        ]
        buttons = self.assertSendable(RecipeConsumeView(rows))
        self.assertEqual(buttons[0]["label"], "✅ 3× Egg")
        self.assertEqual(buttons[1]["label"], "⬜ Salt")

    async def test_expiry_nudge_view_is_restart_proof_and_capped(self):
        items = [{"product_id": index, "name": f"Chicken thigh {index}"} for index in range(1, 9)]
        buttons = self.assertSendable(ExpiryNudgeView(items))
        self.assertEqual(len(buttons), 10)  # 5 products x (freeze, used)
        for button in buttons:
            self.assertRegex(button["custom_id"], ExpiryActionButton.__discord_ui_compiled_template__)

    async def test_expiry_button_rebuilds_from_custom_id(self):
        template = ExpiryActionButton.__discord_ui_compiled_template__
        match = re.fullmatch(template, "pantry:expiry:used:42")
        button = await ExpiryActionButton.from_custom_id(MagicMock(), MagicMock(), match)
        self.assertEqual((button.kind, button.product_id), ("used", 42))

    async def test_put_away_nudge_is_restart_proof(self):
        buttons = self.assertSendable(PutAwayNudgeView())
        self.assertRegex(buttons[0]["custom_id"], PutAwayNudgeButton.__discord_ui_compiled_template__)

    async def test_result_view_variants(self):
        self.assertEqual(len(_buttons(ResultView([]))[1]), 0)
        self.assertEqual([b["label"] for b in _buttons(ResultView(["tx"]))[1]], ["Undo"])
        labels = [b["label"] for b in self.assertSendable(ResultView(["tx"], ["Milk", "Eggs"]))]
        self.assertEqual(labels, ["Undo", "🛒 Add Milk, Eggs to the list"])

    async def test_add_to_list_label_is_truncated(self):
        button = AddToListButton([f"Very long item name number {index}" for index in range(10)])
        self.assertLessEqual(len(button.label), 80)

    async def test_choose_product_view(self):
        candidates = [{"id": index, "name": f"Milk {index}"} for index in range(5)]
        labels = [b["label"] for b in self.assertSendable(ChooseProductView(PantryAction(ADD, "milk"), candidates))]
        self.assertEqual(labels, ["Milk 0", "Milk 1", "Milk 2", "➕ New: milk", "Cancel"])
        labels = [b["label"] for b in _buttons(ChooseProductView(PantryAction(CONSUME, "milk"), candidates))[1]]
        self.assertNotIn("➕ New: milk", labels)


class RefreshThisWeekTests(unittest.IsolatedAsyncioTestCase):
    def _patches(self, current, shown):
        grocy = MagicMock()
        grocy.__aenter__ = AsyncMock(return_value=grocy)
        grocy.__aexit__ = AsyncMock(return_value=False)
        return [
            patch.dict("os.environ", {"THIS_WEEK_CHANNEL_ID": "1", "GROCY_URL": "http://g", "GROCY_API_KEY": "k"}),
            patch("commands.pantry_commands.Grocy", return_value=grocy),
            patch("commands.pantry_commands.use_soon_text", new=AsyncMock(return_value=current)),
            patch("commands.pantry_commands.get_state", return_value=shown),
            patch("commands.pantry_commands.refresh_this_week", new=AsyncMock()),
        ]

    async def _run(self, current, shown, refresh_side_effect=None):
        patches = self._patches(current, shown)
        mocks = [p.start() for p in patches]
        self.addCleanup(lambda: [p.stop() for p in patches])
        refresh = mocks[-1]
        refresh.side_effect = refresh_side_effect
        await refresh_this_week_if_stale(MagicMock())
        return refresh

    async def test_rebuilds_when_use_soon_changed(self):
        refresh = await self._run("🟠 Ground beef — tomorrow", "")
        refresh.assert_awaited_once()

    async def test_leaves_it_alone_when_nothing_changed(self):
        refresh = await self._run("🟠 Ground beef — tomorrow", "🟠 Ground beef — tomorrow")
        refresh.assert_not_awaited()

    async def test_nothing_expiring_and_never_shown(self):
        refresh = await self._run(None, None)
        refresh.assert_not_awaited()

    async def test_never_raises(self):
        refresh = await self._run("🟠 Ground beef — tomorrow", "", refresh_side_effect=RuntimeError("discord down"))
        refresh.assert_awaited_once()


class ClaimTests(unittest.IsolatedAsyncioTestCase):
    async def test_second_click_is_turned_away(self):
        view = MagicMock(spec=[])
        first, second = MagicMock(), MagicMock()
        second.response.send_message = AsyncMock()

        self.assertTrue(await _claim(view, first))
        self.assertFalse(await _claim(view, second))
        second.response.send_message.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
