"""Technical indicators on lists of bars (``{t, o, h, l, c, v}``) or closes.

Every series function returns a list as long as its input, with ``None``
where there is not yet enough data. Textbook definitions:

* EMA: seeded with the SMA of the first ``n`` values
* RSI, ATR: Wilder's smoothing
* VWAP: per session, typical price (H+L+C)/3 weighted by volume; index
  candles have no volume, so it falls back to equal weights (TWAP)
* SuperTrend: ATR(10) x 3 bands around (H+L)/2
* Pivots: classic floor pivots and the Central Pivot Range (CPR)
"""

import datetime as dt
from typing import List, Optional, Sequence, Tuple

Series = List[Optional[float]]


def sma(values: Sequence[float], n: int) -> Series:
    out: Series = []
    total = 0.0
    for i, value in enumerate(values):
        total += value
        if i >= n:
            total -= values[i - n]
        out.append(total / n if i >= n - 1 else None)
    return out


def ema(values: Sequence[float], n: int) -> Series:
    out: Series = [None] * len(values)
    if len(values) < n:
        return out
    k = 2.0 / (n + 1)
    current = sum(values[:n]) / n
    out[n - 1] = current
    for i in range(n, len(values)):
        current = values[i] * k + current * (1 - k)
        out[i] = current
    return out


def rsi(closes: Sequence[float], n: int = 14) -> Series:
    out: Series = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = losses = 0.0
    for i in range(1, n + 1):
        change = closes[i] - closes[i - 1]
        gains += max(change, 0)
        losses += max(-change, 0)
    avg_gain, avg_loss = gains / n, losses / n

    def value(g: float, l: float) -> float:   # noqa: E741
        if l == 0:
            return 100.0 if g > 0 else 50.0
        return 100 - 100 / (1 + g / l)

    out[n] = value(avg_gain, avg_loss)
    for i in range(n + 1, len(closes)):
        change = closes[i] - closes[i - 1]
        avg_gain = (avg_gain * (n - 1) + max(change, 0)) / n
        avg_loss = (avg_loss * (n - 1) + max(-change, 0)) / n
        out[i] = value(avg_gain, avg_loss)
    return out


def true_range(bars: Sequence[dict]) -> List[float]:
    out = []
    for i, bar in enumerate(bars):
        if i == 0:
            out.append(bar["h"] - bar["l"])
        else:
            prev_close = bars[i - 1]["c"]
            out.append(max(bar["h"] - bar["l"], abs(bar["h"] - prev_close), abs(bar["l"] - prev_close)))
    return out


def atr(bars: Sequence[dict], n: int = 14) -> Series:
    ranges = true_range(bars)
    out: Series = [None] * len(bars)
    if len(bars) < n:
        return out
    current = sum(ranges[:n]) / n
    out[n - 1] = current
    for i in range(n, len(bars)):
        current = (current * (n - 1) + ranges[i]) / n
        out[i] = current
    return out


def vwap(bars: Sequence[dict]) -> Tuple[List[float], bool]:
    """Per-session VWAP; returns (values, weighted_by_volume)."""
    out: List[float] = []
    has_volume = any(b["v"] for b in bars)
    day: Optional[dt.date] = None
    price_volume = volume = 0.0
    for bar in bars:
        if bar["t"].date() != day:
            day, price_volume, volume = bar["t"].date(), 0.0, 0.0
        typical = (bar["h"] + bar["l"] + bar["c"]) / 3
        weight = bar["v"] if has_volume else 1.0
        price_volume += typical * weight
        volume += weight
        out.append(price_volume / volume if volume else typical)
    return out, has_volume


def supertrend(bars: Sequence[dict], n: int = 10, mult: float = 3.0) -> Tuple[Series, List[Optional[int]]]:
    """Returns (line, direction) with direction +1 (up) or -1 (down)."""
    ranges = atr(bars, n)
    line: Series = [None] * len(bars)
    direction: List[Optional[int]] = [None] * len(bars)
    final_upper = final_lower = None
    trend = 1
    for i, bar in enumerate(bars):
        if ranges[i] is None:
            continue
        middle = (bar["h"] + bar["l"]) / 2
        basic_upper, basic_lower = middle + mult * ranges[i], middle - mult * ranges[i]
        prev_close = bars[i - 1]["c"] if i else bar["c"]
        if final_upper is None or basic_upper < final_upper or prev_close > final_upper:
            final_upper = basic_upper
        if final_lower is None or basic_lower > final_lower or prev_close < final_lower:
            final_lower = basic_lower
        if i == 0 or line[i - 1] is None:
            trend = 1 if bar["c"] >= middle else -1
        elif trend == 1 and bar["c"] < final_lower:
            trend = -1
        elif trend == -1 and bar["c"] > final_upper:
            trend = 1
        line[i] = final_lower if trend == 1 else final_upper
        direction[i] = trend
    return line, direction


