"""Investor research: insider trades, shareholding patterns, the screener and the tax arithmetic.

Offline on a snapshot recorded on Friday 23 October 2026 after the close
(BSE insider feed with personal fields removed, NSE SAST, shareholding
XBRL, NSE quote data for the Nifty 50, Yahoo daily closes).
"""

import datetime as dt
import gzip
import json
import os

from _base import HERE, WorkspaceTest

RESEARCH = os.path.join(HERE, "fixtures", "snap-2026-10-23-research")
NOW = "2026-10-23 16:00"


def _xbrl(name):
    with gzip.open(os.path.join(RESEARCH, name + ".gz"), "rt", encoding="utf-8") as fh:
        return fh.read()


RELIANCE_SEP = "nse-shp-SHP_1742991_21102026042504_WEB.xml"


class ResearchTest(WorkspaceTest):
    def _offline(self, *argv):
        """The CLI on the 23 October research snapshot: (exit code, stdout)."""
        code, out, _ = self.cli(*argv, "--offline", RESEARCH, offline=False, now=NOW)
        return code, out

    def research_ctx(self):
        from indtrader.core.context import AppContext
        return AppContext.create(now=NOW, offline=RESEARCH)


class TestInsiders(ResearchTest):
    def test_classify_and_pledge_wording(self):
        from indtrader.models.analytics.insiders import classify, pledge_label
        self.assertEqual(classify("Market Purchase", "Acquisition"), "buy")
        self.assertEqual(classify("Market Sale", "Disposal"), "sell")
        self.assertEqual(classify("Open Market", "sale"), "sell")
        self.assertEqual(classify("ESOP", "Acquisition"), "other")
        self.assertEqual(classify("Off Market", "Disposal"), "other")
        self.assertEqual(classify(None, "Invoke"), "pledge")
        # "Invoke" as a transaction type means a pledge was created; "Invocation of pledge" means the lender enforced it
        self.assertEqual(pledge_label("-", "Invoke"), "Pledge created")
        self.assertEqual(pledge_label("Pledge Creation", "Acquisition"), "Pledge created")
        self.assertEqual(pledge_label("Invocation of pledge", "Disposal"), "Pledge enforced")
        self.assertEqual(pledge_label("-", "Revoke"), "Pledge released")

    def test_symbol_matcher(self):
        from indtrader.models.analytics.insiders import SymbolMatcher
        match = SymbolMatcher({"NATCOPHARM": "Natco Pharma Limited", "KARURVYSYA": "Karur Vysya Bank Limited",
                               "ABC": "Alpha Ltd", "ABD": "Alpha Limited"})
        self.assertEqual(match("Natco Pharma Ltd"), "NATCOPHARM")
        self.assertEqual(match("KARUR VYSYA BANK LTD."), "KARURVYSYA")
        self.assertIsNone(match("Alpha Ltd"))            # two listed names reduce to the same key: refuse to guess
        self.assertIsNone(match("Unknown Co"))

    def test_personal_fields_are_dropped(self):
        from indtrader.models.data.bse import strip_personal
        record = {"Fld_PromoterName": "A Person", "Fld_PromoterPAN": "ABCDE1234F", "Fld_PromoterAdd": "street",
                  "Fld_PromoterContact": "99999", "Fld_PromoterCIN": "x", "Fld_PromoterDIN": "y",
                  "Fld_PercentofShareholdingPre": "1.2", "Companyname": "Natco Pharma Ltd"}
        self.assertEqual(sorted(strip_personal(record)), ["Companyname", "Fld_PercentofShareholdingPre", "Fld_PromoterName"])
        with open(os.path.join(RESEARCH, "bse-insider-2026-10-16-2026-10-23.json"), encoding="utf-8") as fh:
            text = fh.read()
        for field in ("PromoterPAN", "PromoterAdd", "PromoterContact"):
            self.assertNotIn(field, text)

    def test_dedupe_and_clusters(self):
        from indtrader.models.analytics.insiders import clusters, dedupe
        base = {"source": "PIT", "company": "K Bank", "symbol": "KB", "mode": "Market Sale", "qty": 2000.0,
                "traded_to": "2026-10-21", "value": 769230.0, "kind": "sell"}
        trades = dedupe([dict(base, person="A"), dict(base, person="A"), dict(base, person="B"), dict(base, person="C", kind="buy")])
        self.assertEqual(len(trades), 3)
        groups = clusters(trades)
        self.assertEqual([(g["symbol"], g["kind"], g["people"]) for g in groups], [("KB", "sell", ["A", "B"])])

    def test_collect_offline(self):
        from indtrader.models.analytics.insiders import InsiderTracker
        result = InsiderTracker(self.research_ctx().market).collect(self.now(NOW), days=7)
        self.assertEqual(result["errors"], [])
        self.assertEqual((result["from"], result["to"]), ("2026-10-16", "2026-10-23"))
        kinds = {t["kind"] for t in result["trades"]}
        self.assertNotIn("other", kinds)                  # ESOP, gifts ... hidden by default
        sast = [t for t in result["trades"] if t["source"] == "SAST"]
        self.assertEqual(len(sast), result["summary"]["sast"])
        samhi = next(t for t in sast if t["symbol"] == "SAMHI")
        self.assertEqual((samhi["side"], samhi["pct_after"], samhi["pct_change"]), ("acquisition", 5.06, 0.53))
        natco = next(t for t in result["trades"] if t["symbol"] == "NATCOPHARM" and t["kind"] == "buy")
        self.assertEqual((natco["qty"], natco["category"], natco["mode"]), (237963.0, "Promoter", "Market Purchase"))
        self.assertAlmostEqual(natco["price"], 35.52, places=2)
        ids = [t["id"] for t in result["trades"]]
        self.assertEqual(len(ids), len(set(ids)))
        everything = InsiderTracker(self.research_ctx().market).collect(self.now(NOW), days=7, show_all=True)
        self.assertGreater(len(everything["trades"]), len(result["trades"]))

    def test_symbols_filter_and_cli(self):
        code, out = self._offline("insiders", "KARURVYSYA", "--days", "7")
        self.assertEqual(code, 0)
        self.assertIn("KARURVYSYA", out)
        self.assertIn("SELL 3 people", out)
        self.assertNotIn("NATCOPHARM", out)
        code, out = self._offline("insiders", "--json")
        data = json.loads(out)
        self.assertTrue(all(not k.lower().endswith("pan") for t in data["trades"] for k in t))


