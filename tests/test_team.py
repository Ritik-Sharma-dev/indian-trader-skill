"""The six team agents added on 23 October 2026: chart analyst, options strategist, stock picker,
smart money, risk manager and performance coach.

Pure functions are tested on hand-made inputs; each agent then runs offline
on a snapshot recorded after the close on Friday 23 October 2026 (NIFTY
closed at 22,600.00).
"""

import datetime as dt
import json
import os

from _base import HERE, WorkspaceTest

AGENTS_SNAP = os.path.join(HERE, "fixtures", "snap-2026-10-23-agents")
NOW = "2026-10-23 16:00"


class TeamTest(WorkspaceTest):
    def team_ctx(self):
        from indtrader.core.context import AppContext
        return AppContext.create(now=NOW, offline=AGENTS_SNAP)

    def run_agent(self, name):
        from indtrader.controllers.agents import run_agent
        return run_agent(self.team_ctx(), name)


class TestChartAnalyst(TeamTest):
    def test_votes_and_trend(self):
        from indtrader.models.agents.chart_analyst.mtf import trend_of, trend_votes
        votes = trend_votes({"last": 101, "ema9": 100.5, "ema21": 100, "supertrend_dir": 1, "macd": 2, "macd_signal": 1})
        self.assertEqual(sum(votes.values()), 4)
        self.assertEqual(trend_votes({"last": None})["close>ema21"], 0)
        self.assertEqual([trend_of(s) for s in (4, 2, 1, -1, -2)], ["UP", "UP", "SIDEWAYS", "SIDEWAYS", "DOWN"])

    def test_alignment_weights(self):
        from indtrader.models.agents.chart_analyst.mtf import alignment
        rows = [{"weight": 1, "trend": "UP"}, {"weight": 2, "trend": "UP"}, {"weight": 2, "trend": "UP"}, {"weight": 3, "trend": "UP"}]
        self.assertEqual(alignment(rows)["label"], "ALIGNED UP")
        rows[-1]["trend"] = "DOWN"                                     # the daily chart disagrees
        self.assertEqual(alignment(rows)["label"], "LEANING UP")
        rows[1]["trend"] = rows[2]["trend"] = "SIDEWAYS"
        self.assertEqual(alignment(rows)["label"], "LEANING DOWN")
        self.assertEqual(alignment([])["label"], "UNKNOWN")

    def test_cross_index_notes(self):
        from indtrader.models.agents.chart_analyst.mtf import cross_index_notes
        results = {"NIFTY": {"alignment": {"label": "LEANING UP"}, "rows": [{"interval": "1d", "trend": "DOWN"}]},
                   "BANKNIFTY": {"alignment": {"label": "ALIGNED DOWN"}, "rows": []}}
        notes = cross_index_notes(results, vix_change=6.0)
        self.assertTrue(any(n.startswith("divergence") for n in notes))
        self.assertTrue(any(n.startswith("fear") for n in notes))

    def test_offline_run(self):
        report = self.run_agent("chart-analyst")
        nifty = report.findings["symbols"]["NIFTY"]
        trends = {r["interval"]: r["trend"] for r in nifty["rows"]}
        self.assertEqual(trends, {"5m": "UP", "15m": "UP", "1h": "DOWN", "1d": "SIDEWAYS"})
        self.assertEqual(nifty["last"], 22600.0)
        self.assertEqual(sorted(report.findings["symbols"]), ["BANKNIFTY", "FINNIFTY", "NIFTY", "SENSEX"])
        self.assertAlmostEqual(nifty["levels"]["next_pivots"]["P"], 22586.42, places=1)
        self.assertIn("Multi-timeframe", report.markdown)


