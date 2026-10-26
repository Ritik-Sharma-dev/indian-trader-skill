"""Chart analysis for one symbol: indicators, levels and a plain summary.

Intraday (1m / 5m / 15m / 1h): VWAP, EMA 9/21, SuperTrend(10, 3), RSI(14),
ATR, the opening range, the previous day's high / low / close with CPR and
floor pivots, and, once the session is complete, the levels for the NEXT
session (from the exchange's official high / low / close for indices).

Daily: EMA 20/50/200, RSI, MACD, Bollinger bands, ATR, the 52-week range and
swing levels.

The output describes the chart; it does not predict it.
"""

import datetime as dt
import logging
import re
from typing import List, Optional

from indtrader.core import clock
from indtrader.core.errors import DataError, IndianTraderError
from indtrader.core.formatting import num
from indtrader.models.analytics import indicators as ind
from indtrader.models.data import bars as barlib
from indtrader.models.data.feeds import parse_time
from indtrader.models.data.symbols import is_index

log = logging.getLogger(__name__)

DATA_CHECK_PCT = 0.2
EVENT_FILINGS = re.compile(r"financial result|outcome of board meeting|\bresults?\b|acquisition|amalgamation|merger|scheme of arrangement"
                           r"|resignation|insolvency|fraud|default", re.I)


def _untraded(session: List[dict]) -> bool:
    if len(session) < 6:
        return False
    traded = sum(1 for b in session if b["v"])
    return traded < len(session) / 2 or len({b["c"] for b in session}) <= 3