class TestShareholding(ResearchTest):
    def test_parse_xbrl(self):
        from indtrader.models.analytics.shareholding import parse_xbrl
        parsed = parse_xbrl(_xbrl(RELIANCE_SEP))
        self.assertEqual((parsed["symbol"], parsed["date"]), ("RELIANCE", "2026-09-30"))
        cats = parsed["categories"]
        self.assertEqual(cats["ShareholdingOfPromoterAndPromoterGroup"], 50.44)
        self.assertEqual(cats["PublicShareholding"], 49.56)
        self.assertEqual(cats["MutualFundsOrUTI"], 10.31)
        self.assertEqual(cats["InstitutionsForeign"], 16.67)
        holders = {h["name"]: h for h in parsed["holders"]}
        self.assertEqual(holders["Life Insurance Corporation of India"]["pct"], 7.11)
        self.assertFalse(holders["Life Insurance Corporation of India"]["promoter"])
        self.assertTrue(holders["Mukesh D Ambani"]["promoter"])

    def test_bad_xbrl(self):
        from indtrader.models.analytics.shareholding import parse_xbrl
        from indtrader.core.errors import DataError
        with self.assertRaises(DataError):
            parse_xbrl("<xbrl></xbrl>")

    def test_holder_changes_match_loosely(self):
        from indtrader.models.analytics.shareholding import holder_changes
        latest = [{"name": "Reliance Industrial Investments and Holdings Lim", "pct": 3.62, "promoter": True},
                  {"name": "New Fund", "pct": 1.5, "promoter": False},
                  {"name": "Placeholder", "pct": 0.0, "promoter": False}]
        previous = [{"name": "Reliance Industrial Investments and Holdings Ltd", "pct": 3.60, "promoter": True},
                    {"name": "Old Fund", "pct": 1.1, "promoter": False}]
        rows = {r["name"]: r for r in holder_changes(latest, previous)}
        self.assertEqual(rows["Reliance Industrial Investments and Holdings Lim"]["change"], 0.02)
        self.assertEqual(rows["New Fund"]["status"], "new")
        self.assertEqual(rows["Old Fund"]["status"], "gone")
        self.assertNotIn("Placeholder", rows)

    def test_filings_keep_the_latest_revision(self):
        from indtrader.models.analytics.shareholding import filings
        rows = filings([{"date": "30-JUN-2026", "broadcastDate": "21-JUL-2026 10:00:00", "xbrl": "a"},
                        {"date": "30-JUN-2026", "broadcastDate": "02-AUG-2026 10:00:00", "xbrl": "b"},
                        {"date": "30-SEP-2026", "broadcastDate": "21-OCT-2026 10:00:00", "xbrl": "c"}])
        self.assertEqual([(r["quarter"], r["xbrl"]) for r in rows], [("2026-09-30", "c"), ("2026-06-30", "b")])

    def test_pattern_offline(self):
        from indtrader.models.analytics.shareholding import ShareholdingService
        result = ShareholdingService(self.research_ctx().market).pattern("RELIANCE")
        self.assertEqual((result["quarter"], result["previous_quarter"]), ("2026-09-30", "2026-06-30"))
        rows = {r["key"]: r for r in result["categories"]}
        self.assertEqual(rows["InstitutionsForeign"]["change"], -0.53)
        self.assertEqual(rows["InstitutionsDomestic"]["change"], 0.53)
        self.assertEqual(result["promoter_trend"][0], {"quarter": "2026-09-30", "promoters": 50.44, "public": 49.56})
        lic = next(h for h in result["holders"] if h["name"].startswith("Life Insurance"))
        self.assertEqual((lic["pct"], lic["change"], lic["status"]), (7.11, 0.23, "held"))

    def test_find_uses_aliases(self):
        from indtrader.models.analytics.shareholding import ShareholdingService, search_pattern
        self.assertTrue(search_pattern("life insurance").search("LIC of India"))
        self.assertTrue(search_pattern("LIC").search("Life Insurance Corporation of India"))
        self.assertFalse(search_pattern("LIC").search("Public Holdings"))
        result = ShareholdingService(self.research_ctx().market).find("life insurance", ["RELIANCE", "TCS", "ITC"])
        found = {(h["symbol"], h["pct"]) for h in result["hits"]}
        self.assertIn(("TCS", 5.65), found)
        self.assertIn(("ITC", 16.46), found)
        self.assertIn(("RELIANCE", 7.11), found)

    def test_cli(self):
        code, out = self._offline("holdings", "RELIANCE")
        self.assertEqual(code, 0)
        self.assertIn("shareholding at 2026-09-30", out)
        self.assertIn("Life Insurance Corporation of India", out)
        code, _ = self._offline("holdings")
        self.assertEqual(code, 1)                          # neither a symbol nor --find
        code, out = self._offline("holdings", "--find", "nobody-at-all", "RELIANCE")
        self.assertEqual(code, 1)
        self.assertIn("No holder matching", out)


