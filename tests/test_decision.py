"""The decision maker: its hard rules, the context votes, every action, and an end-to-end run offline."""

import datetime as dt

from _base import WorkspaceTest

DAY = "2026-10-23"


def _trade(time="09:55", side="short", **extra):
    trade = {"time": time, "side": side, "setup": "orb", "why": "close below the opening range 22699.80 with the bias -1", "entry": 22638.0,
             "stop": 22743.4, "init_stop": 22743.4, "target": 22427.25, "risk": 105.4,
             "option": {"tradingsymbol": "NIFTY 27OCT26 22650 PE", "lot": 65, "premium_now": 120.5, "bid": 120.0, "ask": 121.0,
                        "premium_stop": 75.0, "premium_target": 210.0, "risk_per_lot": 2957.5, "reward_per_lot": 5817.5}}
    trade.update(extra)
    return trade


def _entry_event(time="09:55"):
    return {"type": "ENTRY", "time": "%sT%s:00+05:30" % (DAY, time), "text": "ENTRY SHORT (orb) at 22638.00"}


def _state(events=(), trade=None, trades=()):
    return {"symbol": "NIFTY", "date": DAY, "events": list(events), "trade": trade, "trades": list(trades), "regime": "down"}


SNAP = {"close": 22600.0, "or_high": 22786.95, "or_low": 22699.8, "pdh": 22790.0, "pdl": 22555.1, "pdc": 22687.65, "day_open": 22742.2}
CONTEXT = {"votes": [{"name": "daily trend", "vote": -1, "detail": "daily trend DOWN"},
                     {"name": "option chain", "vote": -1, "detail": "PCR 0.74"}], "notes": [], "errors": [], "levels": {}}


class TestRules(WorkspaceTest):
    def rules(self):
        from indtrader.models.agents.decision_maker.rules import DecisionRules
        return DecisionRules.from_config(self.cfg())

    def test_skip_reason(self):
        from indtrader.models.agents.decision_maker.rules import skip_reason
        rules = self.rules()
        self.assertIsNone(skip_reason(rules, 1, "09:55", 0.24))
        self.assertIsNone(skip_reason(rules, 1, "12:00", -0.5))
        self.assertIn("one trade a day", skip_reason(rules, 2, "09:55", 0.5))
        self.assertIn("after 12:00", skip_reason(rules, 1, "12:05", 0.5))
        self.assertIn("flat open", skip_reason(rules, 1, "10:00", 0.1))
        self.assertIn("flat open", skip_reason(rules, 1, "10:00", None))

    def test_gap(self):
        from indtrader.models.agents.decision_maker.rules import gap_pct
        self.assertEqual(gap_pct(22687.65, 22742.2), 0.24)
        self.assertIsNone(gap_pct(None, 22742.2))
        up, down = self.rules().gap_levels(22600.0)
        self.assertAlmostEqual(up, 22645.2)
        self.assertAlmostEqual(down, 22554.8)

    def test_config_override(self):
        from indtrader.models.agents.decision_maker.rules import DecisionRules
        self.config(decision={"last_entry": "11:00", "min_gap_pct": 0.3})
        rules = DecisionRules.from_config(self.cfg())
        self.assertEqual((rules.last_entry, rules.min_gap_pct, rules.symbols), (dt.time(11, 0), 0.3, ("NIFTY",)))

    def test_gated_backtest(self):
        from indtrader.models.agents.decision_maker.rules import gated_backtest
        trades = [{"date": "d1", "time": "09:50", "r": 2.0}, {"date": "d1", "time": "10:40", "r": -1.0},
                  {"date": "d2", "time": "09:45", "r": -1.0}, {"date": "d3", "time": "12:30", "r": 1.0}]
        split = gated_backtest(trades, {"d1": 0.5, "d2": 0.05, "d3": -0.6}, self.rules())
        self.assertEqual([t["r"] for t in split["taken"]], [2.0])
        self.assertEqual([t["skip"].split(" (")[0] for t in split["skipped"]], ["one trade a day", "flat open", "after 12:00"])


