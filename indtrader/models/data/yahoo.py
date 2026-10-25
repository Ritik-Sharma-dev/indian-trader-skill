"""Yahoo Finance: candles, multi-symbol closes and quotes (free, unofficial).

NSE stocks are ``SYMBOL.NS``, BSE stocks ``SYMBOL.BO``; indices have their
own codes (:data:`indtrader.models.data.symbols.INDEX_YAHOO`). Index candles carry
no volume. Intraday history: 1-minute bars for about 7 days, 5-minute bars
for 60 days.
"""

import logging
import time
import urllib.parse
from typing import Any, Dict, Iterable, List, Optional, Tuple

from indtrader.core import clock
from indtrader.core.errors import DataError, IndianTraderError, NetworkError
from indtrader.core.http import HttpClient
from indtrader.models.data import bars as barlib
from indtrader.models.data.symbols import safe_name, yahoo_symbol

log = logging.getLogger(__name__)

HOSTS = ("https://query2.finance.yahoo.com", "https://query1.finance.yahoo.com")


def parse_chart(payload: Any, interval: str) -> Tuple[dict, List[dict]]:
    """Yahoo chart JSON -> (meta, bars).

    Intraday bars are kept only on the interval grid and inside 09:15-15:30
    (Yahoo adds a last "tick" bar at 15:30 and live seconds-stamped bars;
    both are dropped). Prices are rounded to the paisa: Yahoo sends float32
    noise such as 1191.300048828125.
    """
    try:
        result = payload["chart"]["result"][0]
    except (KeyError, IndexError, TypeError) as exc:
        error = (payload.get("chart") or {}).get("error") if isinstance(payload, dict) else None
        raise DataError("Yahoo sent no chart (%s)" % (error or "empty")) from exc
    meta = result.get("meta", {})
    stamps = result.get("timestamp") or []
    quote = (result.get("indicators", {}).get("quote") or [{}])[0]
    minutes = barlib.interval_minutes(interval)
    blank = [None] * len(stamps)
    opens, highs, lows, closes = (quote.get(k) or blank for k in ("open", "high", "low", "close"))
    volumes = quote.get("volume") or [0] * len(stamps)
    out: Dict[Any, dict] = {}
    for i, stamp in enumerate(stamps):
        o, h, l, c = opens[i], highs[i], lows[i], closes[i]   # noqa: E741
        if None in (o, h, l, c):
            continue
        when = clock.to_ist(stamp)
        if minutes:
            from_open = when.hour * 3600 + when.minute * 60 - (9 * 3600 + 15 * 60)
            if when.second or from_open % (minutes * 60) or not (clock.OPEN <= when.time() < clock.CLOSE):
                continue
        else:
            when = when.replace(hour=0, minute=0, second=0)
        out[when] = {"t": when, "o": round(o, 2), "h": round(h, 2), "l": round(l, 2), "c": round(c, 2),
                     "v": int(volumes[i] or 0)}          # a repeated bar: the last copy wins
    bars = [out[k] for k in sorted(out)]
    if minutes and bars and not any(b["v"] for b in bars):
        # indices only (no volume): fake auction wicks are an index-data artefact;
        # a stock's long wick on news is real and is kept
        meta["wicks_trimmed"] = barlib.trim_wicks(bars)
        if meta["wicks_trimmed"]:
            log.info("trimmed %d fake wicks in %s %s bars", meta["wicks_trimmed"], meta.get("symbol"), interval)
    return meta, bars


def quote_from_meta(meta: dict) -> dict:
    price = meta.get("regularMarketPrice")
    prev = meta.get("previousClose") or meta.get("chartPreviousClose")
    change = (price - prev) if (price is not None and prev) else None
    return {
        "price": price, "prev_close": prev, "change": change,
        "change_pct": (change / prev * 100) if change is not None else None,
        "day_high": meta.get("regularMarketDayHigh"), "day_low": meta.get("regularMarketDayLow"),
        "time": clock.to_ist(meta["regularMarketTime"]).isoformat(timespec="minutes") if meta.get("regularMarketTime") else None,
        "name": meta.get("shortName") or meta.get("longName"),
        "year_high": meta.get("fiftyTwoWeekHigh"), "year_low": meta.get("fiftyTwoWeekLow"),
    }