class TestScreener(ResearchTest):
    def test_rule_ops(self):
        from indtrader.models.trading.screener import Rule
        self.assertTrue(Rule("x", ">", 1).check(2))
        self.assertFalse(Rule("x", "<=", 1).check(2))
        self.assertTrue(Rule("x", "between", [1, 3]).check(3))
        self.assertFalse(Rule("x", "between", [1, 3]).check(3.1))
        self.assertTrue(Rule("s", "in", ["it", "Energy"]).check("ENERGY"))
        self.assertTrue(Rule("s", "not in", ["IT"]).check("Energy"))
        self.assertTrue(Rule("fo", "==", True).check(True))
        self.assertTrue(Rule("s", "==", "energy").check("Energy"))
        self.assertEqual(Rule("x", "between", [1, 3]).describe(), "x between 1 and 3")

    def test_rule_validation(self):
        from indtrader.core.errors import ValidationError
        from indtrader.models.trading.screener import RuleSet
        for bad in ({}, {"rules": [{"metric": "pe", "op": "~", "value": 1}]}, {"rules": [{"metric": "pe", "op": "between", "value": 3}]},
                    {"rules": [{"metric": "s", "op": "in", "value": "IT"}]}, {"rules": [{"metric": "pe", "op": ">", "value": 1}], "missing": "maybe"},
                    {"rules": [{"metric": "pe", "op": ">", "value": 1}], "rank": [{"metric": "pe", "order": "up"}]}):
            with self.assertRaises(ValidationError, msg=bad):
                RuleSet.from_dict(bad)

    def test_evaluate_missing_and_score(self):
        from indtrader.models.trading.screener import RuleSet
        rules = RuleSet.from_dict({"rules": [{"metric": "pe", "op": "<", "value": 30}, {"metric": "rsi", "op": ">", "value": 50}],
                                   "rank": [{"metric": "ret_20d", "order": "desc"}]})
        self.assertEqual(rules.evaluate({"pe": 20.0, "rsi": 60.0}), (True, [], []))
        ok, failures, _ = rules.evaluate({"pe": 35.0})
        self.assertFalse(ok)
        self.assertEqual(failures, ["pe 35.00, needs < 30", "rsi is missing"])
        rules.missing = "skip"
        self.assertEqual(rules.evaluate({"pe": 20.0}), (True, [], ["rsi is missing"]))
        passed = [{"metrics": {"ret_20d": 10.0}}, {"metrics": {"ret_20d": 0.0}}, {"metrics": {}}]
        rules.score(passed)
        self.assertEqual([p["score"] for p in passed], [1.0, 0.0, 0.0])

    def test_quote_metrics(self):
        from indtrader.models.trading.screener import close_metrics, quote_metrics
        with open(os.path.join(RESEARCH, "nse-info-TCS.json"), encoding="utf-8") as fh:
            info = json.load(fh)["equityResponse"][0]
        metrics = quote_metrics(info, fo=True)
        self.assertEqual(metrics["price"], 2525.6)
        self.assertEqual(metrics["sector"], "Information Technology")
        self.assertAlmostEqual(metrics["pe_vs_sector"], metrics["pe"] / metrics["sector_pe"], places=2)
        self.assertLess(metrics["pct_from_high"], 0)
        self.assertEqual(close_metrics([100.0] * 10), {})
        rising = close_metrics([100.0 + i for i in range(250)])
        self.assertGreater(rising["vs_ema50"], 0)
        self.assertGreater(rising["rsi"], 70)
        self.assertAlmostEqual(rising["ret_20d"], (349 / 329 - 1) * 100, places=2)

    def test_cli_momentum(self):
        code, out = self._offline("screen", "--preset", "momentum", "--list", "nifty50")
        self.assertEqual(code, 0)
        self.assertIn("5 of 50 stocks pass", out)
        first = [line for line in out.splitlines() if line.startswith("1 ")][0]
        self.assertIn("TCS", first)
        code, out = self._offline("screen", "--symbols", "TCS")
        self.assertEqual(code, 1)                          # no preset, no rules file