class TestOptionsStrategist(TeamTest):
    def test_realised_vol(self):
        from indtrader.models.agents.options_strategist.strategist import realised_vol
        self.assertIsNone(realised_vol([100.0] * 10))
        self.assertEqual(realised_vol([100.0] * 30), 0.0)
        alternating = [100.0 * (1.01 if i % 2 else 1.0) for i in range(30)]
        self.assertGreater(realised_vol(alternating), 0.1)

    def test_regime(self):
        from indtrader.models.agents.options_strategist.strategist import regime
        self.assertEqual(regime(0.20, 0.14)["label"], "EXPENSIVE")
        self.assertEqual(regime(0.12, 0.15)["label"], "CHEAP")
        self.assertEqual(regime(0.143, 0.163)["label"], "FAIR")
        self.assertEqual(regime(None, 0.1)["label"], "UNKNOWN")

    def test_score_and_best(self):
        from indtrader.models.agents.options_strategist.strategist import best, score_strike
        cfg = self.cfg()
        good = score_strike({"delta": 0.54, "theta": -18.0, "bid": 132.0, "ask": 133.0, "spread_pct": 0.8, "oi": 90000}, cfg)
        lotto = score_strike({"delta": -0.12, "theta": -9.0, "bid": 10.0, "ask": 11.5, "spread_pct": 14.0, "oi": 300}, cfg)
        self.assertEqual(good["score"], 4)
        self.assertEqual(good["theta_hour"], 2.88)
        self.assertAlmostEqual(good["breakeven_pts"], (1.0 + 2.88 / 2) / 0.54, places=1)
        self.assertEqual(lotto["score"], 0)
        self.assertIs(best([lotto, good]), good)
        self.assertIsNone(best([]))

    def test_offline_run(self):
        report = self.run_agent("options-strategist")
        nifty = report.findings["symbols"]["NIFTY"]
        self.assertEqual((nifty["expiry"], nifty["lot"], nifty["atm"]), ("2026-10-27", 65, 22600))
        self.assertEqual(nifty["regime"]["label"], "FAIR")
        self.assertEqual((nifty["best_call"]["strike"], nifty["best_call"]["kind"]), (22600, "CE"))
        self.assertEqual(nifty["best_put"]["kind"], "PE")
        self.assertEqual(len(nifty["calls"]), 4)
        self.assertIn("BANKNIFTY", report.findings["symbols"])


class TestStockPicker(TeamTest):
    def test_buildup(self):
        from indtrader.models.agents.stock_picker.picker import buildup
        self.assertEqual(buildup(1.2, 5.0), "long buildup")
        self.assertEqual(buildup(-1.2, 5.0), "short buildup")
        self.assertEqual(buildup(1.2, -5.0), "short covering")
        self.assertEqual(buildup(-1.2, -5.0), "long unwinding")
        self.assertIsNone(buildup(0, 5.0))

    def test_rollover_is_summed_across_expiries(self):
        from indtrader.models.agents.stock_picker.picker import futures_buildup
        rows = [{"instrumentType": "FUTSTK", "symbol": "ABC", "expiryDate": "27-Oct-2026", "changeInOI": -900, "prevOI": 1000, "pChange": 1.5},
                {"instrumentType": "FUTSTK", "symbol": "ABC", "expiryDate": "24-Nov-2026", "changeInOI": 1000, "prevOI": 500, "pChange": 1.4},
                {"instrumentType": "OPTIDX", "symbol": "NIFTY", "changeInOI": 5, "prevOI": 5, "pChange": 1}]
        result = futures_buildup(rows)
        self.assertEqual(list(result), ["ABC"])
        self.assertEqual(result["ABC"]["oi_change_pct"], round(100 / 1500 * 100, 2))    # +6.67 %, not -90 %
        self.assertEqual((result["ABC"]["buildup"], result["ABC"]["price_change_pct"]), ("long buildup", 1.5))

    def test_score(self):
        from indtrader.models.agents.stock_picker.picker import score
        row = {"rs_20d": 6.0, "change_pct": 1.8, "buildup": "long buildup", "oi_change_pct": 12.0}
        self.assertEqual(len(score(row, "long")), 3)
        self.assertEqual(len(score(row, "long", count_oi=False)), 2)
        self.assertEqual(score(row, "short"), [])

    def test_offline_run(self):
        report = self.run_agent("stock-picker")
        findings = report.findings
        self.assertTrue(findings["rollover"])                          # 27 Oct is the monthly expiry
        self.assertGreater(findings["scanned"], 200)
        self.assertEqual(findings["shorts"][0]["symbol"], "POLICYBZR")
        for row in findings["longs"] + findings["shorts"]:
            self.assertGreaterEqual(row["long_points"] if row in findings["longs"] else row["short_points"], 2)
            self.assertFalse(any("futures" in reason for reason in row["long"] + row["short"]))   # OI not counted this week