class ChartAnalyzer:
    def __init__(self, market) -> None:
        self.market = market

    def analyze(self, symbol: str, interval: str = "5m", rng: Optional[str] = None, day: Optional[dt.date] = None,
                now: Optional[dt.datetime] = None, or_minutes: int = 15) -> dict:
        minutes = barlib.interval_minutes(interval)
        rng = rng or ("5d" if minutes else "1y")
        _, bars = self.market.candles(symbol, interval, rng)
        if minutes:
            bars = barlib.closed(bars, now, interval)
        else:
            bars = [b for b in bars if b["t"].date() <= now.date()]
            if interval == "1d":
                bars = self.market.fill_daily_holes(symbol, bars, now)
        if not bars:
            raise DataError("no bars for %s" % symbol)
        result = {"symbol": symbol.upper(), "interval": interval, "as_of": None, "signals": [], "levels": {}}
        if minutes:
            self._intraday(result, symbol, bars, day, minutes, or_minutes)
            last_close = bars[-1]["t"] + dt.timedelta(minutes=minutes)
        else:
            self._daily(result, bars)
            self._check_daily(result, symbol, bars[-1])
            last_close = clock.at(bars[-1]["t"].date(), clock.CLOSE)
        if not day:
            self._events_since(result, symbol, last_close, now)
        log.debug("%s %s: trend %s", symbol, interval, result["trend"])
        return result

    def _events_since(self, out: dict, symbol: str, since: dt.datetime, now: dt.datetime) -> None:
        """Results and other company events filed after the chart's last bar: the chart has not priced them yet."""
        if is_index(symbol) or "." in symbol or now <= since:
            return
        try:
            payload = self.market.nse.announcements(symbol.upper(), since.date(), now.date())
        except IndianTraderError as exc:
            log.info("no filings check for %s: %s", symbol, exc)
            return
        rows = payload if isinstance(payload, list) else (payload or {}).get("data") or []
        events = []
        for record in rows:
            stamp = parse_time(record.get("sort_date") or record.get("an_dt"))
            text = "%s %s" % (record.get("desc") or "", record.get("attchmntText") or "")
            if stamp and since < stamp <= now and EVENT_FILINGS.search(text):
                events.append({"time": stamp.strftime("%Y-%m-%d %H:%M"), "category": (record.get("desc") or "").strip()})
        if events:
            out["events_since"] = events
            out["signals"].insert(0, "EVENT after the last bar: %s (filed %s IST). The chart does not reflect it yet." % (
                events[0]["category"], events[0]["time"]))

    # -- intraday ----------------------------------------------------------------------

    def _intraday(self, out: dict, symbol: str, bars: List[dict], day: Optional[dt.date], minutes: int,
                  or_minutes: int) -> None:
        sessions = barlib.by_session(bars)
        days = sorted(sessions)
        day = day or days[-1]
        if day not in sessions:
            raise DataError("no %dm bars for %s on %s" % (minutes, symbol, day))
        session = sessions[day]
        trading = barlib.continuous(session) or session
        upto = [b for b in barlib.continuous(bars) if b["t"].date() < day] + trading
        closes = [b["c"] for b in upto]
        ema9, ema21 = ind.ema(closes, 9), ind.ema(closes, 21)
        vwap, has_volume = ind.vwap(upto)
        st_line, st_dir = ind.supertrend(upto)
        rsi = ind.rsi(closes)
        atr = ind.atr(upto)
        last = session[-1]
        complete = last["t"].time() >= dt.time(15, 25)
        out["as_of"] = (last["t"] + dt.timedelta(minutes=minutes)).isoformat(timespec="minutes")
        out.update({"date": day.isoformat(), "last": last["c"], "last_trade": trading[-1]["c"], "open": session[0]["o"],
                    "day_high": max(b["h"] for b in session), "day_low": min(b["l"] for b in session),
                    "ema9": ind.last(ema9), "ema21": ind.last(ema21), "vwap": vwap[-1], "vwap_has_volume": has_volume,
                    "supertrend": st_line[-1], "supertrend_dir": st_dir[-1], "rsi": rsi[-1], "atr": atr[-1]})
        if len(trading) < len(session):
            out["auction"] = {"close": last["c"], "last_trade": trading[-1]["c"],
                              "last_trade_time": (trading[-1]["t"] + dt.timedelta(minutes=minutes)).strftime("%H:%M"),
                              "move_pct": (last["c"] / trading[-1]["c"] - 1) * 100}
        official = self.market.official_day(symbol, day) if complete else None
        if official and official.get("close"):
            out["official"] = official
            reference = official["close"] if out.get("auction") else official.get("last")
            out["data_check_pct"] = (last["c"] / reference - 1) * 100 if reference else None
            out["data_check_against"] = reference
            out["last"] = official["close"]
        opening = ind.opening_range(session, or_minutes, minutes)
        if opening:
            out["levels"]["or_high"], out["levels"]["or_low"] = opening[0], opening[1]
        position = days.index(day)
        if position > 0:
            prev = sessions[days[position - 1]]
            high, low, close = max(b["h"] for b in prev), min(b["l"] for b in prev), prev[-1]["c"]
            out["prev_day"] = {"date": days[position - 1].isoformat(), "high": high, "low": low, "close": close}
            out["gap_pct"] = (session[0]["o"] / close - 1) * 100
            out["change_pct"] = (out["last"] / close - 1) * 100
            out["levels"].update({"pdh": high, "pdl": low, "pdc": close})
            out["pivots"] = ind.pivots(high, low, close)
        if complete:
            out["next_session"] = self._next_session_levels(symbol, out, session)

        price = trading[-1]["c"]
        signals = out["signals"]
        if has_volume and _untraded(trading):
            out["trend"] = "untraded"
            out["signals"] = ["too little trading for indicators: %d of %d bars traded, %d distinct prices" % (
                sum(1 for b in trading if b["v"]), len(trading), len({b["c"] for b in trading}))]
            out["series"] = {"bars": trading, "vwap": vwap[-len(trading):], "ema9": ema9[-len(trading):], "ema21": ema21[-len(trading):],
                             "st": st_line[-len(trading):], "rsi": rsi[-len(trading):]}
            return
        if out.get("auction"):
            a = out["auction"]
            signals.append("closing auction set the close at %s (%+.2f%% vs the last continuous trade %s at %s); indicators are read at %s"
                           % (num(a["close"]), a["move_pct"], num(a["last_trade"]), a["last_trade_time"], a["last_trade_time"]))
        if out.get("data_check_pct") is not None and abs(out["data_check_pct"]) > DATA_CHECK_PCT:
            signals.append("data check: the bars end at %s but NSE has %s (%+.2f%%); NSE's official close is %s"
                           % (num(last["c"]), num(out["data_check_against"]), out["data_check_pct"], num(out["official"]["close"])))
        signals.append("price %s VWAP%s (%s)" % ("above" if price > vwap[-1] else "below",
                                                 "" if has_volume else " [TWAP: index has no volume]", num(vwap[-1])))
        if out["ema9"] and out["ema21"]:
            rising = out["ema9"] > out["ema21"]
            signals.append("EMA 9 %s EMA 21: short-term trend %s" % (">" if rising else "<", "up" if rising else "down"))
        if st_dir[-1]:
            signals.append("SuperTrend %s (line %s)" % ("UP" if st_dir[-1] > 0 else "DOWN", num(st_line[-1])))
        if rsi[-1] is not None:
            signals.append("RSI %.0f%s" % (rsi[-1], " overbought" if rsi[-1] > 70 else " oversold" if rsi[-1] < 30 else ""))
        if opening:
            where = "above it" if price > opening[0] else "below it" if price < opening[1] else "inside it"
            signals.append("opening range %s - %s: price is %s" % (num(opening[1]), num(opening[0]), where))
        if out.get("pivots"):
            width = out["pivots"]["cpr_width_pct"]
            character = "narrow, trending day more likely" if width < 0.25 else "wide, range day more likely" if width > 0.6 else "normal"
            signals.append("CPR %s - %s (width %.2f%%: %s)" % (num(out["pivots"]["BC"]), num(out["pivots"]["TC"]), width, character))
        score = sum([price > vwap[-1], (out["ema9"] or 0) > (out["ema21"] or 0), (st_dir[-1] or 0) > 0]) * 2 - 3
        out["trend"] = "bullish" if score >= 3 else "bearish" if score <= -3 else "mixed"
        tail = len(trading)
        out["series"] = {"bars": trading, "vwap": vwap[-tail:], "ema9": ema9[-tail:], "ema21": ema21[-tail:],
                         "st": st_line[-tail:], "rsi": rsi[-tail:]}

    def _next_session_levels(self, symbol: str, out: dict, session: List[dict]) -> dict:
        """Pivots for the next session; indices use the exchange's official
        high / low / close when it belongs to this session."""
        high, low, close = out["day_high"], out["day_low"], session[-1]["c"]
        official = self.market.official_index_quote(symbol) if is_index(symbol) else None
        if official and official.get("day_high") and abs(official["price"] - close) / close < 0.002:
            high, low, close = official["day_high"], official["day_low"], official["price"]
        day = out.get("official")
        if day and day.get("high") and day.get("low"):
            high, low, close = day["high"], day["low"], day["close"]
        return {"high": high, "low": low, "close": close, "pivots": ind.pivots(high, low, close)}

    # -- daily --------------------------------------------------------------------------

    def _check_daily(self, out: dict, symbol: str, bar: dict) -> None:
        official = self.market.official_day(symbol, bar["t"].date())
        if not (official and official.get("close")):
            return
        out["official"] = official
        out["data_check_pct"] = (bar["c"] / official["close"] - 1) * 100
        if abs(out["data_check_pct"]) > DATA_CHECK_PCT:
            out["signals"].append("data check: the last daily bar closes at %s but NSE's official close is %s (%+.2f%%)"
                                  % (num(bar["c"]), num(official["close"]), out["data_check_pct"]))

    @staticmethod
    def _daily(out: dict, bars: List[dict]) -> None:
        closes = [b["c"] for b in bars]
        ema20, ema50, ema200 = ind.ema(closes, 20), ind.ema(closes, 50), ind.ema(closes, 200)
        rsi = ind.rsi(closes)
        macd_line, macd_signal, _ = ind.macd(closes)
        bb_upper, _, bb_lower = ind.bollinger(closes)
        atr = ind.atr(bars)
        last = bars[-1]
        year = bars[-250:]
        high_52w, low_52w = max(b["h"] for b in year), min(b["l"] for b in year)
        out["as_of"] = last["t"].date().isoformat()
        out.update({"last": last["c"], "change_pct": (last["c"] / bars[-2]["c"] - 1) * 100 if len(bars) > 1 else None,
                    "ema20": ema20[-1], "ema50": ema50[-1], "ema200": ema200[-1], "rsi": rsi[-1],
                    "macd": macd_line[-1], "macd_signal": macd_signal[-1], "atr": atr[-1],
                    "atr_pct": atr[-1] / last["c"] * 100 if atr[-1] else None,
                    "high_52w": high_52w, "low_52w": low_52w, "bb_upper": bb_upper[-1], "bb_lower": bb_lower[-1]})
        out["levels"]["swing"] = [{"level": level, "touches": n, "kind": kind}
                                  for level, n, kind in ind.swing_levels(bars[-120:])]
        price = last["c"]
        signals = out["signals"]
        for name, value in (("EMA 20", ema20[-1]), ("EMA 50", ema50[-1]), ("EMA 200", ema200[-1])):
            if value:
                signals.append("price %s %s (%s)" % ("above" if price > value else "below", name, num(value)))
        if rsi[-1] is not None:
            signals.append("RSI %.0f%s" % (rsi[-1], " overbought" if rsi[-1] > 70 else " oversold" if rsi[-1] < 30 else ""))
        if macd_line[-1] is not None and macd_signal[-1] is not None:
            signals.append("MACD %s signal" % ("above" if macd_line[-1] > macd_signal[-1] else "below"))
        signals.append("%.1f%% below the 52-week high, %.1f%% above the low" % ((1 - price / high_52w) * 100, (price / low_52w - 1) * 100))
        if out["atr_pct"]:
            signals.append("ATR(14) %s = %.2f%% a day" % (num(atr[-1]), out["atr_pct"]))
        score = sum(1 if (v and price > v) else -1 for v in (ema20[-1], ema50[-1], ema200[-1]))
        out["trend"] = "bullish" if score >= 2 else "bearish" if score <= -2 else "mixed"
        tail = min(len(bars), 120)
        out["series"] = {"bars": bars[-tail:], "ema20": ema20[-tail:], "ema50": ema50[-tail:], "ema200": ema200[-tail:],
                         "rsi": rsi[-tail:]}