class TestContext(WorkspaceTest):
    def test_lean_and_confidence(self):
        from indtrader.models.agents.decision_maker.context import confidence, lean
        votes = [{"vote": -1}, {"vote": -1}, {"vote": 1}, {"vote": 0}]
        self.assertEqual(lean(votes), {"score": -1, "label": "MIXED", "for": 1, "against": 2})
        self.assertEqual(confidence(votes, "short"), "MEDIUM")
        self.assertEqual(confidence(votes, "long"), "LOW")
        self.assertEqual(confidence(votes + [{"vote": -1}], "short"), "HIGH")
        self.assertEqual(lean(votes + [{"vote": -1}])["label"], "BEARISH")

    def test_news_view(self):
        from indtrader.models.agents.decision_maker.context import news_view
        items = [{"title": "Nifty falls %d" % i, "sentiment": -0.5, "tags": ["market"], "source": "ET"} for i in range(5)]
        items.append({"title": "RBI keeps repo rate unchanged", "sentiment": 0.0, "tags": ["rbi-rates"], "source": "BS"})
        vote, headlines, warnings = news_view(items)
        self.assertEqual(vote["vote"], -1)
        self.assertEqual(len(headlines), 5)
        self.assertEqual(warnings, ["policy / macro headline: RBI keeps repo rate unchanged"])
        vote, _, _ = news_view(items[:3])                                  # too few scored headlines to vote
        self.assertEqual(vote["vote"], 0)

    def test_event_warnings(self):
        from indtrader.models.agents.decision_maker.context import event_warnings
        now = self.now("2026-10-23 09:00")
        at = lambda hm: self.now("2026-10-23 %s" % hm)                     # noqa: E731
        calendar = [{"time": at("11:00"), "impact": "High", "country": "IN", "event": "RBI policy"},
                    {"time": at("18:00"), "impact": "High", "country": "US", "event": "CPI"},
                    {"time": at("12:00"), "impact": "Medium", "country": "IN", "event": "PMI"}]
        warnings = event_warnings(calendar, now)
        self.assertEqual(len(warnings), 1)
        self.assertIn("11:00 IST: IN RBI policy", warnings[0])

    def test_near_walls(self):
        from indtrader.models.agents.decision_maker.context import near_walls
        walls = [{"strike": 24000, "oi": 900}, {"strike": 22700, "oi": 500}, {"strike": 22800, "oi": 700}, {"strike": 22500, "oi": 999}]
        self.assertEqual(near_walls(walls, 22600, above=True), [22800, 22700])          # 24000 is out of reach today
        self.assertEqual(near_walls(walls, 22600, above=False), [22500])


