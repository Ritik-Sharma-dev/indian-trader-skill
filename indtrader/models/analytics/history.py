"""How the market actually moved over the last month (or N sessions).

From daily bars (holes filled from 5-minute data) and 5-minute bars:

* each day: OHLC, change, range, gap, where the close sits in the range and
  a day type (trend-up / trend-down: body >= 60% of the range and the close
  in the top / bottom quarter; range: body <= 30%; otherwise normal)
* summary: up / down days, average and largest moves, average range,
  streaks, net change, gap behaviour (same-day fill rate), weekday pattern,
  expiry days against other days
* intraday: the opening range (first 15 minutes), which side broke first,
  how often the break went on a further 1x range width, when the day's high
  and low were made, and volatility by hour

Everything is measured; nothing is predicted. Twenty sessions carry wide
error bars: read the percentages as tendencies.
"""

import datetime as dt
import logging
from typing import Dict, List, Optional, Tuple

from indtrader.core import clock
from indtrader.core.errors import DataError
from indtrader.models.data import bars as barlib

log = logging.getLogger(__name__)

BUCKETS: List[Tuple[str, dt.time, dt.time]] = [
    ("09:15-09:45", dt.time(9, 15), dt.time(9, 45)), ("09:45-11:00", dt.time(9, 45), dt.time(11, 0)),
    ("11:00-13:00", dt.time(11, 0), dt.time(13, 0)), ("13:00-14:30", dt.time(13, 0), dt.time(14, 30)),
    ("14:30-15:30", dt.time(14, 30), dt.time(15, 30)),
]


def day_type(open_: float, high: float, low: float, close: float) -> str:
    span = high - low
    if span <= 0:
        return "flat"
    body = abs(close - open_) / span
    location = (close - low) / span
    if body >= 0.6 and location >= 0.75:
        return "trend-up"
    if body >= 0.6 and location <= 0.25:
        return "trend-down"
    return "range" if body <= 0.3 else "normal"


def bucket_of(t: dt.time) -> str:
    return next((name for name, start, end in BUCKETS if start <= t < end), BUCKETS[-1][0])


def streaks(rows: List[dict]) -> Tuple[int, int, int]:
    """(longest up streak, longest down streak, current streak: + up / - down)."""
    best_up = best_down = current = 0
    for row in rows:
        if row["change_pct"] > 0:
            current = current + 1 if current > 0 else 1
        elif row["change_pct"] < 0:
            current = current - 1 if current < 0 else -1
        best_up, best_down = max(best_up, current), min(best_down, current)
    return best_up, -best_down, current


