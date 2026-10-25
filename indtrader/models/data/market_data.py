"""MarketData: the one object the rest of the code asks for market data.

It combines the three sources with the rules learnt from cross-checking
them against the exchanges (22 Oct 2026):

* index quotes come from the exchange first (NSE allIndices; BSE for
  SENSEX), Yahoo is the fallback and the source for stocks;
* Yahoo's own previous close can skip a session, so for Indian symbols the
  previous close is taken from the previous NSE trading day's bars;
* Yahoo's daily index bars can skip a trading day; :meth:`fill_daily_holes`
  rebuilds those days from 5-minute bars;
* lot sizes come from NSE's file once a day; never from memory.
"""

import csv
import datetime as dt
import io
import logging
from typing import Dict, Iterable, List, Optional, Tuple

from indtrader.core import clock, settings
from indtrader.core.errors import IndianTraderError, ValidationError
from indtrader.core.http import HttpClient
from indtrader.core.storage import read_json, write_json
from indtrader.models.data import bars as barlib
from indtrader.models.data.bse import BseClient
from indtrader.models.data.nse import NseClient, parse_lots
from indtrader.models.data.symbols import BSE_INDICES, NSE_INDEX_NAMES, NSE_INDICES, is_indian, yahoo_symbol
from indtrader.models.data.yahoo import YahooClient, quote_from_meta

log = logging.getLogger(__name__)


def _number(value) -> Optional[float]:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


