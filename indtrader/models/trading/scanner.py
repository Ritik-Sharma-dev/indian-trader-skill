"""Chart scanner: finds setups across many NSE stocks.

* universe: ``fo`` (F&O stocks, about 200 liquid names), ``nifty50`` ...
  ``nifty500``, or a file of symbols
* daily (before the open, from 3 months of daily closes):
  breakout_20d / breakdown_20d (last close beyond every close of the 20
  before), bull_flag / bear_flag (more than 8% over 10 sessions, then five
  closes inside a 4% band), reclaim_ma20 / lose_ma20, oversold (RSI under
  30), overbought (RSI over 70), big_move (more than 4% in a day)
* orb (after 09:30): the first COMPLETED 5-minute bar that closes beyond the
  opening range (long = CE, short = PE), optionally with volume above the
  range bars' average

Results go to ``workspace/watchlist.json`` for news, entry and the brief.
"""

import concurrent.futures as cf
import datetime as dt
import logging
from typing import Dict, List, Optional, Sequence, Tuple

from indtrader.core import settings
from indtrader.core.errors import IndianTraderError, ValidationError
from indtrader.core.storage import write_json
from indtrader.models.analytics import indicators as ind
from indtrader.models.data import bars as barlib
from indtrader.models.data.nse import INDEX_LISTS

log = logging.getLogger(__name__)

BULLISH = frozenset({"breakout_20d", "bull_flag", "reclaim_ma20", "oversold"})
BEARISH = frozenset({"breakdown_20d", "bear_flag", "lose_ma20", "overbought"})
_SETUP_ORDER = {"breakout_20d": 0, "breakdown_20d": 0, "bull_flag": 1, "bear_flag": 1}


def find_setups(closes: Sequence[float]) -> List[str]:
    found: List[str] = []
    if len(closes) < 22:
        return found
    last, prior = closes[-1], closes[-21:-1]
    if last > max(prior):
        found.append("breakout_20d")
    if last < min(prior):
        found.append("breakdown_20d")
    if len(closes) >= 16:
        run = closes[-6] / closes[-16] - 1
        flag = closes[-5:]
        band = (max(flag) - min(flag)) / min(flag)
        if run > 0.08 and band < 0.04:
            found.append("bull_flag")
        if run < -0.08 and band < 0.04:
            found.append("bear_flag")
    average = ind.sma(closes, 20)
    if average[-2] is not None:
        if closes[-2] < average[-2] and last > average[-1]:
            found.append("reclaim_ma20")
        if closes[-2] > average[-2] and last < average[-1]:
            found.append("lose_ma20")
    strength = ind.rsi(closes, 14)[-1]
    if strength is not None and strength < 30:
        found.append("oversold")
    if strength is not None and strength > 70:
        found.append("overbought")
    if abs(last / closes[-2] - 1) > 0.04:
        found.append("big_move")
    return found


def orb_eval(session: Sequence[dict], or_minutes: int = 15, min_vol_x: float = 0.0, interval_min: int = 5) -> Optional[dict]:
    """The first opening-range break in one session of closed bars."""
    opening = ind.opening_range(session, or_minutes, interval_min)
    if not opening:
        return None
    high, low, count = opening
    average_volume = sum(b["v"] for b in session[:count]) / count
    width_pct = round((high - low) / low * 100, 2)
    for bar in session[count:]:
        side = "long" if bar["c"] > high else "short" if bar["c"] < low else None
        if not side or (min_vol_x and average_volume and bar["v"] < min_vol_x * average_volume):
            continue
        edge = high if side == "long" else low
        return {"side": side, "or_high": high, "or_low": low,
                "trigger_time": (bar["t"] + dt.timedelta(minutes=interval_min)).strftime("%H:%M"),
                "trigger_price": bar["c"], "beyond_pct": round((bar["c"] / edge - 1) * 100, 2),
                "vol_x": round(bar["v"] / average_volume, 2) if average_volume else None,
                "last": session[-1]["c"], "or_width_pct": width_pct}
    return {"side": None, "or_high": high, "or_low": low, "last": session[-1]["c"], "or_width_pct": width_pct}


