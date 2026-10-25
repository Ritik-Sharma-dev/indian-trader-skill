"""The live monitor engine: no look-ahead, entries, management, replay."""

import datetime as dt
import unittest

from _base import WorkspaceTest, session

from indtrader.core import clock
from indtrader.models.agents.live_monitor.engine import LiveEngine, new_state
from indtrader.models.agents.live_monitor.monitor import LiveMonitor, stats
from indtrader.models.agents.live_monitor.strategy import daily_regime

DAY = dt.date(2026, 10, 22)


def day_bars(closes, spread=2.0):
    return session("2026-10-22", closes, spread=spread)


class TestLiveEngine(WorkspaceTest):
    def setUp(self):
        super().setUp()
        self.engine = LiveEngine(self.cfg())
        self.prev = session("2026-10-21", [100 + i * 0.1 for i in range(75)])

    def test_orb_short_entry_and_stop(self):
        state = new_state("TEST", DAY)
        events = self.engine.process(state, self.prev, day_bars([100, 101, 99.5, 97.0, 96.5, 96.0, 99.0, 102.0, 103.0]))
        entry = next(e for e in events if e["type"] == "ENTRY")["trade"]
        self.assertEqual((entry["side"], entry["setup"], entry["time"]), ("short", "orb", "09:35"))
        self.assertIn("EXIT", [e["type"] for e in events])
        self.assertEqual(state["trades"][0]["exit_reason"], "stop")
        self.assertAlmostEqual(state["trades"][0]["r"], -1.0, places=2)

    def test_incremental_equals_batch(self):
        bars = day_bars([100, 101, 99.5, 97.0, 96.5, 96.0, 95.0, 94.0, 93.5, 94.0, 93.0, 92.0])
        batch = new_state("T", DAY)
        self.engine.process(batch, self.prev, bars)
        stepped = new_state("T", DAY)
        for k in range(1, len(bars) + 1):                       # one bar at a time, like live ticks
            self.engine.process(stepped, self.prev, bars[:k])
        strip = lambda s: [{k: v for k, v in t.items() if k != "best"} for t in s["trades"]]   # noqa: E731
        self.assertEqual(strip(batch), strip(stepped))
        self.assertEqual(batch["trade"] and batch["trade"]["entry"], stepped["trade"] and stepped["trade"]["entry"])

    def test_no_entry_outside_window_and_breakeven(self):
        late_cfg = dict(self.cfg(), no_entries_before="10:00")
        state = new_state("T", DAY)
        self.assertFalse([e for e in LiveEngine(late_cfg).process(state, self.prev, day_bars([100, 101, 99.5, 97.0, 96.5, 96.0]))
                          if e["type"] == "ENTRY"])
        state = new_state("T", DAY)
        events = self.engine.process(state, self.prev, day_bars([100, 101, 99.5, 97.0, 95.0, 93.0, 92.0], spread=0.5))
        if state["trade"]:
            self.assertLessEqual(state["trade"]["stop"], state["trade"]["entry"] + 0.05)
        self.assertTrue(any(e["type"] == "UPDATE" for e in events) or state["trades"])

    def test_late_signal_not_taken_live(self):
        state = new_state("T", DAY)
        events = self.engine.process(state, self.prev, day_bars([100, 101, 99.5, 97.0]), live=True, now=clock.parse_now("2026-10-22 09:50"))
        self.assertIsNone(state["trade"])
        self.assertTrue(any("missed" in e["text"] for e in events))

    def test_regime(self):
        self.assertEqual(daily_regime([100 + i for i in range(40)]), "up")
        self.assertEqual(daily_regime([140 - i for i in range(40)]), "down")
        self.assertIsNone(daily_regime([100] * 10))


class TestTradeManagement(WorkspaceTest):
    """Stops move on the move since entry, never on the day's extremes from before the trade."""

    def manage(self, bar, day_low, trade=None):
        from indtrader.models.agents.live_monitor.strategy import LiveStrategy
        trade = trade or {"side": "short", "entry": 100.0, "stop": 102.0, "init_stop": 102.0, "target": 96.0, "risk": 2.0}
        snap = {"close_t": dt.datetime(2026, 10, 22, 10, 30, tzinfo=clock.IST), "vwap": 101.0, "st_dir": -1, "atr": 1.0,
                "day_low": day_low, "day_high": 104.0}
        return LiveStrategy(self.cfg()).manage(trade, [bar], 0, snap), trade

    def test_pre_entry_low_does_not_move_the_stop(self):
        # a pullback short: the day's low (95) was made before entry at 100; the trade itself is only 0.5 in profit
        result, trade = self.manage({"o": 100.2, "h": 100.5, "l": 99.5, "c": 99.8}, day_low=95.0)
        self.assertIsNone(result)
        self.assertEqual(trade["stop"], 102.0)
        self.assertEqual(trade["best"], 0.5)

    def test_breakeven_and_trail_after_entry(self):
        result, trade = self.manage({"o": 99.5, "h": 99.6, "l": 97.9, "c": 98.2}, day_low=97.9)
        self.assertEqual(result, ("move-stop", 100.0))                  # +1R since entry: stop to breakeven
        result, trade = self.manage({"o": 98.2, "h": 98.3, "l": 96.9, "c": 97.2}, day_low=96.9, trade=trade)
        self.assertEqual(result, ("move-stop", 98.2))                   # beyond +1.5R: trail 1 ATR above the close


class TestLiveSnapshot(WorkspaceTest):
    def test_replay_22_oct(self):
        state, _ = LiveMonitor(self.ctx()).replay_day("NIFTY", DAY)
        first = state["trades"][0]
        self.assertEqual((first["side"], first["setup"], first["time"], first["entry"]), ("long", "orb", "10:25", 22725.7))
        self.assertEqual(first["exit"] if first["exit_reason"] == "stop" else first["stop"], 22624.25)

    def test_backtest_and_cli(self):
        days, trades = LiveMonitor(self.ctx()).backtest("NIFTY", 20)
        self.assertEqual(len(days), 20)
        summary = stats(trades)
        self.assertEqual(summary["trades"], len(trades))
        self.assertEqual(sum(summary["exits"].values()), len(trades))
        _, out, _ = self.cli("live", "replay", "NIFTY", "--date", "2026-10-22")
        self.assertIn("ACTION 10:25", out)
        _, out, _ = self.cli("live", "tick", "NIFTY", now="2026-10-20 11:00")
        self.assertIn("market closed", out)


if __name__ == "__main__":
    unittest.main()
