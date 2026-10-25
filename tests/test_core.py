"""Formatting, settings, errors, the NSE clock, indicators and Black-Scholes."""

import datetime as dt
import json
import math
import os
import unittest

from _base import SNAP, WorkspaceTest, session

from indtrader.core import clock, settings
from indtrader.core.errors import ConfigError, DataError, IndianTraderError, NetworkError, ValidationError
from indtrader.core.formatting import inr, round_tick
from indtrader.models.analytics import blackscholes as bs
from indtrader.models.analytics import indicators as ind

D = dt.date


class TestFormatting(unittest.TestCase):
    def test_indian_grouping(self):
        self.assertEqual(inr(1234567.5), "₹12,34,567.50")
        self.assertEqual(inr(100000), "₹1,00,000.00")
        self.assertEqual(inr(999), "₹999.00")
        self.assertEqual(inr(12345678901), "₹12,34,56,78,901.00")
        self.assertEqual(inr(-3380.444), "-₹3,380.44")
        self.assertEqual(inr(0.999), "₹1.00")
        self.assertEqual(inr(-0.001), "₹0.00")
        self.assertEqual(inr(50, sign=True), "+₹50.00")

    def test_tick_rounding(self):
        self.assertEqual(round_tick(109.33, 0.05, "down"), 109.30)
        self.assertEqual(round_tick(109.31, 0.05, "up"), 109.35)
        self.assertEqual(round_tick(255.425), 255.45)
        self.assertEqual(round_tick(22624.27, 0.05, "down"), 22624.25)


class TestErrorsAndSettings(WorkspaceTest):
    def test_hierarchy(self):
        for cls in (ConfigError, ValidationError, DataError, NetworkError):
            self.assertTrue(issubclass(cls, IndianTraderError))
        self.assertTrue(issubclass(NetworkError, DataError))
        self.assertEqual(IndianTraderError.exit_code, 1)

    def test_defaults_and_merge(self):
        self.config(capital=250000, charges={"gst_pct": 12.0})
        cfg = settings.load()
        self.assertEqual(cfg["capital"], 250000)
        self.assertEqual(cfg["charges"]["gst_pct"], 12.0)
        self.assertEqual(cfg["charges"]["brokerage_per_order"], 20.0)      # untouched nested default
        self.assertEqual(cfg["risk_free_rate_pct"], 10.0)

    def test_validation(self):
        for bad in ({"capital": -5}, {"max_loss_per_trade": "lots"}, {"square_off_by": "3pm"}, {"blocked": "TCS"}):
            self.config(**bad)
            with self.assertRaises(ConfigError, msg=str(bad)):
                settings.load()
        with open(os.path.join(self.home, "config.json"), "w") as fh:
            fh.write("{not json")
        with self.assertRaises(ConfigError):
            settings.load()

    def test_init(self):
        path, created = settings.init()
        self.assertTrue(created and os.path.exists(path))
        self.assertFalse(settings.init()[1])


class TestClock(WorkspaceTest):
    def test_trading_days(self):
        self.assertFalse(clock.is_trading_day(D(2026, 10, 20)))      # Dussehra
        self.assertFalse(clock.is_trading_day(D(2026, 10, 24)))      # Saturday
        self.assertTrue(clock.is_trading_day(D(2026, 10, 22)))
        self.assertEqual(clock.next_trading_day(D(2026, 10, 19)), D(2026, 10, 21))
        self.assertEqual(clock.prev_trading_day(D(2026, 10, 21)), D(2026, 10, 19))
        self.assertEqual(clock.holiday_name(D(2026, 11, 10)), "Diwali-Balipratipada")

    def test_market_status(self):
        status = clock.market_status(clock.parse_now("2026-10-22 10:30"))
        self.assertEqual((status["state"], status["minutes_to_close"]), ("open", 300))
        self.assertEqual(clock.market_status(clock.parse_now("2026-10-22 09:05"))["state"], "pre-open")
        status = clock.market_status(clock.parse_now("2026-10-23 16:00"))
        self.assertEqual(status["state"], "closed")
        self.assertTrue(status["next_open"].startswith("2026-10-26T09:15"))
        status = clock.market_status(clock.parse_now("2026-10-20 11:00"))
        self.assertEqual((status["state"], status["reason"]), ("closed", "Dussehra"))

    def test_expiry_rule_matches_nse(self):
        with open(SNAP + "/nse-oc-info-NIFTY.json", encoding="utf-8") as fh:
            nse = [dt.datetime.strptime(e, "%d-%b-%Y").date() for e in json.load(fh)["expiryDates"][:6]]
        found, day = [], D(2026, 10, 22)
        for _ in range(6):
            expiry = clock.weekly_expiry("NIFTY", day)
            found.append(expiry)
            day = expiry + dt.timedelta(days=1)
        self.assertEqual(found, nse)          # includes Mon 9 Nov and Mon 23 Nov (holiday shifts)
        self.assertEqual(clock.monthly_expiry("BANKNIFTY", D(2026, 10, 28)), D(2026, 11, 23))
        self.assertEqual(clock.monthly_expiry("BANKNIFTY", D(2026, 11, 24)), D(2026, 12, 29))

    def test_nse_holiday_parser_matches_builtin(self):
        with open(SNAP + "/nse-holidays.json", encoding="utf-8") as fh:
            self.assertEqual(set(clock.parse_nse_holidays(json.load(fh))), set(clock.HOLIDAYS_2026))

    def test_parse_now(self):
        self.assertEqual(clock.parse_now("2026-10-22 10:30").utcoffset(), dt.timedelta(hours=5, minutes=30))
        with self.assertRaises(ValidationError):
            clock.parse_now("yesterday")
        with self.assertRaises(ValidationError):
            clock.parse_hhmm("3pm")


