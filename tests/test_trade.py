"""The trade chain: scanner -> entry -> plan -> Time Machine -> sizing ->
risk -> paper -> alerts, on synthetic bars and on the 22 Oct 2026 snapshot."""

import datetime as dt
import json
import os
import random
import statistics
import unittest

from _base import NOW, WorkspaceTest, session

from indtrader.core import clock
from indtrader.core.errors import DataError, ValidationError
from indtrader.models.trading import alerts, planner, scanner, timemachine
from indtrader.models.trading.charges import charges
from indtrader.models.trading.entry import EntryRequest, EntryTimer
from indtrader.models.trading.risk import RiskManager
from indtrader.models.trading.timemachine import TimeMachine


class TestScanner(WorkspaceTest):
    def test_daily_setups(self):
        self.assertIn("breakout_20d", scanner.find_setups([100.0] * 40 + [101, 102, 103, 104, 105]))
        self.assertIn("breakdown_20d", scanner.find_setups([100.0] * 40 + [99, 98, 97, 96, 95]))
        flag = [100.0] * 30 + [100 + 2 * i for i in range(1, 11)] + [120, 120.5, 119.8, 120.2, 120.4]
        self.assertIn("bull_flag", scanner.find_setups(flag))
        self.assertEqual(scanner.find_setups([100.0] * 10), [])

    def test_orb_eval(self):
        result = scanner.orb_eval(session("2026-10-22", [100, 101, 99.5, 100.5, 102.5, 103]))
        self.assertEqual((result["side"], result["trigger_time"], result["or_high"]), ("long", "09:40", 102.0))
        self.assertEqual(scanner.orb_eval(session("2026-10-22", [100, 101, 99.5, 100.5, 97.5]))["side"], "short")

    def test_orb_scan_snapshot(self):
        code, out, _ = self.cli("scan", "orb", "--symbols", "RELIANCE,HDFCBANK,ICICIBANK,SBIN,INFY,BAJFINANCE", "--at", "10:00")
        self.assertEqual(code, 0, out)
        got = {(h["symbol"], h["side"], h["trigger_time"], h["trigger_price"]) for h in self.read("watchlist.json")["hits"]}
        self.assertEqual(got, {("BAJFINANCE", "long", "09:35", 921.0), ("HDFCBANK", "short", "09:35", 695.0),
                               ("RELIANCE", "short", "09:35", 1191.3)})

    def test_daily_scan_snapshot(self):
        symbols = ("RELIANCE,TCS,INFY,HDFCBANK,ICICIBANK,SBIN,ITC,LT,AXISBANK,KOTAKBANK,BHARTIARTL,HINDUNILVR,MARUTI,"
                   "SUNPHARMA,TITAN,BAJFINANCE,WIPRO,ONGC,NTPC,NESTLEIND")
        code, _, _ = self.cli("scan", "daily", "--symbols", symbols)
        self.assertEqual(code, 0)
        hits = {h["symbol"]: h for h in self.read("watchlist.json")["hits"]}
        self.assertEqual(hits["ICICIBANK"]["setups"], ["breakout_20d"])
        self.assertEqual(hits["NESTLEIND"]["setups"], ["breakdown_20d", "oversold"])
        self.assertEqual(hits["SBIN"]["lean"], "long")


