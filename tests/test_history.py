"""One-month behaviour statistics and the profit-goal table."""

import unittest

from _base import WorkspaceTest

from indtrader.models.analytics import history
from indtrader.models.analytics.history import MarketHistory
from indtrader.models.trading.charges import charges
from indtrader.models.trading.sizing import PositionSizer

LATE = "2026-10-22 23:30"


class TestHistory(WorkspaceTest):
    def test_day_types(self):
        self.assertEqual(history.day_type(100, 110, 99, 109.5), "trend-up")
        self.assertEqual(history.day_type(110, 111, 100, 100.5), "trend-down")
        self.assertEqual(history.day_type(100, 105, 95, 100.5), "range")
        self.assertEqual(history.day_type(100, 105, 99, 103), "normal")

    def test_streaks(self):
        self.assertEqual(history.streaks([{"change_pct": x} for x in (1, 1, -1, -1, -1, 1, -1, -1)]), (2, 3, -2))

    def test_nifty_month_snapshot(self):
        summary = MarketHistory(self.market(), self.cfg()).analyse("NIFTY", 22, self.now(LATE))
        self.assertEqual((summary["sessions"], summary["to"]), (22, "2026-10-22"))
        days = {d["date"]: d for d in summary["days"]}
        self.assertAlmostEqual(days["2026-10-22"]["close"], 22687.65)
        self.assertAlmostEqual(days["2026-10-21"]["close"], 22811.35)      # the hole Yahoo left, rebuilt from 5-minute bars
        self.assertAlmostEqual(days["2026-10-22"]["change_pct"], -0.5423, places=3)
        self.assertNotIn("2026-10-20", days)                                # Dussehra
        self.assertEqual(summary["up_days"] + summary["down_days"], 22)
        self.assertEqual(summary["or_broke_up_first"] + summary["or_broke_down_first"] + summary["or_no_break"], summary["or_sessions"])
        self.assertEqual(sum(summary["high_time_buckets"].values()), summary["or_sessions"])
        self.assertEqual(summary["current_streak"], -3)

    def test_cli(self):
        code, out, err = self.cli("history", "NIFTY", "BANKNIFTY", now=LATE)
        self.assertEqual(code, 0, err)
        self.assertIn("Opening range (first 15 min)", out)
        self.assertIn("Day's LOW made in", out)


class TestProfitTarget(WorkspaceTest):
    def test_target_table(self):
        self.cli("entry", "check", "NIFTY")
        self.cli("plan", "make", "--target", "1.5R")
        table = PositionSizer(self.cfg()).target_table(self.read("plan.json"), 3500)
        one = table["rows"][0]
        self.assertEqual((one["lots"], one["qty"]), (1, 65))
        costs = charges("option", table["entry"] * one["qty"], (table["entry"] + one["move_needed"]) * one["qty"])["total"]
        self.assertAlmostEqual(one["move_needed"] * one["qty"] - costs, 3500, delta=1.0)    # the move nets the goal
        forty = next(r for r in table["rows"] if r["lots"] == 40)
        self.assertGreater(forty["loss_at_stop"], 30 * 3500)
        self.assertLess(forty["move_needed"], 2.0)
        _, out, _ = self.cli("budget", "target", "--profit", "3500")
        self.assertIn("over max loss", out)


if __name__ == "__main__":
    unittest.main()
