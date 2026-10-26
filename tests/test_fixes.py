"""Data-accuracy fixes of 26 October 2026: the closing auction, exact strikes, NSE's official day,
net-of-charges backtests, symbol lookup, company news by the names the press uses, and insiders."""

import datetime as dt
import unittest
from unittest import mock

from _base import WorkspaceTest, session

from indtrader.core import clock
from indtrader.core.errors import DataError
from indtrader.core.formatting import strike
from indtrader.models.analytics import news as newslib
from indtrader.models.data import bars as barlib

BHAV = """SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER
GROWW, EQ, 23-Oct-2026, 187.07, 187.17, 187.50, 179.50, 181.40, 181.52, 181.47, 16469697, 29887.19, 202340, 8574596, 52.06
GROWW, BL, 23-Oct-2026, 187.07, 181.00, 181.00, 181.00, 181.00, 181.00, 181.00, 100, 0.18, 1, 100, 100.00
"""

SYMBOL_CHANGES = """NAME OF THE COMPANY,OLD SYMBOL,NEW SYMBOL,EFFECTIVE DATE
ETERNAL LIMITED,ZOMATO,ETERNAL,09-APR-2025
Some Company Limited,AAA,BBB,01-JAN-2020
Some Company Limited,BBB,CCC,01-JAN-2022
"""

BSE_SEARCH = ("<li class='quotemenu quotemenuselect'><a href='/x/'><strong>AMIN TANNERY</strong> LTD<br /><span>AMINTAN&nbsp;&nbsp;&nbsp;"
              "INE572Z01017&nbsp;&nbsp;&nbsp;541771</span> <span class='offleft' tabindex='-1'>1 matches found </span> </a></li>")


def leg(ltp, bid, ask, vol, oi, iv):
    return {"ltp": ltp, "chg": 0, "oi": oi, "coi": 0, "vol": vol, "iv": iv, "bid": bid, "ask": ask}


class TestClosingAuction(WorkspaceTest):
    def test_session_times(self):
        self.assertEqual(clock.derivatives_close(dt.date(2026, 7, 31)), dt.time(15, 30))
        self.assertEqual(clock.derivatives_close(dt.date(2026, 10, 27)), dt.time(15, 40))
        self.assertEqual(clock.expiry_close(dt.date(2026, 10, 27)), clock.parse_now("2026-10-27 15:40"))
        self.assertIn("closing auction", clock.market_status(self.now("2026-10-22 15:20"))["reason"])
        self.assertIn("derivatives trade until 15:40", clock.market_status(self.now("2026-10-22 15:35"))["reason"])

    def test_auction_bars_are_flagged_for_fo_stocks_only(self):
        market = self.market()
        _, bars = market.candles("RELIANCE", "5m", "1d")
        flagged = [b for b in bars if b.get("auction")]
        self.assertEqual([b["t"].strftime("%H:%M") for b in flagged], ["15:25"])
        self.assertEqual(barlib.continuous(bars)[-1]["c"], 1189.9)
        made = session("2026-10-22", [100.0] * 75)
        barlib.mark_closing_auction(made)
        self.assertEqual(sum(1 for b in made if b.get("auction")), 3)
        older = session("2026-07-31", [100.0] * 75)
        self.assertEqual(barlib.mark_closing_auction(older), 0)

    def test_chart_reads_indicators_before_the_auction(self):
        from indtrader.models.analytics.charting import ChartAnalyzer
        result = ChartAnalyzer(self.market()).analyze("RELIANCE", "5m", "1d", None, self.now("2026-10-22 23:00"))
        self.assertEqual(result["last"], 1184.5)
        self.assertEqual(result["last_trade"], 1189.9)
        self.assertEqual(result["auction"]["last_trade_time"], "15:15")
        self.assertTrue(any(s.startswith("closing auction set the close at 1184.50") for s in result["signals"]))
        self.assertTrue(all(not b.get("auction") for b in result["series"]["bars"]))

    def test_option_iv_uses_the_parity_price_when_spot_is_stale(self):
        from indtrader.models.analytics.option_chain import OptionChainAnalyzer
        rows = [{"strike": 147.5, "ce": leg(2.92, 2.7, 2.9, 83, 33, 0), "pe": leg(0.87, 0.88, 1.0, 705, 105, 39.25)},
                {"strike": 150.0, "ce": leg(1.48, 1.33, 1.47, 841, 234, 0), "pe": leg(2.07, 1.94, 2.12, 1587, 261, 45.99)},
                {"strike": 152.5, "ce": leg(0.63, 0.58, 0.65, 655, 254, 14.55), "pe": leg(3.67, 3.63, 3.9, 146, 92, 52.43)},
                {"strike": 155.0, "ce": leg(0.30, 0.28, 0.32, 956, 271, 20.62), "pe": leg(5.74, 5.77, 6.02, 700, 312, 61.9)}]
        chain = {"symbol": "MOTHERSON", "spot": 151.67, "timestamp": "23-Oct-2026 15:40:00", "rows": rows, "expiry": dt.date(2026, 10, 27)}
        analysis = OptionChainAnalyzer(self.cfg()).analyze(chain, self.now("2026-10-23 16:00"), 6150)
        self.assertTrue(analysis["spot_mismatch"])
        self.assertAlmostEqual(analysis["pricing_spot"], 149.4, delta=0.2)
        self.assertEqual(analysis["atm"], 150.0)
        for row in analysis["near"]:
            self.assertLess(abs(row["ce"]["iv_calc"] - row["pe"]["iv_calc"]), 0.03, row["strike"])
        self.assertEqual(analysis["spot"], 151.67)

    def test_index_chain_has_no_mismatch(self):
        from indtrader.models.analytics.option_chain import OptionChainAnalyzer, OptionChainService
        moment = self.now()
        chain = OptionChainService(self.market()).fetch("NIFTY", moment)
        analysis = OptionChainAnalyzer(self.cfg()).analyze(chain, moment, 65)
        self.assertFalse(analysis["spot_mismatch"])
        self.assertEqual(analysis["pricing_spot"], analysis["spot"])