class TestEntry(WorkspaceTest):
    def timer(self, **overrides):
        cfg = self.cfg()
        cfg.update(overrides)
        return EntryTimer(self.market(), cfg)

    def test_synthetic_breakout_and_window(self):
        day = "2026-10-22"
        bars = session(day, [100, 101, 99.5, 100.5, 102.5, 103])
        result = self.timer().evaluate(bars, clock.parse_now(day + " 09:45"), EntryRequest())
        self.assertEqual((result["status"], result["side"], result["trigger_time"], result["trigger_price"]), ("triggered", "long", "09:40", 102.5))
        self.assertEqual(self.timer().evaluate(bars[:3], clock.parse_now(day + " 09:30"), EntryRequest())["status"], "waiting")
        self.assertIn("forming", self.timer().evaluate(bars[:2], clock.parse_now(day + " 09:25"), EntryRequest())["why"])
        flat = session(day, [100, 101, 99.5] + [100] * 70)
        self.assertEqual(self.timer().evaluate(flat, clock.parse_now(day + " 15:00"), EntryRequest())["status"], "expired")

    def test_missing_first_bar_is_no_data(self):
        bars = session("2026-10-22", [100, 101, 99.5, 100.5, 102.5, 103])[1:]
        result = self.timer().evaluate(bars, clock.parse_now("2026-10-22 09:50"), EntryRequest())
        self.assertEqual(result["status"], "no-data")

    def test_level_setup_needs_side(self):
        bars = session("2026-10-22", [100, 101, 99.5, 100.5, 102.5])
        moment = clock.parse_now("2026-10-22 09:45")
        with self.assertRaises(ValidationError):
            self.timer().evaluate(bars, moment, EntryRequest(setup="level", level=102))
        result = self.timer().evaluate(bars, moment, EntryRequest(setup="level", side="long", level=102))
        self.assertEqual(result["status"], "triggered")

    def test_snapshot_nifty(self):
        code, out, _ = self.cli("entry", "check", "NIFTY")
        self.assertEqual(code, 0, out)
        found = self.read("entry.json")
        self.assertEqual((found["side"], found["trigger_time"], found["trigger_price"]), ("long", "10:25", 22725.7))
        self.assertEqual((found["or_low"], found["or_high"]), (22558.05, 22690.45))
        code, out, _ = self.cli("entry", "check", "NIFTY", "--no-write", now="2026-10-22 09:50")
        self.assertEqual(code, 1)
        self.assertIn("WAITING", out)


class TestPlan(WorkspaceTest):
    def test_levels(self):
        lv = planner.levels("long", 22725.70, "or-mid", "1.5R", 22690.45, 22558.05)
        self.assertEqual((lv["stop"], lv["target"], lv["risk_points"]), (22624.25, 22877.90, 101.45))
        lv = planner.levels("short", 1191.30, "or-opposite", "2R", 1204.20, 1193.20)
        self.assertEqual((lv["stop"], lv["target"]), (1204.20, 1165.50))
        lv = planner.levels("long", 100.0, "pct:1", "2R")
        self.assertEqual((lv["stop"], lv["target"]), (99.0, 102.0))

    def test_refusals(self):
        for args in (("long", 100, "price:101", "2R"), ("long", 22725.7, "points:5", "2R"), ("long", 100, "or-mid", "2R")):
            with self.assertRaises(ValidationError, msg=str(args)):
                planner.levels(*args)
        with self.assertRaises(ValidationError):
            planner.parse_stop("trailing")
        with self.assertRaises(DataError):
            planner.levels("long", 100, "atr:1.5", "2R")

    def test_option_plan_snapshot(self):
        self.cli("entry", "check", "NIFTY")
        code, _, err = self.cli("plan", "make", "--target", "1.5R")
        self.assertEqual(code, 0, err)
        instrument = self.read("plan.json")["instrument"]
        self.assertEqual(instrument["tradingsymbol"], "NIFTY 27OCT26 22700 CE")
        premium = instrument["premium"]
        self.assertEqual((instrument["lot"], premium["entry"], premium["stop"], premium["target"]), (65, 181.0, 128.75, 277.7))
        self.assertEqual(premium["market_premium"], 160.30)        # repriced from spot 22687.65 to the entry 22725.70
        self.assertEqual(instrument["risk_per_lot"], 3396.25)

    def test_untriggered_entry_is_refused(self):
        with open(os.path.join(self.home, "entry.json"), "w") as fh:
            json.dump({"symbol": "NIFTY", "status": "waiting"}, fh)
        code, _, err = self.cli("plan", "make")
        self.assertEqual(code, 1)
        self.assertIn("has not triggered", err)


