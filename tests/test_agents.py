"""The agent classes: registry, the base-class contract and each agent's report."""

import os
import unittest

from _base import WorkspaceTest

from indtrader.models.agents import REGISTRY
from indtrader.models.agents.base import Agent
from indtrader.models.agents.market_analyst.agent import key_levels, scenarios
from indtrader.controllers.agents import run_agent

LATE = "2026-10-22 23:30"


class TestAgentContract(unittest.TestCase):
    def test_registry(self):
        self.assertEqual(sorted(REGISTRY), ["chart-analyst", "decision-maker", "global-news", "india-news", "live-monitor", "market-analyst",
                                            "options-strategist", "performance-coach", "risk-manager", "smart-money", "stock-picker",
                                            "trading-desk"])
        for name, cls in REGISTRY.items():
            self.assertTrue(issubclass(cls, Agent))
            self.assertEqual(cls.name, name)

    def test_name_is_required(self):
        class Nameless(Agent):
            def collect(self):
                return {}

            def render(self, findings):
                return ""

        with self.assertRaises(TypeError):
            Nameless(ctx=None)


class TestAgentsOnSnapshot(WorkspaceTest):
    def run_agent(self, name):
        report = run_agent(self.ctx(LATE), name)
        self.assertTrue(os.path.exists(report.path))
        self.assertTrue(report.markdown.startswith("# "))
        return report

    def test_india_news(self):
        report = self.run_agent("india-news")
        for section in ("## Policy, rules and regulation", "## Market headlines", "## Money flows", "## Results and board meetings"):
            self.assertIn(section, report.markdown)
        self.assertIn("INFY", report.markdown)

    def test_global_news(self):
        report = self.run_agent("global-news")
        self.assertIn("Global mood for the Indian open: NEGATIVE", report.markdown)
        self.assertIn("Indian ADRs (NYSE)", report.markdown)

    def test_market_analyst(self):
        report = self.run_agent("market-analyst")
        self.assertIn("## NIFTY", report.markdown)
        self.assertIn("## BANKNIFTY", report.markdown)
        nifty = report.findings["symbols"]["NIFTY"]
        levels = dict((label, value) for value, label in nifty["levels"])
        self.assertEqual(levels["call wall"], 24000)
        self.assertEqual(levels["put wall"], 22000)
        self.assertTrue(nifty["scenarios"])

    def test_cli(self):
        code, out, err = self.cli("agent", "run", "global-news", now=LATE)
        self.assertEqual(code, 0, err)
        self.assertIn("report written", out)


class TestScenarioRules(unittest.TestCase):
    def test_scenarios_bracket_the_price(self):
        levels = [(22900.0, "R2"), (22800.0, "R1"), (22680.0, "TC"), (22560.0, "S1"), (22450.0, "S2")]
        text = scenarios(22700.0, levels)
        self.assertIn("Bullish if a 5-minute candle closes above 22800.00 (R1)", text[0])
        self.assertIn("Bearish if a 5-minute candle closes below 22680.00 (TC)", text[1])
        self.assertIn("Range between 22680.00 and 22800.00", text[2])

    def test_key_levels_prefer_next_session(self):
        intraday = {"next_session": {"high": 22785.0, "low": 22554.85, "close": 22687.65,
                                     "pivots": {"R2": 22905.0, "R1": 22796.0, "TC": 22681.0, "BC": 22670.0, "S1": 22567.0, "S2": 22446.0}}}
        chain = {"resistance": [{"strike": 23000}], "support": [{"strike": 22000}], "max_pain": 22850}
        found = key_levels(intraday, chain)
        self.assertEqual(found[0], (23000, "call wall"))
        self.assertEqual(found[-1], (22000, "put wall"))
        self.assertEqual([v for v, _ in found], sorted((v for v, _ in found), reverse=True))


if __name__ == "__main__":
    unittest.main()