class TestSmartMoney(TeamTest):
    def test_fii_run(self):
        from indtrader.models.agents.smart_money.tracker import fii_run
        history = {"20-Oct-2026": {"FII": {"net": -1000}, "DII": {"net": 900}}, "21-Oct-2026": {"FII": {"net": -500}, "DII": {"net": 800}},
                   "23-Oct-2026": {"FII": {"net": 888}, "DII": {"net": -100}}}
        run = fii_run(history)
        self.assertEqual((run["days"], run["fii_net"], run["dii_net"], run["fii_selling_days"]), (3, -612, 1600, 2))
        self.assertIsNone(fii_run({}))

    def test_round_trips_are_dropped(self):
        from indtrader.models.agents.smart_money.tracker import directional_deals
        deals = [{"symbol": "X", "client": "HFT", "side": "BUY"}, {"symbol": "X", "client": "HFT", "side": "SELL"},
                 {"symbol": "X", "client": "FUND", "side": "BUY"}]
        self.assertEqual([d["client"] for d in directional_deals(deals)], ["FUND"])

    def test_verdict(self):
        from indtrader.models.agents.smart_money.tracker import verdict
        flows = {"fiidii": {"FII": {"net": -1200}}, "fii_run": {"days": 5, "fii_net": -5000, "dii_net": 6000, "fii_selling_days": 4},
                 "participants": {"view": {"FII": {"fut_long_pct": 12}}}}
        lines = verdict(flows, {"clusters": [{"people": ["A", "B"], "kind": "buy", "symbol": "ABC"}], "summary": {"pledges_enforced": 1}})
        text = " | ".join(lines)
        for fragment in ("FIIs sold 1200 crore in cash on the latest session", "absorbing", "heavily short", "2 insiders bought ABC", "pledge"):
            self.assertIn(fragment, text)

    def test_offline_run(self):
        report = self.run_agent("smart-money")
        self.assertIn("FIIs bought 888 crore in cash on 23-Oct-2026", report.findings["verdict"])
        self.assertIsNotNone(report.findings["insiders"])
        self.assertIn("Smart money", report.markdown)


class TestRiskManager(TeamTest):
    def paper(self, trades):
        with open(os.path.join(self.home, "paper.json"), "w", encoding="utf-8") as fh:
            json.dump({"trades": trades}, fh)

    def test_lot_risk(self):
        from indtrader.models.agents.risk_manager.status import lot_risk
        risk = lot_risk(premium=132.45, delta=0.54, index_risk_pts=51, lot=65, cfg=self.cfg())
        self.assertGreater(risk, 0.54 * 51 * 65)                       # plus charges
        self.assertLess(risk, 0.54 * 51 * 65 + 150)
        self.assertLessEqual(lot_risk(20.0, 0.9, 500, 65, self.cfg()), 20.0 * 65 + 150)   # never more than the premium

    def test_daily_stop(self):
        from indtrader.models.agents.risk_manager.status import daily_stop
        now = self.now(NOW)
        self.assertIsNone(daily_stop(self.cfg(), now))
        self.paper([{"opened": "2026-10-23T09:56", "status": "closed", "net": -3100}])
        self.assertIn("daily limit", daily_stop(self.cfg(), now))
        self.paper([{"opened": "2026-10-23T09:%02d" % i, "status": "closed", "net": 10} for i in range(3)])
        self.assertIn("3 trades today", daily_stop(self.cfg(), now))
        self.paper([{"opened": "2026-10-22T09:56", "status": "closed", "net": -5000}])          # yesterday does not count
        self.assertIsNone(daily_stop(self.cfg(), now))

    def test_levels(self):
        from indtrader.models.agents.risk_manager.status import RiskDesk
        option = {"premium": 132.45, "delta": 0.54, "lot": 65, "cost_per_lot": 8609, "strike": 22600, "kind": "CE"}
        desk = RiskDesk(self.team_ctx())
        desk.typical_risk_points = lambda symbol="NIFTY": 51.0
        self.assertEqual(desk.status("NIFTY", option)["level"], "BLOCKED")          # default Rs 1,000 limit
        self.config(max_loss_per_trade=4000)                           # but the daily limit is still Rs 3,000
        desk.cfg = self.cfg()
        tight = desk.status("NIFTY", option)
        self.assertEqual((tight["level"], tight["lots_allowed"]), ("CAUTION", 1))
        self.config(max_loss_per_trade=4000, max_daily_loss=10000)
        desk.cfg = self.cfg()
        clear = desk.status("NIFTY", option)
        self.assertEqual((clear["level"], clear["lots_allowed"]), ("CLEAR", 2))     # Rs 4,000 / ~Rs 1,830, capped at 2 lots
        caution = desk.status("NIFTY", option, vix=24.0, expiry_day=True)
        self.assertEqual(caution["level"], "CAUTION")
        self.assertEqual(desk.status("NIFTY", option, decision_done=True)["level"], "STOP")

    def test_offline_run(self):
        report = self.run_agent("risk-manager")
        findings = report.findings
        self.assertEqual(findings["level"], "BLOCKED")
        self.assertGreater(findings["typical_risk_points"], 20)
        self.assertIn("max_loss_per_trade", report.markdown)