class TestTimeMachine(WorkspaceTest):
    def setUp(self):
        super().setUp()
        self.cli("entry", "check", "NIFTY")
        self.cli("plan", "make", "--target", "1.5R")
        self.plan = self.read("plan.json")
        self.machine = TimeMachine(self.market(), self.cfg())

    def test_reproducible_and_consistent(self):
        first = self.machine.run(self.plan, replays=3000, seed=19)
        second = self.machine.run(self.plan, replays=3000, seed=19)
        self.assertEqual(first["p_target"], second["p_target"])
        self.assertAlmostEqual(first["p_target"] + first["p_stop"] + first["p_neither"], 1.0)
        self.assertEqual((first["sessions_used"], first["entry_time"]), (57, "10:25"))
        past = first["history"]
        self.assertEqual((past["fired"], past["target"], past["stop"], past["neither"]), (21, 7, 11, 3))

    def test_full_run_numbers(self):
        result = self.machine.run(self.plan)
        self.assertAlmostEqual(result["p_target"], 0.038, places=3)
        self.assertAlmostEqual(result["p_stop"], 0.353, places=3)
        self.assertEqual(result["verdict"], "leans unfavourable")

    def test_simulator_matches_real_drift(self):
        _, bars = self.market().candles("NIFTY", "5m", "60d")
        sessions = timemachine.full_sessions(bars, dt.date(2026, 10, 22))
        pool = timemachine.build_pool(sessions)
        rnd = random.Random(1)
        simulated = []
        for _ in range(3000):
            level = 1.0
            for slot in range(13, 72):
                level *= rnd.choice(pool[min(74, max(1, slot + rnd.randint(-2, 2)))])[3]
            simulated.append(level - 1)
        real = [s[71]["c"] / s[12]["c"] - 1 for s in sessions]
        self.assertAlmostEqual(statistics.mean(simulated), statistics.mean(real), delta=0.0006)
        self.assertAlmostEqual(statistics.pstdev(simulated), statistics.pstdev(real), delta=0.0008)


class TestSizingRiskPaper(WorkspaceTest):
    def prepare(self, **cfg):
        self.config(**cfg)
        self.cli("entry", "check", "NIFTY")
        self.cli("plan", "make", "--target", "1.5R")

    def test_charges(self):
        option = charges("option", 160.30 * 65, 190.0 * 65)
        self.assertEqual(option["brokerage"], 40.0)
        self.assertAlmostEqual(option["stt"], 190.0 * 65 * 0.0015, delta=0.006)    # 0.15% of the sell premium
        self.assertEqual(option["total"], 75.47)
        future = charges("future", 22700 * 65, 22800 * 65)
        self.assertEqual(future["brokerage"], 40.0)
        self.assertAlmostEqual(future["stt"], 22800 * 65 * 0.0005, places=2)
        self.assertAlmostEqual(charges("equity_intraday", 1000, 1010)["brokerage"], 0.6, places=2)   # 0.03% beats Rs 20
        with self.assertRaises(ValidationError):
            charges("crypto", 1, 1)

    def test_refuses_when_one_lot_is_too_risky(self):
        self.prepare()
        code, out, _ = self.cli("budget", "size", "--write")
        self.assertEqual(code, 1)
        self.assertIn("NO TRADE", out)
        self.assertFalse(os.path.exists(os.path.join(self.home, "orders.json")))

    def test_full_chain_to_paper(self):
        self.prepare(max_loss_per_trade=4000, max_daily_loss=8000)
        code, out, _ = self.cli("budget", "size", "--write")
        self.assertEqual(code, 0, out)
        order = self.read("orders.json")["orders"][0]
        self.assertEqual((order["lots"], order["qty"], order["price"]), (1, 65, 181.0))
        self.assertAlmostEqual(order["max_loss_net"], 3464.69, places=2)
        self.assertEqual(order["rr_net"], 1.79)
        code, out, _ = self.cli("risk", "--no-events")
        self.assertEqual(code, 0, out)
        self.assertIn("PASS", out)
        code, _, err = self.cli("paper", "open", "--price", "181.0")
        self.assertEqual(code, 1)
        self.assertIn("explicit yes", err)
        code, out, _ = self.cli("paper", "open", "--price", "181.0", "--yes")
        self.assertEqual(code, 0, out)
        _, out, _ = self.cli("risk", "--no-events", "--no-write", now="2026-10-22 10:40")
        self.assertIn("duplicate", out)
        _, out, _ = self.cli("paper", "mark", "--price", "105", now="2026-10-22 11:00")
        self.assertIn("(stop)", out)
        trade = self.read("paper.json")["trades"][0]
        self.assertEqual(trade["status"], "closed")
        self.assertAlmostEqual(trade["gross"], (105 - 181.0) * 65, places=2)
        self.assertLess(trade["net"], trade["gross"])
        _, out, _ = self.cli("paper", "report")
        self.assertIn("1 trades, 0 wins", out)

    def test_paper_needs_risk_pass(self):
        self.prepare(max_loss_per_trade=4000, max_daily_loss=8000)
        self.cli("budget", "size", "--write")
        code, _, err = self.cli("paper", "open", "--yes", "--price", "160")
        self.assertEqual(code, 1)
        self.assertIn("has not passed", err)

    def test_risk_rules(self):
        manager = RiskManager(self.cfg())
        base = {"symbol": "NIFTY 27OCT26 22700 CE", "underlying": "NIFTY", "type": "option", "action": "BUY", "qty": 65, "lots": 1,
                "price": 160.3, "stop_loss": 109.3, "target": 255.4, "date": "2026-10-22", "delta": 0.51, "spread_pct": 0.6,
                "oi": 93686, "expiry": "2026-10-27", "fingerprint": "f1", "max_loss_net": 900, "rr_net": 1.8, "capital_used": 10419.5}
        moment = clock.parse_now(NOW)
        self.assertEqual(manager.check(base, moment, trades=[])["verdict"], "PASS")

        def blocks(when=moment, trades=(), **changes):
            return " | ".join(manager.check(dict(base, **changes), when, trades=list(trades))["block"])

        self.assertIn("window", blocks(when=clock.parse_now("2026-10-22 09:20")))
        self.assertIn("lottery", blocks(delta=0.1))
        self.assertIn("liquidity", blocks(spread_pct=8.0))
        self.assertIn("selling", blocks(action="SELL", stop_loss=200))
        self.assertIn("loss", blocks(max_loss_net=1500))
        self.assertIn("reward", blocks(rr_net=1.1))
        self.assertIn("stop", blocks(stop_loss=None))
        self.assertIn("window", blocks(date="2026-10-21"))
        self.assertIn("expiry day", blocks(when=clock.parse_now("2026-10-22 14:00"), expiry="2026-10-22"))
        losing = [{"status": "closed", "net": -2500}, {"status": "closed", "net": -100}, {"status": "closed", "net": 50}]
        result = manager.check(base, moment, trades=losing)
        self.assertTrue(any(b.startswith("daily") for b in result["block"]))
        self.assertTrue(any(b.startswith("count") for b in result["block"]))
        self.assertTrue(manager.check(base, moment, vix=24, trades=[])["warn"])