def macd(closes: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[Series, Series, Series]:
    fast_ema, slow_ema = ema(closes, fast), ema(closes, slow)
    line = [(f - s) if (f is not None and s is not None) else None for f, s in zip(fast_ema, slow_ema)]
    first = next((i for i, v in enumerate(line) if v is not None), None)
    signal_line: Series = [None] * len(closes)
    if first is not None:
        signal_line[first:] = ema([v for v in line[first:]], signal)
    histogram = [(a - b) if (a is not None and b is not None) else None for a, b in zip(line, signal_line)]
    return line, signal_line, histogram


def bollinger(closes: Sequence[float], n: int = 20, k: float = 2.0) -> Tuple[Series, Series, Series]:
    middle = sma(closes, n)
    upper: Series = []
    lower: Series = []
    for i, mid in enumerate(middle):
        if mid is None:
            upper.append(None)
            lower.append(None)
            continue
        window = closes[i - n + 1:i + 1]
        deviation = (sum((x - mid) ** 2 for x in window) / n) ** 0.5
        upper.append(mid + k * deviation)
        lower.append(mid - k * deviation)
    return upper, middle, lower


def pivots(high: float, low: float, close: float) -> dict:
    """Classic floor pivots and the CPR from a session's high, low and close."""
    pivot = (high + low + close) / 3
    bottom = (high + low) / 2
    top = 2 * pivot - bottom
    if top < bottom:
        top, bottom = bottom, top
    return {
        "P": pivot, "TC": top, "BC": bottom,
        "R1": 2 * pivot - low, "S1": 2 * pivot - high,
        "R2": pivot + (high - low), "S2": pivot - (high - low),
        "R3": high + 2 * (pivot - low), "S3": low - 2 * (high - pivot),
        "cpr_width_pct": (top - bottom) / pivot * 100 if pivot else None,
    }


def opening_range(session_bars: Sequence[dict], minutes: int, interval_min: int) -> Optional[Tuple[float, float, int]]:
    """(high, low, bars_used) of the first ``minutes``, or ``None``.

    The bars must be the real first bars of the session (09:15, 09:20, ...):
    if the data source skipped one, there is no valid range.
    """
    count = max(1, minutes // interval_min)
    if len(session_bars) < count:
        return None
    first = session_bars[:count]
    start = first[0]["t"]
    if (start.hour, start.minute) != (9, 15):
        return None
    for i, bar in enumerate(first):
        if bar["t"] != start + dt.timedelta(minutes=interval_min * i):
            return None
    return max(b["h"] for b in first), min(b["l"] for b in first), count


def swing_levels(bars: Sequence[dict], left: int = 3, right: int = 3, tolerance_pct: float = 0.3,
                 top: int = 4) -> List[Tuple[float, int, str]]:
    """Support / resistance from swing highs and lows, clustered within
    ``tolerance_pct``; returns ``[(level, touches, kind)]``, strongest first."""
    points = []
    for i in range(left, len(bars) - right):
        high, low = bars[i]["h"], bars[i]["l"]
        window = range(i - left, i + right + 1)
        if all(high >= bars[j]["h"] for j in window):
            points.append((high, "R"))
        if all(low <= bars[j]["l"] for j in window):
            points.append((low, "S"))
    points.sort()
    clusters: List[dict] = []
    for price, kind in points:
        if clusters and abs(price - clusters[-1]["sum"] / clusters[-1]["n"]) / price * 100 <= tolerance_pct:
            cluster = clusters[-1]
            cluster["sum"] += price
            cluster["n"] += 1
            cluster["kinds"].add(kind)
        else:
            clusters.append({"sum": price, "n": 1, "kinds": {kind}})
    levels = [(c["sum"] / c["n"], c["n"], "/".join(sorted(c["kinds"]))) for c in clusters]
    levels.sort(key=lambda x: -x[1])
    return levels[:top]


def last(values: Sequence[Optional[float]]) -> Optional[float]:
    """The last non-None value."""
    for value in reversed(values):
        if value is not None:
            return value
    return None
