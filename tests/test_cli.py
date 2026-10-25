"""Every command runs offline on the snapshot and exits cleanly."""

import os
import unittest

from _base import WorkspaceTest


class TestCommands(WorkspaceTest):
    def ok(self, *argv, **kw):
        code, out, err = self.cli(*argv, **kw)
        self.assertEqual(code, 0, "%s\n%s\n%s" % (argv, out, err))
        return out

    def test_clock(self):
        out = self.ok("clock", offline=False)
        self.assertIn("NSE: OPEN", out)

    def test_pulse(self):
        out = self.ok("pulse")
        self.assertIn("NIFTY 50", out)
        self.assertIn("INDIA VIX", out)
        self.assertIn("Global cues", out)

    def test_quote(self):
        out = self.ok("quote", "NIFTY", "RELIANCE", "--write")
        self.assertIn("-0.54%", out)
        self.assertTrue(os.path.exists(os.path.join(self.home, "prices.json")))

    def test_chain(self):
        out = self.ok("chain", "BANKNIFTY", "--pick", "PE:atm")
        self.assertIn("BANKNIFTY option chain, expiry 2026-10-27", out)
        self.assertIn("Picked BANKNIFTY", out)

    def test_chart_html(self):
        out = self.ok("chart", "NIFTY", "--html")
        self.assertIn("CPR", out)
        html_files = os.listdir(os.path.join(self.home, "charts"))
        self.assertEqual(len(html_files), 1)
        with open(os.path.join(self.home, "charts", html_files[0]), encoding="utf-8") as f:
            page = f.read()
        self.assertIn("<svg", page)
        self.assertIn("prefers-color-scheme:dark", page)
        out = self.ok("chart", "RELIANCE", "--interval", "1d")
        self.assertIn("52w", out)

    def test_news_and_movers(self):
        out = self.ok("news", "--tickers", "RELIANCE", "HDFCBANK", "--hours", "48", "--limit", "0")
        self.assertIn("Watching: RELIANCE, HDFCBANK", out)
        self.assertIn("[HDFCBANK]", out)
        # second run: everything already seen
        out2 = self.ok("news", "--tickers", "RELIANCE", "HDFCBANK", "--hours", "48", "--no-moves")
        self.assertIn("Nothing new", out2)
        out = self.ok("movers", "--hours", "24", now="2026-10-22 23:00")
        self.assertIn("NSE filings", out)

    def test_flows(self):
        out = self.ok("flows")
        self.assertIn("FII", out)
        self.assertIn("Block deals", out)

    def test_brief(self):
        out = self.ok("brief")
        for section in ("## Indices", "## Money flows", "## Option chains", "## Results and board meetings", "## Headlines"):
            self.assertIn(section, out)
        self.assertIn("INFY", out)              # results on 23 Oct
        self.assertEqual(len(os.listdir(os.path.join(self.home, "briefs"))), 1)

    def test_config_init(self):
        out = self.ok("config", "init", offline=False)
        self.assertIn("Created", out)
        self.assertTrue(os.path.exists(os.path.join(self.home, "config.json")))

    def test_errors_are_clean(self):
        code, out, err = self.cli("chain", "SENSEX")
        self.assertEqual(code, 1)
        self.assertIn("BSE", err)
        code, out, err = self.cli("tm")
        self.assertEqual(code, 1)
        self.assertIn("no plan", err)


if __name__ == "__main__":
    unittest.main()
