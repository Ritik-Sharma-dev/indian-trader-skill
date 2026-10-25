"""Global / US news, the overnight snapshot, the economic calendar, Indian
policy feeds, and the Claude agent definitions."""

import json
import os
import re
import unittest

from _base import ROOT, SNAP, WorkspaceTest

from indtrader.models.agents.global_news import themes
from indtrader.models.agents.global_news.desk import GlobalDesk, theme_summary
from indtrader.models.agents.global_news.snapshot import GlobalSnapshot, mood
from indtrader.models.agents.global_news.sources import GlobalNewsSources
from indtrader.models.agents.india_news import tagging
from indtrader.models.agents.india_news.sources import IndiaNewsSources
from indtrader.models.data.feeds import parse_rss, parse_time
from indtrader.models.data.symbols import yahoo_symbol

LATE = "2026-10-22 23:25"


class TestGlobal(WorkspaceTest):
    def test_yahoo_codes_pass_through(self):
        for code in ("DX-Y.NYB", "000001.SS", "BZ=F", "^TNX", "RELIANCE.NS"):
            self.assertEqual(yahoo_symbol(code), code)
        self.assertEqual(yahoo_symbol("INFY"), "INFY.NS")       # plain = NSE; ADRs go raw through raw_quotes

    def test_snapshot_and_mood(self):
        snapshot = GlobalSnapshot(self.market()).collect()
        rows = {r["symbol"]: r for group in snapshot for r in group["rows"]}
        for symbol in ("^GSPC", "ES=F", "^VIX", "^TNX", "DX-Y.NYB", "BZ=F", "000001.SS", "INFY", "HDB"):
            self.assertIn(symbol, rows, symbol)
        self.assertLess(rows["INFY"]["last"], 100)               # the US ADR in dollars, not the NSE share
        self.assertIn("change_bp", rows["^TNX"])
        reading = mood(snapshot)
        self.assertEqual(reading["label"], "negative")
        self.assertTrue(any("Brent" in note for note in reading["notes"]))
        self.assertIsNotNone(reading["adr_avg_pct"])
        # one-day changes from Yahoo's own previous close (the daily spark skipped 21 Oct)
        self.assertAlmostEqual(rows["^N225"]["change_pct"], -2.65, delta=0.02)
        self.assertAlmostEqual(rows["^KS11"]["change_pct"], -3.52, delta=0.02)

    def test_mood_rules(self):
        def snapshot(**changes):
            return [{"group": "x", "rows": [{"symbol": s, "change_pct": c} for s, c in changes.items()]}]
        self.assertEqual(mood(snapshot(**{"ES=F": 1.0, "NQ=F": 1.2}))["label"], "positive")
        self.assertEqual(mood(snapshot(**{"BZ=F": 3.0}))["label"], "mildly negative")
        self.assertEqual(mood(snapshot(**{"ES=F": 0.1}))["label"], "neutral")

    def test_calendar_in_ist(self):
        events = GlobalNewsSources(self.market().http).calendar(self.now("2026-10-22 12:00"))
        claims = next(e for e in events if e["event"] == "Unemployment Claims")
        self.assertEqual(claims["time"].strftime("%Y-%m-%d %H:%M"), "2026-10-22 18:00")   # 08:30 New York = 18:00 IST
        self.assertEqual(claims["when"], "today")
        self.assertTrue(all(e["impact"] in ("High", "Medium") for e in events))

    def test_themes_and_impact(self):
        found = themes.themes_of("Oil prices jump 4% as Houthi attacks hit supply")
        self.assertIn("crude", found)
        self.assertIn("geopolitics", found)
        self.assertIn("fed-rates", themes.themes_of("Powell signals rate cut in December"))
        self.assertIn("tech-ai", themes.themes_of("Nvidia leads chip stocks higher"))
        self.assertEqual(themes.themes_of("Celebrity wedding draws crowds"), [])
        self.assertTrue(all(theme.india_impact for theme in themes.THEMES))
        self.assertIn("BPCL", themes.IMPACT["crude"])

    def test_headlines_snapshot(self):
        items = GlobalDesk(self.market()).headlines(self.now(LATE), 18)
        self.assertGreater(len(items), 10)
        self.assertTrue(all(it["themes"] for it in items))
        self.assertEqual(theme_summary(items)[0]["theme"], "tech-ai")

    def test_cli(self):
        code, out, err = self.cli("global", now=LATE)
        self.assertEqual(code, 0, err)
        for part in ("Global mood for the Indian open", "Indian ADRs", "Economic calendar", "What the themes usually mean for India"):
            self.assertIn(part, out)


class TestPolicy(WorkspaceTest):
    def test_sebi_date_and_filter(self):
        with open(os.path.join(SNAP, "rss-sebi.xml"), "rb") as fh:
            items = parse_rss(fh.read(), "SEBI")
        self.assertTrue(items and all(i["time"] for i in items))
        self.assertEqual(parse_time("22 Oct, 2026 +0530").strftime("%Y-%m-%d"), "2026-10-22")

    def test_policy_themes(self):
        self.assertIn("rbi-liquidity", tagging.policy_themes("RBI to conduct 3-day Variable Rate Repo (VRR) auction"))
        self.assertIn("fno-rules", tagging.policy_themes("SEBI revises lot size for index derivatives"))
        self.assertIn("trade-policy", tagging.policy_themes("India-EU FTA may be operational in January-March"))
        self.assertIn("ban-surveillance", tagging.policy_themes("Securities in ban period for F&O"))

    def test_collect_and_cli(self):
        errors = []
        items = IndiaNewsSources(self.market()).policy_items(errors)
        self.assertEqual(errors, [])
        self.assertTrue({"RBI press release", "SEBI", "BS Economy"} <= {i["source"] for i in items})
        self.assertFalse(any("/enforcement/recovery" in i["link"] for i in items))
        code, out, _ = self.cli("policy", "--hours", "24", now=LATE)
        self.assertEqual(code, 0)
        self.assertIn("RBI press release", out)
        _, out, _ = self.cli("policy", "--only", "trade-policy", now=LATE)
        self.assertIn("FTA", out)


class TestClaudeAgentFiles(unittest.TestCase):
    AGENTS = ("india-market-news", "global-market-news", "market-data-analyst", "live-market-monitor")

    def test_agent_files(self):
        for folder in (os.path.join(ROOT, "agents"), os.path.join(os.path.dirname(ROOT), ".claude", "agents")):
            for name in self.AGENTS:
                path = os.path.join(folder, name + ".md")
                self.assertTrue(os.path.exists(path), path)
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
                match = re.match(r"---\nname: (.+)\ndescription: (.+)\ntools: (.+)\n---\n", text)
                self.assertTrue(match, path)
                self.assertEqual(match.group(1), name)
                # quoted: an unquoted ": " inside a YAML description breaks the agent file
                self.assertTrue(match.group(2).startswith('"'), path)
                self.assertIn("Use when", json.loads(match.group(2)), path)
                self.assertIn("Bash", match.group(3))
                self.assertIn("never place", text)

    def test_research_skill_names_the_agents(self):
        with open(os.path.join(ROOT, "skills", "in-research", "SKILL.md"), encoding="utf-8") as fh:
            text = fh.read()
        for name in self.AGENTS[:3]:
            self.assertIn(name, text)


if __name__ == "__main__":
    unittest.main()
