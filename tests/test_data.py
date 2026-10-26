"""Market data, the option chain, news processing and money flows on the 22 Oct 2026 snapshot."""

import datetime as dt
import gzip
import json
import unittest

from _base import SNAP, WorkspaceTest

from indtrader.core import clock
from indtrader.core.errors import DataError, ValidationError
from indtrader.models.agents.india_news import tagging
from indtrader.models.agents.india_news.sources import parse_announcements
from indtrader.models.analytics import news as newslib
from indtrader.models.analytics.flows import MoneyFlows, participant_view
from indtrader.models.analytics.option_chain import OptionChainAnalyzer, OptionChainService, max_pain, pick_expiry, pick_strike
from indtrader.models.data import bars as barlib
from indtrader.models.data.feeds import parse_rss
from indtrader.models.data.symbols import is_index, yahoo_symbol


class TestMarketData(WorkspaceTest):
    def test_symbols(self):
        self.assertEqual(yahoo_symbol("NIFTY"), "^NSEI")
        self.assertEqual(yahoo_symbol("reliance"), "RELIANCE.NS")
        self.assertEqual(yahoo_symbol("TCS.BO"), "TCS.BO")
        self.assertEqual(yahoo_symbol("FINNIFTY"), "NIFTY_FIN_SERVICE.NS")
        self.assertTrue(is_index("BANKNIFTY"))

    def test_lot_sizes(self):
        market = self.market()
        lots = market.lot_sizes()
        self.assertEqual((lots["NIFTY"]["lot"], lots["BANKNIFTY"]["lot"], lots["RELIANCE"]["lot"]), (65, 30, 500))
        self.assertIn("RELIANCE", market.fo_stocks())
        self.assertNotIn("NIFTY", market.fo_stocks())
        with self.assertRaises(ValidationError):
            market.lot_size("NOTREAL")

    def test_5m_bars_are_full_sessions(self):
        _, bars = self.market().candles("NIFTY", "5m", "60d")
        sessions = barlib.by_session(bars)
        self.assertEqual(len(sessions[dt.date(2026, 10, 21)]), 75)      # 15:30 tick bar dropped
        self.assertNotIn(dt.date(2026, 10, 20), sessions)                # Dussehra
        self.assertEqual(sessions[dt.date(2026, 10, 22)][0]["t"].strftime("%H:%M"), "09:15")
        self.assertEqual(barlib.closed(bars, clock.parse_now("2026-10-22 09:31"), "5m")[-1]["t"].strftime("%H:%M"), "09:25")

    def test_quotes(self):
        market = self.market()
        nifty = market.quote("NIFTY")
        self.assertEqual((nifty["source"], nifty["prev_close"]), ("NSE", 22811.35))
        self.assertAlmostEqual(nifty["change"], -123.70, places=2)
        self.assertAlmostEqual(market.quote("SENSEX")["change"], -460.30, places=2)
        self.assertAlmostEqual(market.quote("RELIANCE")["change_pct"], -2.0265, places=3)

    def test_offline_file_missing_is_a_data_error(self):
        with self.assertRaises(DataError):
            self.market().candles("NOTREAL", "5m", "5d")


class TestOptionChain(WorkspaceTest):
    def setUp(self):
        super().setUp()
        self.moment = self.now()
        self.chain = OptionChainService(self.market()).fetch("NIFTY", self.moment)
        self.analysis = OptionChainAnalyzer(self.cfg()).analyze(self.chain, self.moment, lot=65)

    def test_expiry_and_spot(self):
        self.assertEqual(self.chain["expiry"], dt.date(2026, 10, 27))
        self.assertAlmostEqual(self.chain["spot"], 22687.65)
        self.assertEqual((self.analysis["atm"], self.analysis["strike_step"]), (22700, 50))

    def test_positioning_numbers(self):
        rows = self.chain["rows"]
        calls = sum(r["ce"]["oi"] for r in rows if r["ce"])
        puts = sum(r["pe"]["oi"] for r in rows if r["pe"])
        a = self.analysis
        self.assertAlmostEqual(a["pcr"], puts / calls)
        self.assertAlmostEqual(a["pcr"], 0.82, places=2)
        self.assertEqual((a["max_pain"], a["resistance"][0]["strike"], a["support"][0]["strike"]), (22850, 24000, 22000))
        self.assertAlmostEqual(a["straddle"], 306.2, places=1)

    def test_max_pain_brute_force(self):
        rows = self.chain["rows"]

        def payout(k):
            return sum(max(0, k - r["strike"]) * (r["ce"] or {}).get("oi", 0) + max(0, r["strike"] - k) * (r["pe"] or {}).get("oi", 0)
                       for r in rows)

        self.assertEqual(max_pain(rows), min((r["strike"] for r in rows), key=payout))

    def test_pick_strike(self):
        picked = pick_strike(self.analysis, "CE", "atm")
        self.assertEqual((picked["strike"], picked["premium"], picked["cost_per_lot"]), (22700, 160.30, 10419.5))
        self.assertTrue(0.45 < picked["delta"] < 0.56)
        self.assertEqual(pick_strike(self.analysis, "PE", "otm1")["strike"], 22650)
        self.assertEqual(pick_strike(self.analysis, "CE", "itm1")["strike"], 22650)
        with self.assertRaises(ValidationError):
            pick_strike(self.analysis, "CE", "deep")

    def test_expiry_choice(self):
        expiries = OptionChainService(self.market()).expiries("NIFTY")
        self.assertEqual(pick_expiry(expiries, self.moment, "next"), dt.date(2026, 11, 3))
        self.assertEqual(pick_expiry(expiries, self.moment, "monthly"), dt.date(2026, 10, 27))
        self.assertEqual(pick_expiry(expiries, clock.parse_now("2026-10-27 15:35"), "near"), dt.date(2026, 10, 27))
        self.assertEqual(pick_expiry(expiries, clock.parse_now("2026-10-27 15:41"), "near"), dt.date(2026, 11, 3))
        with self.assertRaises(ValidationError):
            OptionChainService(self.market()).expiries("SENSEX")