class YahooClient:
    def __init__(self, http: HttpClient) -> None:
        self.http = http

    def _get(self, path: str, name: str, ttl: float = 0) -> Any:
        error: Optional[IndianTraderError] = None
        for host in HOSTS:
            try:
                return self.http.json(host + path, name=name, ttl=ttl)
            except IndianTraderError as exc:
                error = exc
                if self.http.offline:
                    break
                log.info("Yahoo %s failed on %s, trying the next host", path.split("?")[0], host)
        assert error is not None
        raise error

    def candles(self, symbol: str, interval: str = "5m", rng: str = "5d") -> Tuple[dict, List[dict]]:
        code = yahoo_symbol(symbol)
        path = "/v8/finance/chart/%s?range=%s&interval=%s&includePrePost=false" % (urllib.parse.quote(code), rng, interval)
        try:
            payload = self._get(path, "yahoo-%s-%s-%s.json" % (safe_name(symbol), rng, interval))
        except NetworkError as exc:
            if "HTTP 404" in str(exc):
                raise DataError("Yahoo has no data for %s (%s): check the symbol" % (symbol.upper(), code)) from exc
            raise
        return parse_chart(payload, interval)

    def spark(self, symbols: Iterable[str], rng: str = "3mo", interval: str = "1d", chunk: int = 20,
              name_prefix: str = "spark", raw: bool = False) -> Dict[str, dict]:
        """Closes for many symbols, 20 per request: ``{symbol: {times, closes, meta}}``.

        ``raw=True`` sends the symbols as given (US tickers, crypto, futures).
        A failed chunk is skipped live and raises offline.
        """
        out: Dict[str, dict] = {}
        symbols = list(symbols)
        for start in range(0, len(symbols), chunk):
            part = symbols[start:start + chunk]
            codes = {(s if raw else yahoo_symbol(s)): s for s in part}
            path = "/v7/finance/spark?symbols=%s&range=%s&interval=%s" % (urllib.parse.quote(",".join(codes)), rng, interval)
            name = "%s-%s-%s-%d.json" % (name_prefix, rng, interval, start // chunk)
            try:
                payload = self._get(path, name)
            except IndianTraderError as exc:
                if self.http.offline:
                    raise
                log.warning("spark chunk %d skipped: %s", start // chunk, exc)
                continue
            for item in (payload.get("spark") or {}).get("result") or []:
                response = (item.get("response") or [{}])[0]
                symbol = codes.get(item.get("symbol"), item.get("symbol"))
                stamps = response.get("timestamp") or []
                closes = ((response.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
                pairs = [(t, c) for t, c in zip(stamps, closes) if c is not None]
                out[symbol] = {"times": [clock.to_ist(t) for t, _ in pairs], "closes": [float(c) for _, c in pairs],
                               "meta": response.get("meta", {})}
            if not self.http.offline and start + chunk < len(symbols):
                time.sleep(0.3)
        return out

    def raw_quotes(self, symbols: Iterable[str]) -> Dict[str, dict]:
        """Last price vs the previous session's close for any Yahoo code.

        One chart request per symbol: Yahoo's multi-symbol daily feed has
        holes (22 Oct 2026: no 21 Oct bar for the S&P 500, VIX, Nikkei,
        Kospi, the ADRs), which turned one-day changes into two-day changes.
        The single-symbol chart's ``chartPreviousClose`` is the real previous close.
        """
        out: Dict[str, dict] = {}
        for symbol in symbols:
            path = "/v8/finance/chart/%s?range=1d&interval=1d" % urllib.parse.quote(symbol)
            try:
                meta = self._get(path, "yahoo-raw-%s.json" % safe_name(symbol))["chart"]["result"][0]["meta"]
            except (IndianTraderError, KeyError, IndexError, TypeError) as exc:
                log.warning("no quote for %s: %s", symbol, exc)
                continue
            last = meta.get("regularMarketPrice")
            prev = meta.get("chartPreviousClose") or meta.get("previousClose")
            out[symbol] = {"last": last, "prev": prev,
                           "change_pct": (last / prev - 1) * 100 if last is not None and prev else None,
                           "time": clock.to_ist(meta["regularMarketTime"]) if meta.get("regularMarketTime") else None}
            if not self.http.offline:
                time.sleep(0.15)
        return out