def _mean(values: List[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


class MarketHistory:
    def __init__(self, market, cfg) -> None:
        self.market = market
        self.cfg = cfg

    def analyse(self, symbol: str, sessions: int = 22, now: Optional[dt.datetime] = None, or_minutes: int = 15) -> dict:
        now = now or clock.now_ist()
        _, daily = self.market.candles(symbol, "1d", "6mo")
        daily = [b for b in daily if b["t"].date() <= now.date() and clock.is_trading_day(b["t"].date())]
        daily = self.market.fill_daily_holes(symbol, daily, now)
        if now.time() < clock.CLOSE:
            daily = [b for b in daily if b["t"].date() < now.date()]          # finished sessions only
        if len(daily) < sessions + 1:
            raise DataError("only %d daily bars for %s" % (len(daily), symbol))
        _, intraday = self.market.candles(symbol, "5m", "60d")
        by_day = barlib.by_session(intraday)
        window = daily[-(sessions + 1):]
        rows = [self._day(prev, bar, by_day.get(bar["t"].date()), or_minutes) for prev, bar in zip(window, window[1:])]
        log.info("history %s: %d sessions %s to %s", symbol, len(rows), rows[0]["date"], rows[-1]["date"])
        return self._summarise(symbol.upper(), rows)

    @staticmethod
    def _day(prev: dict, bar: dict, session: Optional[List[dict]], or_minutes: int) -> dict:
        day = bar["t"].date()
        o, h, l, c, prev_close = bar["o"], bar["h"], bar["l"], bar["c"], prev["c"]   # noqa: E741
        row = {"date": day.isoformat(), "weekday": day.strftime("%a"), "open": o, "high": h, "low": l, "close": c,
               "change_pct": (c / prev_close - 1) * 100, "change_pts": c - prev_close, "range_pts": h - l,
               "range_pct": (h - l) / prev_close * 100, "gap_pct": (o / prev_close - 1) * 100,
               "close_loc": (c - l) / (h - l) if h > l else 0.5, "type": day_type(o, h, l, c)}
        gap = o - prev_close
        row["gap_filled"] = (l <= prev_close) if gap > 0 else (h >= prev_close) if gap < 0 else None
        if not session or len(session) < 70 or session[0]["t"].strftime("%H:%M") != "09:15":
            return row
        n = or_minutes // 5
        or_high, or_low = max(b["h"] for b in session[:n]), min(b["l"] for b in session[:n])
        width = or_high - or_low
        first_side, trigger = None, None
        for k in range(n, len(session)):
            if session[k]["c"] > or_high:
                first_side, trigger = "up", k
                break
            if session[k]["c"] < or_low:
                first_side, trigger = "down", k
                break
        if first_side:
            rest = session[trigger + 1:]
            middle = (or_high + or_low) / 2
            if first_side == "up":
                row["or_follow_1x"] = any(b["h"] >= or_high + width for b in rest)
                row["or_back_to_mid"] = any(b["l"] <= middle for b in rest)
            else:
                row["or_follow_1x"] = any(b["l"] <= or_low - width for b in rest)
                row["or_back_to_mid"] = any(b["h"] >= middle for b in rest)
        high_bar = max(session, key=lambda b: b["h"])
        low_bar = min(session, key=lambda b: b["l"])
        hour_ranges: Dict[str, List[float]] = {}
        for b in session:
            hour_ranges.setdefault(b["t"].strftime("%H"), []).append(b["h"] - b["l"])
        row.update({"or_width": width, "or_width_pct": width / prev_close * 100, "or_first": first_side or "none",
                    "high_time": high_bar["t"].strftime("%H:%M"), "low_time": low_bar["t"].strftime("%H:%M"),
                    "hour_ranges": hour_ranges})
        return row

    def _summarise(self, symbol: str, rows: List[dict]) -> dict:
        ups = [r for r in rows if r["change_pct"] > 0]
        downs = [r for r in rows if r["change_pct"] < 0]
        gaps = [r for r in rows if abs(r["gap_pct"]) >= 0.2]
        up_streak, down_streak, current = streaks(rows)
        types: Dict[str, int] = {}
        weekdays: Dict[str, List[float]] = {}
        for r in rows:
            types[r["type"]] = types.get(r["type"], 0) + 1
            weekdays.setdefault(r["weekday"], []).append(r["change_pct"])
        intraday = [r for r in rows if "or_width" in r]
        high_buckets: Dict[str, int] = {}
        low_buckets: Dict[str, int] = {}
        hours: Dict[str, List[float]] = {}
        for r in intraday:
            hb, lb = bucket_of(clock.parse_hhmm(r["high_time"])), bucket_of(clock.parse_hhmm(r["low_time"]))
            high_buckets[hb] = high_buckets.get(hb, 0) + 1
            low_buckets[lb] = low_buckets.get(lb, 0) + 1
            for hour, ranges in r["hour_ranges"].items():
                hours.setdefault(hour, []).extend(ranges)
        broke = [r for r in intraday if r["or_first"] != "none"]
        first_close = rows[0]["close"] - rows[0]["change_pts"]
        peak, drawdown = first_close, 0.0
        for r in rows:
            peak = max(peak, r["close"])
            drawdown = min(drawdown, (r["close"] / peak - 1) * 100)
        expiry_dates = {r["date"] for r in rows
                        if clock.weekly_expiry("NIFTY", dt.date.fromisoformat(r["date"]), self.cfg) == dt.date.fromisoformat(r["date"])}
        expiry_rows = [r for r in rows if r["date"] in expiry_dates]
        other_rows = [r for r in rows if r["date"] not in expiry_dates]
        rate = lambda flag, subset: _mean([1.0 if r.get(flag) else 0.0 for r in subset]) if subset else None  # noqa: E731
        return {
            "symbol": symbol, "sessions": len(rows), "from": rows[0]["date"], "to": rows[-1]["date"],
            "net_change_pct": (rows[-1]["close"] / first_close - 1) * 100, "net_change_pts": rows[-1]["close"] - first_close,
            "max_drawdown_pct": drawdown, "up_days": len(ups), "down_days": len(downs),
            "avg_up_pct": _mean([r["change_pct"] for r in ups]), "avg_down_pct": _mean([r["change_pct"] for r in downs]),
            "best_day": max(rows, key=lambda r: r["change_pct"]), "worst_day": min(rows, key=lambda r: r["change_pct"]),
            "avg_range_pts": _mean([r["range_pts"] for r in rows]), "avg_range_pct": _mean([r["range_pct"] for r in rows]),
            "max_range_pts": max(r["range_pts"] for r in rows),
            "longest_up_streak": up_streak, "longest_down_streak": down_streak, "current_streak": current,
            "day_types": types, "gap_days": len(gaps),
            "gap_up": sum(1 for r in gaps if r["gap_pct"] > 0), "gap_down": sum(1 for r in gaps if r["gap_pct"] < 0),
            "gap_fill_rate": rate("gap_filled", gaps), "avg_abs_gap_pct": _mean([abs(r["gap_pct"]) for r in rows]),
            "weekday_avg_change": {k: round(_mean(v), 3) for k, v in weekdays.items()},
            "expiry_days": len(expiry_rows), "expiry_avg_range_pct": _mean([r["range_pct"] for r in expiry_rows]),
            "other_avg_range_pct": _mean([r["range_pct"] for r in other_rows]),
            "or_sessions": len(intraday), "or_avg_width_pts": _mean([r["or_width"] for r in intraday]),
            "or_avg_width_pct": _mean([r["or_width_pct"] for r in intraday]),
            "or_broke_up_first": sum(1 for r in intraday if r["or_first"] == "up"),
            "or_broke_down_first": sum(1 for r in intraday if r["or_first"] == "down"),
            "or_no_break": sum(1 for r in intraday if r["or_first"] == "none"),
            "or_follow_1x_rate": rate("or_follow_1x", broke), "or_back_to_mid_rate": rate("or_back_to_mid", broke),
            "high_time_buckets": high_buckets, "low_time_buckets": low_buckets,
            "hour_avg_bar_range": {h: round(_mean(v), 2) for h, v in sorted(hours.items())},
            "days": [{k: v for k, v in r.items() if k != "hour_ranges"} for r in rows],
        }