class TestStrikesAndOfficialDay(WorkspaceTest):
    def test_strikes_are_never_rounded(self):
        self.assertEqual(strike(152.5), "152.5")
        self.assertEqual(strike(22700.0), "22700")
        self.assertEqual(strike(72.25), "72.25")
        self.assertEqual(strike(None), "-")

    def test_chain_view_prints_half_strikes(self):
        from indtrader.views.market import chain
        analysis = {"symbol": "X", "expiry": "2026-10-27", "days_to_expiry": 4.0, "timestamp": None, "spot": 151.67,
                    "pricing_spot": 149.39, "parity_gap_pct": -1.5, "spot_mismatch": True, "atm": 150.0, "lot": 6150, "strike_step": 2.5,
                    "pcr": 0.6, "pcr_near": 0.6, "pcr_change": None, "ce_oi_added": 0, "pe_oi_added": 0, "max_pain": 157.5, "atm_iv": 0.28,
                    "straddle": 3.55, "expected_move": 3.55, "resistance": [{"strike": 152.5, "oi": 254}], "support": [], "ce_writing": [],
                    "pe_writing": [], "bias": "neutral", "bias_score": 0, "reasons": [],
                    "near": [{"strike": 150.0, "ce": {}, "pe": {}}, {"strike": 152.5, "ce": {}, "pe": {}}]}
        text = chain(analysis)
        self.assertIn("step 2.5", text)
        self.assertIn("Max pain 157.5", text)
        self.assertIn("152.5 (254)", text)
        self.assertIn("WARNING: the options are priced off 149.39", text)
        self.assertIn("further from spot than the priced-in move", text)

    def test_bhavcopy(self):
        from indtrader.models.data.nse import parse_bhavcopy
        day = parse_bhavcopy(BHAV)
        self.assertEqual(list(day), ["GROWW"])
        self.assertEqual((day["GROWW"]["last"], day["GROWW"]["close"], day["GROWW"]["series"]), (181.40, 181.52, "EQ"))
        market = self.market()
        with mock.patch.object(market.nse, "bhavcopy", return_value=BHAV):
            self.assertEqual(market.official_day("GROWW", dt.date(2026, 10, 23))["close"], 181.52)
            self.assertIsNone(market.official_day("NIFTY", dt.date(2026, 10, 23)))
            self.assertIsNone(market.official_day("AMINTAN.BO", dt.date(2026, 10, 23)))