class Scanner:
    def __init__(self, market) -> None:
        self.market = market

    def universe(self, name: Optional[str]) -> List[str]:
        name = (name or "fo").lower()
        if name == "fo":
            return self.market.fo_stocks()
        if name in INDEX_LISTS:
            return [r["symbol"] for r in self.market.index_members(name)]
        try:
            with open(name, encoding="utf-8") as fh:
                return [line.strip().upper() for line in fh if line.strip() and not line.startswith("#")]
        except OSError as exc:
            raise ValidationError("unknown universe %r (fo, nifty50, nifty100, nifty200, nifty500 or a file)" % name) from exc

    def daily(self, symbols: List[str], min_price: float = 50, min_volume: float = 200000) -> Tuple[List[dict], int]:
        closes_by_symbol = self.market.spark(symbols, rng="3mo", interval="1d")
        hits, skipped = [], 0
        for symbol in symbols:
            series = closes_by_symbol.get(symbol)
            if not series or len(series["closes"]) < 22:
                skipped += 1
                continue
            meta = series["meta"]
            price = meta.get("regularMarketPrice") or series["closes"][-1]
            volume = meta.get("regularMarketVolume") or 0
            if price < min_price or (volume and volume < min_volume):
                continue
            setups = find_setups(series["closes"])
            if not setups:
                continue
            strength = ind.rsi(series["closes"], 14)[-1]
            lean = len(BULLISH & set(setups)) - len(BEARISH & set(setups))
            hits.append({"symbol": symbol, "price": round(price, 2), "setups": setups,
                         "date": series["times"][-1].date().isoformat() if series.get("times") else None,
                         "change_pct": round((series["closes"][-1] / series["closes"][-2] - 1) * 100, 2),
                         "rsi": round(strength, 1) if strength else None,
                         "lean": "long" if lean > 0 else "short" if lean < 0 else "either"})
        hits.sort(key=lambda h: (min(_SETUP_ORDER.get(s, 5) for s in h["setups"]), -abs(h["change_pct"])))
        log.info("daily scan: %d hits of %d symbols (%d skipped)", len(hits), len(symbols), skipped)
        return hits, skipped

    def opening_range(self, symbols: List[str], now: dt.datetime, day: dt.date, or_minutes: int = 15,
                      min_vol_x: float = 0.0, workers: int = 4) -> Tuple[List[dict], int, int]:
        if (now.date() - day).days > 55:
            raise ValidationError("5-minute history only reaches back about 60 days")
        rng = "1d" if day == now.date() else "60d"

        def evaluate(symbol: str):
            try:
                _, bars = self.market.candles(symbol, "5m", rng)
            except IndianTraderError as exc:
                log.warning("ORB scan: no bars for %s (%s)", symbol, exc)
                return symbol, None
            session = [b for b in barlib.closed(bars, now, "5m") if b["t"].date() == day]
            return symbol, orb_eval(session, or_minutes, min_vol_x)

        results: Dict[str, Optional[dict]] = {}
        if self.market.offline or workers <= 1:
            results.update(evaluate(s) for s in symbols)
        else:
            with cf.ThreadPoolExecutor(max_workers=workers) as pool:
                results.update(pool.map(evaluate, symbols))
        hits = [dict(result, symbol=symbol) for symbol, result in results.items() if result and result.get("side")]
        hits.sort(key=lambda h: (h["trigger_time"], -abs(h["beyond_pct"])))
        missing = sum(1 for result in results.values() if result is None)
        log.info("ORB scan %s: %d breaks of %d symbols (%d without data)", day, len(hits), len(results), missing)
        return hits, len(results), missing


def write_watchlist(kind: str, hits: List[dict], now: dt.datetime, extra: Optional[dict] = None) -> str:
    path = settings.path("watchlist.json")
    document = {"scan": kind, "time": now.isoformat(timespec="minutes"), "hits": hits}
    document.update(extra or {})
    write_json(path, document)
    return path