class TestAlerts(WorkspaceTest):
    def test_rules(self):
        moment = clock.parse_now("2026-10-22 11:00")
        quotes = {"NIFTY": {"price": 22600.0, "change_pct": -0.9}}
        evaluate = alerts.evaluate
        self.assertTrue(evaluate({"id": "a", "type": "below", "symbol": "NIFTY", "price": 22624.25}, moment, quotes, {}, {}))
        self.assertIsNone(evaluate({"id": "a", "type": "below", "symbol": "NIFTY", "price": 22624.25}, moment, quotes, {}, {"a": "x"}))
        self.assertIsNone(evaluate({"id": "b", "type": "above", "symbol": "NIFTY", "price": 22877.9}, moment, quotes, {}, {}))
        self.assertTrue(evaluate({"id": "c", "type": "pct", "symbol": "NIFTY", "pct": 0.5}, moment, quotes, {}, {}))
        self.assertIsNone(evaluate({"id": "c", "type": "pct", "symbol": "NIFTY", "pct": 0.5, "direction": "up"}, moment, quotes, {}, {}))
        self.assertTrue(evaluate({"id": "d", "type": "time", "at": "10:00"}, moment, quotes, {}, {}))
        self.assertIsNone(evaluate({"id": "d", "type": "time", "at": "10:00"}, clock.parse_now("2026-10-20 11:00"), quotes, {}, {}))
        premium_rule = {"id": "e", "type": "premium_below", "symbol": "NIFTY", "strike": 22700, "kind": "CE", "expiry": "2026-10-27", "price": 109.3}
        self.assertTrue(evaluate(premium_rule, moment, quotes, {"e": 100.0}, {}))

    def test_from_plan_and_check_once(self):
        self.cli("entry", "check", "NIFTY")
        self.cli("plan", "make", "--target", "1.5R")
        _, out, _ = self.cli("alerts", "add", "--from-plan")
        self.assertEqual(out.count("added"), 5)
        code, out, _ = self.cli("alerts", "check", now="2026-10-22 15:16")
        self.assertEqual(code, 0)
        self.assertIn("square off NIFTY", out)
        code, _, _ = self.cli("alerts", "check", now="2026-10-22 15:17")
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