class TestBacktestCharges(WorkspaceTest):
    def test_stock_trades_are_netted(self):
        from indtrader.models.agents.live_monitor.monitor import stats, with_charges
        trades = [{"side": "long", "setup": "orb", "entry": 72.30, "exit": 72.32, "points": 0.02, "risk": 0.20, "r": 0.1, "exit_reason": "target"},
                  {"side": "short", "setup": "orb", "entry": 3650.0, "exit": 3620.0, "points": 30.0, "risk": 25.0, "r": 1.2, "exit_reason": "target"}]
        with_charges(trades, self.cfg())
        self.assertEqual(trades[0]["qty"], 5000)
        self.assertLess(trades[0]["net_points"], 0)
        self.assertEqual(trades[1]["qty"], 40)
        self.assertLess(trades[1]["net_r"], trades[1]["r"])
        summary = stats(trades)
        self.assertLess(summary["total_net_r"], summary["total_r"])
        self.assertEqual(summary["net_wins"], 1)

    def test_backtest_without_full_sessions_is_a_clear_error(self):
        from indtrader.models.agents.live_monitor.monitor import LiveMonitor
        monitor = LiveMonitor(self.ctx())
        with mock.patch.object(monitor.market, "candles", return_value=({}, session("2026-10-22", [1.6] * 20))):
            with self.assertRaises(DataError):
                monitor.backtest("AMINTAN.BO")

    def test_decide_backtest_reports_out_of_sample(self):
        code, out, _ = self.cli("decide", "backtest", "NIFTY")
        self.assertEqual(code, 0)
        self.assertIn("Out of sample (sessions after 2026-10-23", out)


class TestSymbols(WorkspaceTest):
    def test_symbol_changes_follow_chains(self):
        market = self.market()
        with mock.patch.object(market.nse, "symbol_changes", return_value=SYMBOL_CHANGES):
            former = market.former_symbols()
            self.assertEqual(former["ETERNAL"], ["ZOMATO"])
            self.assertEqual(sorted(former["CCC"]), ["AAA", "BBB"])

    def test_bse_search_and_explanations(self):
        from indtrader.models.data.bse import parse_search
        self.assertEqual(parse_search(BSE_SEARCH), [{"name": "AMIN TANNERY LTD", "symbol": "AMINTAN", "isin": "INE572Z01017", "code": "541771"}])
        market = self.market()
        with mock.patch.object(market.nse, "symbol_changes", return_value=SYMBOL_CHANGES), \
                mock.patch.object(market.bse, "search", return_value=parse_search(BSE_SEARCH)), \
                mock.patch.object(market, "listed_companies", return_value={"HDFCBANK": "HDFC Bank Ltd", "HDFCLIFE": "HDFC Life"}):
            self.assertIn("NSE renamed ZOMATO to ETERNAL on 09 Apr 2025", market.explain_symbol("zomato"))
            self.assertIn("NSE symbols starting HDFC: HDFCBANK, HDFCLIFE", market.explain_symbol("HDFC"))
            self.assertIn("AMINTAN.BO (AMIN TANNERY LTD, code 541771)", market.explain_symbol("AMINTAN"))

    def test_entry_text_for_a_stock_without_fo(self):
        from indtrader.views.trading import entry
        result = {"symbol": "GROWW", "setup": "orb", "status": "triggered", "side": "short", "trigger_time": "09:40", "trigger_price": 183.55,
                  "fo": False}
        text = entry(result)
        self.assertIn("short the stock intraday (GROWW has no futures or options)", text)
        self.assertNotIn("buy PE", text)
        self.assertIn("buy PE or sell future", entry(dict(result, symbol="NIFTY", fo=True)))


