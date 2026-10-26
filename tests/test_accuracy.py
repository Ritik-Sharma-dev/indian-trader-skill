"""Accuracy against the exchanges' own numbers (found by cross-checking the
22 Oct 2026 session against NSE, BSE and Yahoo)."""

import datetime as dt
import unittest

from _base import WorkspaceTest, session

from indtrader.core import clock
from indtrader.models.analytics import blackscholes as bs
from indtrader.models.analytics.option_chain import OptionChainService, chain_time
from indtrader.models.data import bars as barlib


class TestAccuracy(WorkspaceTest):
    def test_iv_matches_nse_convention(self):
        # NSE's chain IVs = Black-Scholes on spot, 10% rate, calendar time from the close
        moment = self.now("2026-10-22 23:25")
        chain = OptionChainService(self.market()).fetch("NIFTY", moment)
        self.assertEqual(chain_time(chain, moment), clock.parse_now("2026-10-22 15:40"))
        years = clock.years_to(clock.expiry_close(chain["expiry"]), chain_time(chain, moment))
        atm = next(i for i, r in enumerate(chain["rows"]) if r["strike"] == 22700)
        gaps = []
        for row in chain["rows"][atm - 5: atm + 6]:
            for kind, key in (("CE", "ce"), ("PE", "pe")):
                leg = row[key]
                gaps.append(abs(bs.implied_vol(kind, leg["ltp"], chain["spot"], row["strike"], years, 0.10) * 100 - leg["iv"]))
        self.assertLess(sum(gaps) / len(gaps), 0.25)

    def test_wick_trimming(self):
        bars = session("2026-10-22", [100 + (i % 3) * 0.1 for i in range(40)], spread=0.05)
        bars[-1]["h"] = 102.5                     # a fake 2.3% auction wick (Sensex had 1,500 points)
        bars[5]["l"] = 98.0
        real = session("2026-10-22", [100, 100.2, 101.5, 101.6], spread=0.05)   # a real move: big body
        self.assertEqual(barlib.trim_wicks(bars), 2)
        self.assertEqual(bars[-1]["h"], max(bars[-1]["o"], bars[-1]["c"]))
        self.assertEqual(barlib.trim_wicks(real), 0)

    def test_sensex_bars_are_cleaned(self):
        market = self.market()
        meta, bars = market.candles("SENSEX", "5m", "5d")
        day = [b for b in bars if b["t"].date() == dt.date(2026, 10, 22)]
        self.assertGreater(meta["wicks_trimmed"], 0)
        self.assertLess(max(b["h"] for b in day), 73800)          # BSE official high 73,720.83
        self.assertGreater(min(b["l"] for b in day), 72900)       # BSE official low 73,005.11
        meta, _ = market.candles("NIFTY", "5m", "60d")
        self.assertLessEqual(meta["wicks_trimmed"], 3)            # clean data is left alone
        meta, _ = market.candles("RELIANCE", "5m", "1d")
        self.assertNotIn("wicks_trimmed", meta)                   # stocks keep their real wicks

    def test_official_index_quotes(self):
        market = self.market()
        vix = market.quote("INDIAVIX")
        self.assertEqual((vix["source"], vix["price"]), ("NSE", 15.82))
        self.assertAlmostEqual(vix["change"], 0.14, places=2)
        bank = market.quote("BANKNIFTY")
        self.assertEqual((bank["source"], bank["price"], bank["prev_close"]), ("NSE", 54925.7, 54976.9))
        sensex = market.quote("SENSEX")
        self.assertEqual((sensex["source"], sensex["day_high"], sensex["day_low"]), ("BSE", 73720.83, 73005.11))
        self.assertAlmostEqual(sensex["change"], -460.30, places=2)
        self.assertEqual(market.quote("RELIANCE")["source"], "Yahoo")


if __name__ == "__main__":
    unittest.main()