class TestNews(WorkspaceTest):
    def test_rss_and_tags(self):
        with open(SNAP + "/rss-bs-markets.xml", "rb") as fh:
            items = parse_rss(fh.read(), "Business Standard")
        self.assertGreater(len(items), 10)
        self.assertTrue(all(i["time"] is not None for i in items))
        self.assertEqual(tagging.tag("Infosys Q2 results: net profit rises 8%"), ["results"])
        self.assertIn("order-win", tagging.tag("L&T bags order worth Rs 2,500 crore"))
        self.assertIn("rating", tagging.tag("Jefferies keeps INR 880 target for HDFC Bank"))
        self.assertIn("regulatory", tagging.tag("SEBI imposes penalty on broker"))

    def test_google_source_split(self):
        with gzip.open(SNAP + "/rss-gnews-market.xml.gz") as fh:
            first = parse_rss(fh.read(), "Google News")[0]
        self.assertTrue(first["source"].startswith("Google News / "))
        self.assertFalse(first["title"].endswith(first["source"].split(" / ")[1]))

    def test_invalid_feed(self):
        with self.assertRaises(DataError):
            parse_rss(b"<html>not a feed", "X")

    def test_sentiment_and_names(self):
        self.assertGreater(newslib.sentiment("Shares surge after strong results"), 0)
        self.assertLess(newslib.sentiment("Stock plunges on SEBI probe"), 0)
        self.assertEqual(newslib.sentiment("Board meeting on Friday"), 0.0)
        self.assertEqual(newslib.short_name("Reliance Industries Limited"), "Reliance Industries")
        self.assertEqual(newslib.short_name("HDFC Bank Ltd."), "HDFC Bank")

    def test_announcements_matching_and_seen_store(self):
        with open(SNAP + "/nse-ann-RELIANCE.json", encoding="utf-8") as fh:
            filings = parse_announcements(json.load(fh))
        self.assertEqual(filings[0]["tickers"], ["RELIANCE"])
        extra = {"title": "Reliance Industries shares fall 2%", "link": "x", "summary": "", "time": self.now("2026-10-22 10:00"), "source": "t"}
        items = newslib.enrich(filings + [extra], newslib.mention_patterns(["RELIANCE"], {"RELIANCE": "Reliance Industries Limited"}), tagging.tag)
        self.assertIn("RELIANCE", items[-1]["tickers"])
        later = self.now("2026-10-22 23:00")
        recent = newslib.within(items, later, 48)
        self.assertIn(items[-1]["id"], [i["id"] for i in recent])
        store = newslib.SeenStore()
        store.mark([items[-1]], later)
        store.save(later)
        self.assertIn(items[-1]["id"], newslib.SeenStore())


class TestFlows(WorkspaceTest):
    def test_fii_dii(self):
        flows = MoneyFlows(self.market()).fii_dii()
        self.assertAlmostEqual(flows["FII"]["net"], -3458.70)
        self.assertAlmostEqual(flows["DII"]["net"], 2891.32)

    def test_participants(self):
        participants = MoneyFlows(self.market()).participants(self.now())
        self.assertEqual(participants["date"], "2026-10-21")
        view, notes = participant_view(participants)
        self.assertAlmostEqual(view["FII"]["fut_long_pct"], 32598 / (32598 + 310226) * 100)
        self.assertIn("heavily short", notes[0])

    def test_deals(self):
        flows = MoneyFlows(self.market())
        deals = flows.deals()
        self.assertEqual((len(deals["block"]), deals["block"][0]["symbol"]), (4, "GALLANTT"))
        self.assertTrue(all(r["symbol"] == "CAPINVIT" for r in flows.deals({"CAPINVIT"})["block"]))


if __name__ == "__main__":
    unittest.main()