class TestCompanyNews(WorkspaceTest):
    OTHERS = ["Billionbrains Garage Ventures Limited", "Eternal Limited", "IDFC First Bank Limited", "Larsen & Toubro Limited",
              "Samvardhana Motherson International Limited", "Motherson Sumi Wiring India Limited", "Reliance Industries Limited",
              "Reliance Power Limited"]

    def test_name_terms_come_from_the_exchange_lists(self):
        terms = newslib.name_terms
        self.assertEqual(terms("GROWW", "Billionbrains Garage Ventures Limited", self.OTHERS),
                         ["Billionbrains Garage Ventures", "Billionbrains", "Billionbrains Garage", "Groww"])
        self.assertEqual(terms("ETERNAL", "Eternal Limited", self.OTHERS, ["ZOMATO"]), ["Eternal", "Zomato"])
        self.assertEqual(terms("IDFCFIRSTB", "IDFC First Bank Limited", self.OTHERS), ["IDFC First Bank", "IDFC", "IDFC First"])
        self.assertEqual(terms("LT", "Larsen & Toubro Limited", self.OTHERS), ["Larsen & Toubro", "Larsen"])
        self.assertNotIn("Motherson", terms("MOTHERSON", "Samvardhana Motherson International Limited", self.OTHERS))
        self.assertEqual(terms("RELIANCE", "Reliance Industries Limited", self.OTHERS), ["Reliance Industries"])
        self.assertEqual(newslib.search_terms(["Larsen & Toubro", "Larsen"]), ["Larsen & Toubro"])

    def test_relevance_rules(self):
        from indtrader.models.agents.india_news.desk import company_relevance
        when = self.now("2026-10-23 12:00")
        items = [{"title": t, "source": s, "tickers": [k], "origin": k, "time": when}
                 for t, s, k in (("Groww rolls out US stock investing to all customers", "Google News / ET", "GROWW"),
                                 ("Groww Nifty Metal ETF (GROWWMETAL.NS) Stock Price", "Google News / Yahoo", "GROWW"),
                                 ("Invest in US Stocks on Groww", "Google News / Groww", "GROWW"),
                                 ("Ripple billionaire Chris Larsen bought a Napa estate", "Google News / X", "LT"),
                                 ("Larsen & Toubro wins orders worth Rs 4,400 crore", "Google News / ET", "LT"),
                                 ("NCC Group PLC executes buyback of shares", "Google News / X", "NCC"),
                                 ("NCC receives Rs 12.86 bn road contract", "Google News / X", "NCC"))]
        kept = company_relevance(items, {"GROWW": ["Billionbrains Garage Ventures", "Groww"], "LT": ["Larsen & Toubro", "Larsen"],
                                         "NCC": ["NCC"]})
        self.assertEqual([i["title"][:20] for i in kept], ["Groww rolls out US s", "Larsen & Toubro wins", "NCC receives Rs 12.8"])

    def test_reworded_copies_are_merged(self):
        when = self.now("2026-10-24 18:00")
        raw = [{"title": "IDFC First Bank Q2 profit nearly triples to Rs 1,045 crore", "link": "a", "source": "X", "time": when},
               {"title": "IDFC First Bank Q2 profit nearly triples to Rs 1,045 crore; loan assets rise 30%", "link": "b", "source": "Y", "time": when},
               {"title": "IDFCFIRSTB: Outcome of Board Meeting", "link": "c", "source": "NSE filing", "time": when}]
        items = newslib.enrich(raw, newslib.mention_patterns(["IDFCFIRSTB"], {}, {"IDFCFIRSTB": ["IDFC First Bank"]}), lambda text: [])
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["similar"], 1)
        self.assertEqual(items[0]["tickers"], ["IDFCFIRSTB"])

    def test_archive_and_dated_search(self):
        from indtrader.models.agents.india_news.sources import google_feed_url
        url = google_feed_url('"NCC"', since=dt.date(2026, 10, 12), until=dt.date(2026, 10, 18))
        self.assertIn("after%3A2026-10-11+before%3A2026-10-19", url)
        self.assertIn("when%3A7d", google_feed_url('"NCC"', 7))
        archive = newslib.NewsArchive()
        item = {"id": "abc", "title": "NCC wins order", "time": self.now("2026-10-13 17:32"), "tickers": ["NCC"], "tags": ["order-win"],
                "sentiment": 0.5, "source": "X", "link": "l"}
        self.assertEqual(archive.save([item]), 1)
        loaded = archive.load(self.now("2026-10-12 00:00"), self.now("2026-10-18 23:59"), ["NCC"])
        self.assertEqual([(i["id"], i["tickers"], i["time"]) for i in loaded], [("abc", ["NCC"], item["time"])])
        self.assertEqual(archive.load(self.now("2026-10-19 00:00"), self.now("2026-10-20 00:00")), [])

    def test_news_cli_with_dates(self):
        code, out, _ = self.cli("news", "--tickers", "RELIANCE", "--since", "2026-10-20", "--until", "2026-10-22", "--no-moves", "--stocks-only")
        self.assertEqual(code, 0)
        self.assertIn("News from 20 Oct 2026 to 22 Oct 2026", out)
        code, _, err = self.cli("news", "--until", "2026-10-22")
        self.assertEqual(code, 1)
        self.assertIn("--until needs --since", err)


