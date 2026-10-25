"""Multi-timeframe, multi-index chart reading.

Each chart (an index on one timeframe) gets four trend votes from its
closed bars: close vs EMA 21, EMA 9 vs EMA 21, SuperTrend direction, MACD vs
its signal line. The sum (-4 ... +4) is the chart's trend: UP at +2 or more,
DOWN at -2 or less, otherwise SIDEWAYS.

Timeframes are weighted by how much they matter for an intraday trade
(daily 3, hourly 2, 15-minute 2, 5-minute 1): the weighted share of UP vs
DOWN charts is the index's alignment. Across indices it flags divergence
(NIFTY and BANKNIFTY pulling apart) and fear (India VIX rising while NIFTY
falls). A reading, not a signal: the decision maker uses alignment only as
a confidence vote.
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from indtrader.core.errors import DataError, IndianTraderError
from indtrader.core.formatting import pct
from indtrader.models.analytics import indicators as ind
from indtrader.models.data import bars as barlib

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Timeframe:
    interval: str
    rng: str
    weight: int


TIMEFRAMES: Sequence[Timeframe] = (Timeframe("5m", "5d", 1), Timeframe("15m", "1mo", 2), Timeframe("1h", "6mo", 2), Timeframe("1d", "1y", 3))
INDICES: Sequence[str] = ("NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX")


def _sign(a: Optional[float], b: Optional[float]) -> int:
    return 0 if a is None or b is None or a == b else (1 if a > b else -1)


def chart_reading(bars: List[dict]) -> dict:
    """The same indicators on any timeframe, from its closed bars (oldest first)."""
    closes = [b["c"] for b in bars]
    ema9, ema21, ema50 = (ind.last(ind.ema(closes, n)) for n in (9, 21, 50))
    _, st_dir = ind.supertrend(bars)
    macd_line, signal_line, _ = ind.macd(closes)
    atr = ind.last(ind.atr(bars, 14))
    return {"last": closes[-1], "ema9": ema9, "ema21": ema21, "ema50": ema50, "supertrend_dir": st_dir[-1] if st_dir else None,
            "macd": ind.last(macd_line), "macd_signal": ind.last(signal_line), "rsi": ind.last(ind.rsi(closes, 14)),
            "atr_pct": round(atr / closes[-1] * 100, 2) if atr else None, "as_of": bars[-1]["t"].isoformat(timespec="minutes")}


def trend_votes(chart: dict) -> Dict[str, int]:
    return {"close>ema21": _sign(chart.get("last"), chart.get("ema21")), "ema9>ema21": _sign(chart.get("ema9"), chart.get("ema21")),
            "supertrend": int(chart.get("supertrend_dir") or 0), "macd>signal": _sign(chart.get("macd"), chart.get("macd_signal"))}


def trend_of(score: int) -> str:
    return "UP" if score >= 2 else "DOWN" if score <= -2 else "SIDEWAYS"


def alignment(rows: List[dict]) -> dict:
    """Weighted UP / DOWN share over the timeframes that could be read."""
    total = sum(r["weight"] for r in rows)
    up = sum(r["weight"] for r in rows if r["trend"] == "UP")
    down = sum(r["weight"] for r in rows if r["trend"] == "DOWN")
    if not total:
        return {"label": "UNKNOWN", "up_pct": None, "down_pct": None}
    up_pct, down_pct = up / total * 100, down / total * 100
    label = ("ALIGNED UP" if up_pct >= 75 else "ALIGNED DOWN" if down_pct >= 75 else
             "LEANING UP" if up_pct - down_pct >= 25 else "LEANING DOWN" if down_pct - up_pct >= 25 else "MIXED")
    return {"label": label, "up_pct": round(up_pct), "down_pct": round(down_pct)}


class MultiTimeframeAnalyzer:
    MIN_BARS = 35            # enough for MACD(12, 26, 9) to settle

    def __init__(self, market) -> None:
        self.market = market

    def bars(self, symbol: str, frame: Timeframe, now) -> List[dict]:
        _, bars = self.market.candles(symbol, frame.interval, frame.rng)
        if barlib.interval_minutes(frame.interval):
            return barlib.closed(bars, now, frame.interval)
        daily = [b for b in bars if b["t"].date() <= now.date()]
        return self.market.fill_daily_holes(symbol, daily, now) if frame.interval == "1d" else daily

    def analyze_symbol(self, symbol: str, now, timeframes: Sequence[Timeframe] = TIMEFRAMES) -> dict:
        rows, errors, levels = [], [], {}
        for frame in timeframes:
            try:
                bars = self.bars(symbol, frame, now)
                if len(bars) < self.MIN_BARS:
                    raise DataError("only %d %s bars" % (len(bars), frame.interval))
            except IndianTraderError as exc:
                log.info("mtf %s %s unavailable: %s", symbol, frame.interval, exc)
                errors.append("%s %s: %s" % (symbol, frame.interval, exc))
                continue
            chart = chart_reading(bars)
            votes = trend_votes(chart)
            score = sum(votes.values())
            rows.append(dict(chart, interval=frame.interval, weight=frame.weight, score=score, trend=trend_of(score), votes=votes))
            if frame.interval == "1d" and len(bars) >= 2:
                last = bars[-1]
                levels = {"ema50_daily": chart["ema50"], "ema200_daily": ind.last(ind.ema([b["c"] for b in bars], 200)),
                          "next_pivots": ind.pivots(last["h"], last["l"], last["c"])}
        return {"symbol": symbol, "rows": rows, "alignment": alignment(rows), "errors": errors,
                "last": rows[0]["last"] if rows else None, "levels": levels}

    def analyze(self, now, symbols: Sequence[str] = INDICES) -> dict:
        results = {s: self.analyze_symbol(s, now) for s in symbols}
        notes = cross_index_notes(results, self._vix_change(now))
        return {"symbols": results, "notes": notes, "errors": [e for r in results.values() for e in r["errors"]]}

    def _vix_change(self, now) -> Optional[float]:
        try:
            closes = [b["c"] for b in self.bars("INDIAVIX", Timeframe("1d", "3mo", 0), now)]
            return round((closes[-1] / closes[-2] - 1) * 100, 2) if len(closes) >= 2 else None
        except IndianTraderError as exc:
            log.info("India VIX bars unavailable: %s", exc)
            return None


def cross_index_notes(results: Dict[str, dict], vix_change: Optional[float]) -> List[str]:
    notes = []
    labels = {s: r["alignment"]["label"] for s, r in results.items()}
    nifty, bank = labels.get("NIFTY", ""), labels.get("BANKNIFTY", "")
    if ("UP" in nifty and "DOWN" in bank) or ("DOWN" in nifty and "UP" in bank):
        notes.append("divergence: NIFTY is %s but BANKNIFTY is %s. Index moves are less reliable when the two disagree" % (nifty, bank))
    elif nifty and nifty == bank and nifty.startswith("ALIGNED"):
        notes.append("NIFTY and BANKNIFTY agree: both %s" % nifty)
    nifty_rows = (results.get("NIFTY") or {}).get("rows") or []
    daily = next((r for r in nifty_rows if r["interval"] == "1d"), None)
    if vix_change is not None:
        falling = daily is not None and daily["trend"] == "DOWN"
        if vix_change >= 5 and falling:
            notes.append("fear: India VIX %s today with NIFTY in a daily downtrend; expect wider swings" % pct(vix_change))
        elif vix_change <= -5:
            notes.append("calm: India VIX %s today; ranges tend to shrink" % pct(vix_change))
    return notes