class TestTax(ResearchTest):
    def test_dates(self):
        from indtrader.models.trading.tax import financial_year, fy_bounds, long_term_from
        self.assertEqual(financial_year(dt.date(2026, 3, 31)), "2025-26")
        self.assertEqual(financial_year(dt.date(2026, 4, 1)), "2026-27")
        self.assertEqual(fy_bounds("2026-27"), (dt.date(2026, 4, 1), dt.date(2027, 3, 31)))
        self.assertEqual(long_term_from(dt.date(2025, 6, 2)), dt.date(2026, 6, 3))
        self.assertEqual(long_term_from(dt.date(2024, 2, 29)), dt.date(2025, 3, 1))

    def test_business_income(self):
        from indtrader.models.trading.tax import ClosedTrade, business_income, tax_settings
        trades = [ClosedTrade(dt.date(2026, 10, 23), "N", "fno", 1950, 92.4), ClosedTrade(dt.date(2026, 10, 22), "N", "fno", -1300, 88.1),
                  ClosedTrade(dt.date(2026, 3, 30), "N", "fno", 5000, 50), ClosedTrade(dt.date(2026, 9, 15), "S", "intraday", -400, 30)]
        income = business_income(trades, "2026-27", tax_settings(self.cfg()))
        self.assertEqual(income["fno"]["trades"], 2)                         # the March trade is last year
        self.assertEqual(income["fno"]["turnover"], 3250)                    # |1950| + |-1300|
        self.assertEqual(income["fno"]["net"], round(650 - 180.5, 2))
        self.assertFalse(income["fno"]["audit_likely"])
        self.assertEqual(income["intraday"]["net"], -430)

    def test_capital_gains_offsets(self):
        from indtrader.models.trading.tax import capital_gains_estimate, tax_settings
        rules = tax_settings(self.cfg())
        gains = capital_gains_estimate({"short_term": -30000, "long_term": 200000}, rules)
        self.assertEqual(gains["net_long_term"], 170000)                     # short-term loss set off first
        self.assertEqual(gains["taxable_long_term"], 45000)
        self.assertEqual(gains["tax_at_listed_rates"], 5625)                 # 12.5 % of 45,000
        gains = capital_gains_estimate({"short_term": 50000, "long_term": -20000}, rules)
        self.assertEqual(gains["net_short_term"], 50000)                     # a long-term loss never offsets short-term gains
        self.assertEqual(gains["carry_forward_loss"], 20000)
        self.assertEqual(gains["tax_at_listed_rates"], 10000)

    def _portfolio(self):
        with open(os.path.join(self.home, "portfolio.json"), "w", encoding="utf-8-sig") as fh:      # a BOM, as Notepad writes it
            json.dump({"positions": {"INFY": {"lots": [{"id": "INFY-2", "date": "2026-02-01", "qty": 5, "cost": 8500},
                                                       {"id": "INFY-1", "date": "2025-03-10", "qty": 10, "cost": 16000}]},
                                     "ITC": {"lots": [{"id": "ITC-1", "date": "2024-11-04", "qty": 100, "cost": 30000}]}}}, fh)
        from indtrader.models.trading.tax import Portfolio, tax_settings
        return Portfolio(tax_settings(self.cfg()))

    def test_sell_fifo_and_record(self):
        portfolio = self._portfolio()
        preview = portfolio.sell_preview("INFY", 12, 1450, dt.date(2026, 10, 23), charges=24)
        self.assertEqual([(p["lot"], p["qty"], p["term"]) for p in preview["parts"]], [("INFY-1", 10, "long"), ("INFY-2", 2, "short")])
        self.assertEqual(preview["long_term"], round(14500 - 20 - 16000, 2))
        self.assertEqual(preview["short_term"], round(2900 - 4 - 3400, 2))
        portfolio.record_sale(preview)
        saved = self.read("portfolio.json")["positions"]["INFY"]["lots"]
        self.assertEqual(saved, [{"id": "INFY-2", "date": "2026-02-01", "qty": 3.0, "cost": 5100.0}])
        self.assertEqual(portfolio.realised("2026-27")["sales"], 1)
        from indtrader.core.errors import ValidationError
        with self.assertRaises(ValidationError):
            portfolio.sell_preview("INFY", 4, 1450, dt.date(2026, 10, 23))  # only 3 left

    def test_harvest(self):
        from indtrader.models.trading.tax import harvest
        result = harvest(self._portfolio(), {"INFY": 1450.0, "ITC": 400.0}, dt.date(2026, 10, 23), min_loss=1000)
        self.assertEqual([(v["id"], v["gain"]) for v in result["losses"]], [("INFY-1", -1500.0), ("INFY-2", -1250.0)])
        self.assertEqual([(v["id"], v["gain"]) for v in result["exempt_gains"]], [("ITC-1", 10000.0)])
        self.assertEqual(result["exemption_room"], 125000)

    def test_csv_import(self):
        from indtrader.core.errors import ValidationError
        from indtrader.models.trading.tax import trades_from_csv
        path = os.path.join(self.home, "pnl.csv")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("Date,Symbol,Segment,PnL,Charges\n2026-10-23,NIFTY,fno,\"1,950\",92.4\n")
        self.assertEqual(trades_from_csv(path)[0].gross, 1950)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("2026-10-24,NIFTY,delivery,10,1\n")
        with self.assertRaises(ValidationError):
            trades_from_csv(path)

    def test_cli_report(self):
        with open(os.path.join(self.home, "paper.json"), "w", encoding="utf-8") as fh:
            json.dump({"trades": [{"status": "closed", "type": "option", "symbol": "NIFTY", "closed": "2026-10-23T10:40",
                                   "gross": -1950, "charges": 92.4}]}, fh)
        code, out = self._offline("tax", "report")
        self.assertEqual(code, 0)
        self.assertIn("FY 2026-27", out)
        self.assertIn("F&O loss", out)
        self.assertIn("Not tax advice", out)