class TestJudge(WorkspaceTest):
    def setUp(self):
        super().setUp()
        self.config(max_loss_per_trade=5000)          # one lot of the sample trade risks about Rs 3,000

    def judge(self, state, at="10:00", snap=None, fresh=()):
        from indtrader.models.agents.decision_maker.decider import Decider
        decider = Decider(self.ctx())
        now = self.now("%s %s" % (DAY, at))
        snap = dict(SNAP, **(snap or {}))
        from indtrader.models.agents.decision_maker.rules import gap_pct
        return decider._judge("NIFTY", now, state, snap, gap_pct(snap["pdc"], snap["day_open"]), CONTEXT, {}, set(fresh))

    def test_wait_with_triggers(self):
        decision = self.judge(_state(), "09:40")
        self.assertEqual(decision.action, "WAIT")
        self.assertIn("CLOSES below 22699.80", decision.triggers[0])

    def test_no_trade_late_or_flat(self):
        self.assertEqual(self.judge(_state(), "12:10").action, "NO TRADE")
        flat = self.judge(_state(), "09:40", snap={"day_open": 22700.0})
        self.assertEqual(flat.action, "NO TRADE")
        self.assertIn("Flat open", flat.headline)

    def test_risk_check_blocks_a_trade_over_the_max_loss(self):
        self.config(max_loss_per_trade=1000)
        decision = self.judge(_state([_entry_event()], trade=_trade()), "09:56", fresh=[("ENTRY", "%sT09:55" % DAY)])
        self.assertEqual(decision.action, "NO TRADE")
        self.assertIn("over your max loss of ₹1,000", decision.headline)
        self.assertIn("max_loss_per_trade", decision.do[0])

    def test_buy_put_on_a_fresh_signal(self):
        self.config(max_loss_per_trade=5000)
        trade = _trade()
        decision = self.judge(_state([_entry_event()], trade=trade), "09:56", fresh=[("ENTRY", "%sT09:55" % DAY)])
        self.assertEqual(decision.action, "BUY PUT")
        self.assertEqual(decision.confidence, "HIGH")                   # two bearish votes for a PUT
        text = " ".join(decision.do)
        self.assertIn("BUY NIFTY 27OCT26 22650 PE", text)
        self.assertIn("stop 22743.40, target 22427.25", text)

    def test_hold_then_exit_then_done(self):
        held = self.judge(_state([_entry_event()], trade=_trade(stop=22638.0)), "10:12", snap={"close": 22520.0})
        self.assertEqual(held.action, "HOLD")
        self.assertIn("+118.0 points", held.headline)
        self.assertIn("stop moved to 22638.00", held.headline)
        closed = _trade(exit=22533.5, exit_time="10:30", exit_reason="stop", points=104.5, r=0.99)
        exited = self.judge(_state([_entry_event()], trades=[closed]), "10:31", fresh=[("EXIT", "%sT10:30" % DAY)])
        self.assertEqual(exited.action, "EXIT")
        self.assertIn("SELL the PUT now", exited.headline)
        done = self.judge(_state([_entry_event()], trades=[closed]), "10:40")
        self.assertEqual(done.action, "DONE")

    def test_second_signal_is_ignored(self):
        first = _trade(exit=22533.5, exit_time="10:30", exit_reason="stop", points=104.5, r=0.99)
        second = _trade(time="11:05", side="long")
        events = [_entry_event(), _entry_event("11:05")]
        decision = self.judge(_state(events, trade=second, trades=[first]), "11:06", fresh=[("ENTRY", "%sT11:05" % DAY)])
        self.assertEqual(decision.action, "DONE")

    def test_missed_signal_is_never_chased(self):
        missed = {"type": "INFO", "time": "%sT09:55:00+05:30" % DAY, "text": "missed short orb signal at 09:55 (more than one bar old): not taken"}
        decision = self.judge(_state([missed]), "10:05")
        self.assertEqual(decision.action, "DONE")
        self.assertIn("PUT, orb", decision.headline)
        self.assertIn("never chase", decision.headline)

    def test_late_first_signal_is_skipped(self):
        trade = _trade(time="12:15")
        decision = self.judge(_state([_entry_event("12:15")], trade=trade), "12:16", fresh=[("ENTRY", "%sT12:15" % DAY)])
        self.assertEqual(decision.action, "NO TRADE")
        self.assertIn("after 12:00", decision.headline)

    def test_banknifty_is_refused(self):
        from indtrader.models.agents.decision_maker.decider import Decider
        from indtrader.core.errors import ValidationError
        with self.assertRaises(ValidationError):
            Decider(self.ctx()).decide("BANKNIFTY")