class TestInsidersAndPicker(WorkspaceTest):
    def test_employee_trust_is_not_an_insider_buy(self):
        from indtrader.models.analytics.insiders import SymbolMatcher, from_bse, name_in
        record = {"Fld_PromoterName": "Motherson ESOP Trust", "Fld_PersonCatgName": "Trust", "ModeOfAquisation": "Market Purchase",
                  "Fld_TransactionType": "Acquisition", "Fld_SecurityNo": "3697806", "Fld_SecurityValue": "607132431",
                  "Companyname": "Samvardhana Motherson International Ltd"}
        self.assertEqual(from_bse(record, SymbolMatcher({}))["kind"], "trust")
        director = dict(record, Fld_PromoterName="Gaurav Kalani", Fld_PersonCatgName="Designated Person", ModeOfAquisation="Market Sale",
                        Fld_TransactionType="Disposal")
        self.assertEqual(from_bse(director, SymbolMatcher({}))["kind"], "sell")
        self.assertTrue(name_in("Gaurav Kalani", "Resignation of Gaurav Kalani - Chief Financial Officer"))
        self.assertFalse(name_in("Gaurav Kalani", "Resignation of Gaurav Mehta"))

    def test_insider_linked_to_a_management_filing(self):
        from indtrader.models.analytics.insiders import InsiderTracker
        tracker = InsiderTracker(self.market())
        trades = [{"source": "PIT", "kind": "sell", "symbol": "BAJAJHFL", "person": "Gaurav Kalani"}]
        filings = {"data": [{"desc": "Resignation", "attchmntText": "Resignation of Gaurav Kalani - Chief Financial Officer",
                             "an_dt": "23-Oct-2026 17:03:00"},
                            {"desc": "Updates", "attchmntText": "Gaurav Kalani attended a conference", "an_dt": "20-Oct-2026 10:00:00"}]}
        with mock.patch.object(tracker.market.nse, "announcements", return_value=filings):
            tracker.link_management_filings(trades, dt.date(2026, 9, 25), dt.date(2026, 10, 25), [])
        self.assertEqual([f["category"] for f in trades[0]["linked"]], ["Resignation"])

    def test_picker_points_are_graded(self):
        from indtrader.models.agents.stock_picker.picker import points
        leader = {"rs_20d": 24.7, "change_pct": 0.92, "buildup": None}
        self.assertEqual(points(leader, "long", count_oi=False), 2.92)
        self.assertEqual(points(leader, "short", count_oi=False), 0.0)
        self.assertEqual(points({"rs_20d": 4.66, "change_pct": 1.81, "buildup": None}, "long"), 2.43)


class TestSmallFixes(WorkspaceTest):
    def test_scan_date_is_the_last_session(self):
        code, out, _ = self.cli("scan", "daily", "--symbols", "RELIANCE,HDFCBANK", now="2026-10-25 12:00")
        self.assertIn("closes to 2026-10-2", out)
        self.assertNotIn("closes to 2026-10-25", out)

    def test_holdings_trend_keeps_two_filings_in_one_month_apart(self):
        from indtrader.views.research import holdings
        result = {"symbol": "X", "company": "X Ltd", "quarter": "2025-12-31", "previous_quarter": None, "filed": "-", "categories": [],
                  "holders": [], "promoter_trend": [{"quarter": "2025-10-31", "promoters": 0.0}, {"quarter": "2025-10-01", "promoters": 0.0},
                                                    {"quarter": "2025-09-30", "promoters": 0.0}], "link": None}
        text = holdings(result)
        self.assertIn("2025-10-31 0.00%, 2025-10-01 0.00%, 2025-09 0.00%", text)


if __name__ == "__main__":
    unittest.main()