class TestPerformanceCoach(TeamTest):
    def trades(self):
        day = dt.date(2026, 10, 5)
        out = []
        for i, (hour, result) in enumerate([("09:50", 2.0), ("09:40", -1.0), ("10:10", 1.5), ("12:30", -1.0), ("12:45", -1.0),
                                            ("09:35", 2.0), ("13:10", -1.0), ("12:20", -1.0), ("09:55", -1.0), ("10:05", 2.0),
                                            ("13:30", -1.0), ("09:45", 2.0)]):
            out.append({"day": day + dt.timedelta(days=i // 2), "entry_time": hour, "minutes": 20 if result > 0 else 60,
                        "setup": "orb", "result": result, "r": result, "confidence": "HIGH" if result > 0 else "LOW", "max_loss": None})
        return out

    def test_summary_and_splits(self):
        from indtrader.models.agents.performance_coach.coach import split, summary
        trades = self.trades()
        overall = summary(trades)
        self.assertEqual(overall["trades"], 12)
        self.assertAlmostEqual(overall["total"], 2.5)                    # five winners (+9.5R), seven 1R losers
        self.assertEqual(overall["profit_factor"], round(9.5 / 7.0, 2))
        self.assertEqual(overall["worst_losing_streak"], 4)
        by_hour = split(trades, lambda t: t["entry_time"][:2])
        self.assertLess(by_hour["12"]["total"], 0)
        self.assertIsNone(summary([]))

    def test_mistakes_and_advice(self):
        from indtrader.models.agents.performance_coach.coach import advice, mistakes, split, summary
        trades = self.trades()
        found = " | ".join(mistakes(trades, self.cfg()))
        self.assertIn("after 12:00", found)
        self.assertIn("more than 1 trade", found)
        self.assertIn("losers are held 60 minutes", found)
        tips = " | ".join(advice(summary(trades), split(trades, lambda t: t["entry_time"][:2] + ":00"), "R"))
        self.assertIn("losing streak 4", tips)
        self.assertNotIn("hour(s)", tips)                                  # no hour has the 4 trades advice needs
        self.assertIn("too few", advice(summary(trades[:3]), {}, "R")[0])

    def test_watch_items(self):
        from indtrader.models.agents.performance_coach.coach import watch_items
        mk = lambda total, n=5: {"trades": n, "total": total, "win_rate": 0.2}             # noqa: E731
        self.assertEqual(len(watch_items({"Mon": mk(3), "Wed": mk(-4), "Fri": mk(2)})), 1)
        self.assertEqual(watch_items({"Mon": mk(-3), "Wed": mk(-4)}), [])

    def test_paper_journal_is_reviewed_first(self):
        from indtrader.models.agents.performance_coach.coach import PerformanceCoach
        trades = [{"status": "closed", "opened": "2026-10-%02dT09:%02d" % (5 + i, 40 + i), "closed": "2026-10-%02dT10:%02d" % (5 + i, 10 + i),
                   "net": 900 if i % 2 else -450, "r": 1.0, "setup": "orb", "max_loss_net": 500} for i in range(12)]
        with open(os.path.join(self.home, "paper.json"), "w", encoding="utf-8") as fh:
            json.dump({"trades": trades}, fh)
        result = PerformanceCoach(self.team_ctx()).review(with_baseline=False)
        self.assertEqual((result["source"], result["unit"], result["overall"]["trades"]), ("paper journal", "rupees", 12))
        self.assertAlmostEqual(result["overall"]["total"], 6 * 900 - 6 * 450)

    def test_empty_without_baseline(self):
        from indtrader.models.agents.performance_coach.coach import PerformanceCoach
        from indtrader.views.team import coach as render
        result = PerformanceCoach(self.team_ctx()).review(with_baseline=False)
        self.assertIsNone(result["overall"])
        self.assertIn("No trades", render(result))


class TestTeamWiring(TeamTest):
    def test_registry_groups_and_claude_agents(self):
        from indtrader.models.agents import REGISTRY
        self.assertEqual(len(REGISTRY), 12)
        claude = os.path.join(os.path.dirname(HERE), "agents")
        names = {f[:-3] for f in os.listdir(claude) if f.endswith(".md")}
        for expected in ("chart-analyst", "options-strategist", "stock-picker", "smart-money", "risk-manager", "performance-coach"):
            self.assertIn(expected, names)

    def test_agent_run_cli(self):
        code, out, _ = self.cli("agent", "run", "chart-analyst", "--offline", AGENTS_SNAP, offline=False, now=NOW)
        self.assertEqual(code, 0)
        self.assertIn("chart-analyst: report written", out)