class TestJournal(WorkspaceTest):
    def test_record_and_summary(self):
        from indtrader.models.agents.decision_maker.decider import Decision
        from indtrader.models.agents.decision_maker.journal import DecisionJournal
        from indtrader.views.decisions import journal as render
        journal = DecisionJournal()
        context = {"lean": {"label": "BEARISH", "score": -2}, "votes": [{"name": "news", "vote": -1}]}
        day = dt.date(2026, 10, 23)
        journal.record("NIFTY", day, Decision("NIFTY", "%sT09:40" % DAY, "WAIT", "No signal yet."), 0.24, context)
        journal.record("NIFTY", day, Decision("NIFTY", "%sT09:45" % DAY, "WAIT", "No signal yet."), 0.24, context)
        trade = _trade(exit=22533.5, exit_time="10:30", exit_reason="stop", points=104.5, r=0.99)
        journal.record("NIFTY", day, Decision("NIFTY", "%sT10:31" % DAY, "EXIT", "SELL", "HIGH", trade=trade), 0.24, context)
        journal.record("NIFTY", dt.date(2026, 10, 26), Decision("NIFTY", "2026-10-26T09:31", "NO TRADE", "Flat open"), 0.05, context)
        reloaded = DecisionJournal()
        entry = reloaded.data["2026-10-23 NIFTY"]
        self.assertEqual([a["action"] for a in entry["actions"]], ["WAIT", "EXIT"])          # changes only
        self.assertEqual((entry["outcome"]["r"], entry["outcome"]["confidence"]), (0.99, "HIGH"))
        summary = reloaded.summary()
        self.assertEqual((summary["days"], summary["trades"], summary["no_trade_days"], summary["total_r"]), (2, 1, 1, 0.99))
        self.assertEqual(summary["by_confidence"]["HIGH"]["trades"], 1)
        self.assertIn("Flat open", render(summary))

    def test_replays_are_not_journaled(self):
        code, out, _ = self.cli("decide", "journal")
        self.assertIn("empty", out)
        self.cli("decide", "now", "NIFTY")                               # pinned clock: a replay
        from indtrader.models.agents.decision_maker.journal import DecisionJournal
        self.assertEqual(DecisionJournal().data, {})


class TestTradingDesk(WorkspaceTest):
    def test_desk_runs_every_stage_offline(self):
        from indtrader.models.agents.trading_desk import TradingDeskAgent
        from indtrader.controllers.agents import run_agent
        report = run_agent(self.ctx(), TradingDeskAgent(self.ctx()))
        agents = [s["agent"] for s in report.findings["stages"]]
        self.assertEqual(agents, ["global-news", "india-news", "smart-money", "market-analyst", "chart-analyst", "options-strategist",
                                  "stock-picker", "risk-manager", "decision-maker"])
        for heading in ("## 1. Research", "## 2. Analysis", "## 3. Risk", "## 4. Decision"):
            self.assertIn(heading, report.markdown)
        self.assertIn("DECISION:", report.markdown)
        self.assertTrue(report.path.endswith("trading-desk-data.md"))

    def test_agent_run_all_is_the_desk(self):
        code, out, _ = self.cli("agent", "run", "all")
        self.assertEqual(code, 0)
        self.assertEqual(out.count("report written"), 1)
        self.assertIn("trading-desk", out)


class TestEndToEnd(WorkspaceTest):
    def test_decide_now_offline(self):
        code, out, _ = self.cli("decide", "now", "NIFTY")
        self.assertIn(code, (0, 1))
        self.assertIn("DECISION:", out)
        self.assertIn("NIFTY", out)

    def test_decide_plan_and_json(self):
        import json
        code, out, _ = self.cli("decide", "plan", "NIFTY", "--json")
        self.assertEqual(code, 1)
        data = json.loads(out)
        self.assertIn(data["action"], ("WAIT", "NO TRADE"))
        self.assertTrue(data["triggers"])
        code, out, _ = self.cli("decide", "now", "BANKNIFTY")
        self.assertEqual(code, 1)
        self.assertEqual(out, "")

    def test_replay_has_no_live_quotes(self):
        from indtrader.core.context import AppContext
        self.assertFalse(AppContext.create(offline=None).replaying)
        self.assertTrue(AppContext.create(now="2026-10-23 10:00").replaying)
        self.assertFalse(self.ctx().replaying)                        # an offline snapshot has that moment's quotes