class TestIndicators(unittest.TestCase):
    def test_sma_ema(self):
        self.assertEqual(ind.sma([1, 2, 3, 4], 2), [None, 1.5, 2.5, 3.5])
        values = ind.ema([1, 2, 3, 4, 5], 3)
        self.assertEqual(values[:2], [None, None])
        for got, want in zip(values[2:], (2.0, 3.0, 4.0)):
            self.assertAlmostEqual(got, want)

    def test_rsi(self):
        self.assertEqual(ind.rsi(list(range(1, 20)))[-1], 100.0)
        self.assertEqual(ind.rsi(list(range(20, 1, -1)))[-1], 0.0)
        self.assertTrue(40 < ind.rsi([10, 11] * 15)[-1] < 60)

    def test_atr_and_vwap(self):
        bars = session("2026-10-22", [100] * 20, spread=1.0)
        self.assertAlmostEqual(ind.atr(bars, 14)[-1], 2.0)
        values, has_volume = ind.vwap(bars)
        self.assertTrue(has_volume)
        self.assertAlmostEqual(values[-1], 100.0)

    def test_supertrend_follows_trend(self):
        self.assertEqual(ind.supertrend(session("2026-10-22", [100 + i for i in range(40)]))[1][-1], 1)
        self.assertEqual(ind.supertrend(session("2026-10-22", [140 - i for i in range(40)]))[1][-1], -1)

    def test_pivots_and_cpr(self):
        p = ind.pivots(23120.90, 22649.95, 22811.35)
        self.assertAlmostEqual(p["P"], 22860.73, places=2)
        # (H+L)/2 = 22885.425 is above P here, so it becomes TC and 2P - BC becomes BC
        self.assertAlmostEqual(p["TC"], 22885.425, places=3)
        self.assertAlmostEqual(p["BC"], 22836.04, places=2)
        self.assertAlmostEqual(p["R1"], 23071.52, places=2)

    def test_opening_range(self):
        bars = session("2026-10-22", [100, 102, 101, 103])
        self.assertEqual(ind.opening_range(bars, 15, 5), (103.0, 99.0, 3))
        self.assertIsNone(ind.opening_range(bars[:2], 15, 5))
        self.assertIsNone(ind.opening_range(bars[1:], 15, 5))           # the 09:15 bar is missing


class TestBlackScholes(unittest.TestCase):
    def test_textbook_values(self):
        self.assertAlmostEqual(bs.price("CE", 100, 100, 1, 0.05, 0.2), 10.4506, places=4)
        self.assertAlmostEqual(bs.price("PE", 100, 100, 1, 0.05, 0.2), 5.5735, places=4)

    def test_put_call_parity(self):
        spot, strike, years, rate, sigma = 22687.65, 22700, 4.7 / 365, 0.065, 0.144
        call, put = bs.price("CE", spot, strike, years, rate, sigma), bs.price("PE", spot, strike, years, rate, sigma)
        self.assertAlmostEqual(call - put, spot - strike * math.exp(-rate * years), places=6)

    def test_implied_vol_round_trip(self):
        premium = bs.price("CE", 22687.65, 22700, 0.0129, 0.065, 0.142)
        self.assertAlmostEqual(bs.implied_vol("CE", premium, 22687.65, 22700, 0.0129, 0.065), 0.142, places=4)
        self.assertIsNone(bs.implied_vol("CE", 0.0, 100, 100, 0.1, 0.05))

    def test_greeks(self):
        call = bs.greeks("CE", 100, 100, 0.5, 0.05, 0.2)
        put = bs.greeks("PE", 100, 100, 0.5, 0.05, 0.2)
        self.assertTrue(0.5 < call["delta"] < 0.65)
        self.assertLess(call["theta"], 0)
        self.assertAlmostEqual(call["delta"] - put["delta"], 1.0, places=9)


if __name__ == "__main__":
    unittest.main()
