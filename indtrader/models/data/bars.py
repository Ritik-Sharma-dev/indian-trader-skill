"""OHLCV bars and helpers that work on lists of them.

A bar is a plain dict ``{t, o, h, l, c, v}``: ``t`` is the bar's START time
in IST. Dicts (rather than objects) keep the indicator code simple and the
bars directly JSON-serialisable.
"""

import datetime as dt
from typing import Dict, List, Optional

from indtrader.core import clock

try:                               # Python 3.8+
    from typing import TypedDict
except ImportError:                # pragma: no cover
    TypedDict = dict               # type: ignore


class Bar(TypedDict):
    t: dt.datetime
    o: float
    h: float
    l: float     # noqa: E741  (OHLC naming)
    c: float
    v: int


Sessions = Dict[dt.date, List[dict]]


def interval_minutes(interval: str) -> Optional[int]:
    """'5m' -> 5, '1h' -> 60, daily or longer -> None."""
    if interval.endswith("m"):
        return int(interval[:-1])
    if interval.endswith("h"):
        return int(interval[:-1]) * 60
    return None


def closed(bars: List[dict], now: dt.datetime, interval: str) -> List[dict]:
    """Only the bars that have finished by ``now``."""
    minutes = interval_minutes(interval)
    if not minutes:
        return [b for b in bars if b["t"].date() < now.date() or now.time() >= clock.CLOSE]
    step = dt.timedelta(minutes=minutes)
    return [b for b in bars if b["t"] + step <= now]


def by_session(bars: List[dict]) -> Sessions:
    out: Sessions = {}
    for bar in bars:
        out.setdefault(bar["t"].date(), []).append(bar)
    return out


def aggregate(session: List[dict]) -> dict:
    """One daily bar from a session's intraday bars."""
    return {"t": session[0]["t"].replace(hour=0, minute=0), "o": session[0]["o"],
            "h": max(b["h"] for b in session), "l": min(b["l"] for b in session),
            "c": session[-1]["c"], "v": sum(b["v"] for b in session), "filled": True}


def mark_closing_auction(bars: List[dict]) -> int:
    """Flag the closing-auction bars (``auction: True``); returns how many were flagged."""
    flagged = 0
    for bar in bars:
        moment = bar["t"]
        if moment.time() >= clock.FO_CONTINUOUS_END and clock.has_closing_auction(moment.date()):
            bar["auction"] = True
            flagged += 1
    return flagged


def continuous(bars: List[dict]) -> List[dict]:
    return [b for b in bars if not b.get("auction")]


def trim_wicks(bars: List[dict], k: float = 8.0, floor_pct: float = 0.3) -> int:
    """Cut back fake auction wicks; returns how many were trimmed.

    Yahoo's SENSEX bars carry fake wicks at the BSE opening and closing
    auctions (a 15:20 "high" 1.5% above every real trade). A wick longer
    than ``k`` x the session's median bar range AND more than ``floor_pct``
    of the price is cut back to the bar's body. Real moves (big bodies) are
    kept.
    """
    trimmed = 0
    for day_bars in by_session(bars).values():
        ranges = sorted(b["h"] - b["l"] for b in day_bars)
        median = ranges[len(ranges) // 2] if ranges else 0
        if median <= 0:
            continue
        for bar in day_bars:
            top, bottom = max(bar["o"], bar["c"]), min(bar["o"], bar["c"])
            limit = max(k * median, top * floor_pct / 100)
            if bar["h"] - top > limit:
                bar["h"] = top
                trimmed += 1
            if bottom - bar["l"] > limit:
                bar["l"] = bottom
                trimmed += 1
    return trimmed