class MarketData:
    def __init__(self, http: HttpClient, cfg: Optional[settings.Settings] = None) -> None:
        self.http = http
        self.cfg = cfg if cfg is not None else settings.load()
        self.yahoo = YahooClient(http)
        self.nse = NseClient(http)
        self.bse = BseClient(http)

    @property
    def offline(self) -> bool:
        return bool(self.http.offline)

    # -- candles ---------------------------------------------------------------------

    def candles(self, symbol: str, interval: str = "5m", rng: str = "5d") -> Tuple[dict, List[dict]]:
        return self.yahoo.candles(symbol, interval, rng)

    def spark(self, symbols: Iterable[str], **kwargs) -> Dict[str, dict]:
        return self.yahoo.spark(symbols, **kwargs)

    def raw_quotes(self, symbols: Iterable[str]) -> Dict[str, dict]:
        return self.yahoo.raw_quotes(symbols)

    def fill_daily_holes(self, symbol: str, daily: List[dict], now: dt.datetime) -> List[dict]:
        """Add NSE trading days missing from Yahoo's daily bars (last ~55 days)."""
        if not daily:
            return daily
        have = {b["t"].date() for b in daily}
        cursor = max(daily[0]["t"].date(), now.date() - dt.timedelta(days=55))
        missing = []
        while cursor <= now.date():
            if clock.is_trading_day(cursor) and cursor not in have:
                missing.append(cursor)
            cursor += dt.timedelta(days=1)
        if not missing:
            return daily
        try:
            _, intraday = self.candles(symbol, "5m", "60d")
        except IndianTraderError as exc:
            log.warning("cannot fill %d missing daily bars for %s: %s", len(missing), symbol, exc)
            return daily
        sessions = barlib.by_session(intraday)
        added = [barlib.aggregate(sessions[d]) for d in missing if len(sessions.get(d, [])) >= 70]
        if added:
            log.info("rebuilt %d missing daily bars for %s from 5-minute data", len(added), symbol)
        return sorted(daily + added, key=lambda b: b["t"])

    # -- quotes --------------------------------------------------------------------------

    def official_index_quote(self, symbol: str) -> Optional[dict]:
        """NSE indices from NSE's allIndices, SENSEX from BSE; ``None`` when unavailable."""
        upper = symbol.upper()
        try:
            if upper in NSE_INDEX_NAMES:
                payload = self.nse.all_indices(ttl=20)
                record = next((r for r in payload.get("data") or [] if r.get("index") == NSE_INDEX_NAMES[upper]), None)
                if not record:
                    return None
                last, prev = _number(record.get("last")), _number(record.get("previousClose"))
                source, when = "NSE", payload.get("timestamp")
                high, low, open_ = _number(record.get("high")), _number(record.get("low")), _number(record.get("open"))
            elif upper == "SENSEX":
                record = self.bse.sensex()
                if not record:
                    return None
                last, prev = _number(record.get("ltp")), _number(record.get("Prev_Close"))
                source, when = "BSE", record.get("dttm")
                high, low, open_ = _number(record.get("High")), _number(record.get("Low")), _number(record.get("I_open"))
            else:
                return None
        except (IndianTraderError, ValueError, AttributeError) as exc:
            log.info("official quote for %s unavailable (%s); falling back to Yahoo", upper, exc)
            return None
        if not last or not prev:
            return None
        return {"symbol": upper, "price": last, "prev_close": prev, "change": last - prev,
                "change_pct": (last - prev) / prev * 100, "day_high": high, "day_low": low, "day_open": open_,
                "time": when, "source": source, "name": NSE_INDEX_NAMES.get(upper, upper)}

    def quote(self, symbol: str) -> dict:
        """Last price and change against the previous session's close."""
        official = self.official_index_quote(symbol)
        if official:
            return official
        meta, daily = self.candles(symbol, "1d", "5d")
        quote = quote_from_meta(meta)
        quote.update(symbol=symbol.upper(), source="Yahoo")
        if not meta.get("regularMarketTime") or not is_indian(yahoo_symbol(symbol)):
            return quote                   # foreign symbols: keep Yahoo's numbers
        day = clock.to_ist(meta["regularMarketTime"]).date()
        wanted = clock.prev_trading_day(day)
        prev = next((b["c"] for b in reversed(daily) if b["t"].date() == wanted), None)
        if prev is None:
            try:
                _, intraday = self.candles(symbol, "5m", "5d")
                session = barlib.by_session(intraday).get(wanted)
                prev = session[-1]["c"] if session else None
            except IndianTraderError as exc:
                log.warning("no previous close for %s: %s", symbol, exc)
        today = next((b for b in daily if b["t"].date() == day), None)
        if today:
            quote["day_open"] = today["o"]
        if prev and quote["price"] is not None:
            quote["prev_close"] = prev
            quote["change"] = quote["price"] - prev
            quote["change_pct"] = quote["change"] / prev * 100
        return quote

    # -- F&O reference data ------------------------------------------------------------------

    def lot_sizes(self) -> Dict[str, dict]:
        """``{SYMBOL: {lot, underlying}}``, refreshed from NSE once a day."""
        cache_path = settings.path("cache", "lots.json")
        today = clock.now_ist().date().isoformat()
        cached = read_json(cache_path, {}) or {}
        if not self.offline and cached.get("date") == today and cached.get("lots"):
            return cached["lots"]
        try:
            lots = parse_lots(self.nse.lot_size_csv())
            if lots:
                if not self.offline:
                    write_json(cache_path, {"date": today, "lots": lots})
                return lots
            log.warning("NSE lot-size file was empty")
        except IndianTraderError as exc:
            log.warning("lot sizes unavailable from NSE: %s", exc)
            if cached.get("lots"):
                return cached["lots"]
        log.warning("using fallback lot sizes from config")
        return {k: {"lot": v, "underlying": k, "fallback": True} for k, v in self.cfg["fallback_lot_sizes"].items()}

    def lot_size(self, symbol: str) -> int:
        upper = symbol.upper()
        lots = self.lot_sizes()
        if upper in lots:
            return lots[upper]["lot"]
        if upper in self.cfg["fallback_lot_sizes"]:
            return self.cfg["fallback_lot_sizes"][upper]
        raise ValidationError("%s has no F&O lot size (not in NSE's F&O list)" % upper)

    def fo_stocks(self) -> List[str]:
        return sorted(s for s in self.lot_sizes()
                      if s not in NSE_INDICES and s not in BSE_INDICES and not s.startswith("NIFTY"))

    def index_members(self, list_name: str) -> List[dict]:
        return self.nse.index_members(list_name)

    def company_names(self) -> Dict[str, str]:
        """``{SYMBOL: company name}`` from the Nifty 500 list, to match headlines to tickers."""
        try:
            return {r["symbol"]: r["name"] for r in self.index_members("nifty500")}
        except IndianTraderError as exc:
            log.warning("company names unavailable: %s", exc)
            return {}

    def listed_companies(self) -> Dict[str, str]:
        """``{SYMBOL: company name}`` for every NSE-listed equity; the Nifty 500 list if that file fails."""
        try:
            rows = csv.DictReader(io.StringIO(self.nse.equity_list()))
            names = {(r.get("SYMBOL") or "").strip(): (r.get("NAME OF COMPANY") or "").strip() for r in rows}
            names.pop("", None)
            if names:
                return names
            log.warning("NSE equity list was empty")
        except IndianTraderError as exc:
            log.warning("NSE equity list unavailable: %s", exc)
        return self.company_names()

    def refresh_holidays(self) -> Dict[str, str]:
        table = clock.parse_nse_holidays(self.nse.holidays())
        clock.store_holidays(table)
        return table
