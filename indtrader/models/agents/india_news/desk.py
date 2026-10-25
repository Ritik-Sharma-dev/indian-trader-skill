"""The India news desk: news for your tickers, filings the market is
reacting to, and policy / regulation updates."""

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

from indtrader.core import settings
from indtrader.core.errors import IndianTraderError
from indtrader.core.storage import read_json
from indtrader.models.agents.india_news import tagging
from indtrader.models.agents.india_news.sources import IndiaNewsSources
from indtrader.models.analytics.news import SeenStore, enrich, mention_patterns, within

log = logging.getLogger(__name__)


@dataclass
class NewsQuery:
    tickers: Optional[List[str]] = None
    hours: int = 12
    show_seen: bool = False
    mark_seen: bool = True
    market: bool = True
    stocks: bool = True
    filings: bool = True
    only_mine: bool = False
    limit: int = 40
    with_moves: bool = True


class NewsDesk:
    def __init__(self, market, cfg: dict) -> None:
        self.market = market
        self.cfg = cfg
        self.sources = IndiaNewsSources(market)

    def watch_tickers(self, explicit: Optional[List[str]] = None) -> List[str]:
        """The tickers to follow: given, else the last scan, the plan, open paper trades and the config watchlist."""
        if explicit:
            return [t.upper() for t in explicit]
        found: List[str] = []
        found += [h["symbol"] for h in (read_json(settings.path("watchlist.json"), {}) or {}).get("hits", [])[:15]]
        plan = read_json(settings.path("plan.json"), {}) or {}
        if plan.get("symbol"):
            found.append(plan["symbol"])
        found += [t["underlying"] for t in (read_json(settings.path("paper.json"), {}) or {}).get("trades", []) if t.get("status") == "open"]
        found += self.cfg.get("watchlist", [])
        unique: List[str] = []
        for ticker in (t.upper() for t in found):
            if ticker not in unique:
                unique.append(ticker)
        return unique

    def moves(self, tickers: List[str]) -> Dict[str, dict]:
        out = {}
        for ticker in tickers:
            try:
                out[ticker] = self.market.quote(ticker)
            except IndianTraderError as exc:
                log.info("no quote for %s: %s", ticker, exc)
        return out

    def news(self, query: NewsQuery, now: dt.datetime) -> dict:
        tickers = self.watch_tickers(query.tickers)
        follow_stocks = query.stocks
        names = self.market.company_names() if follow_stocks else {}
        errors: List[str] = []
        raw: List[dict] = []
        if query.market:
            raw += self.sources.market_news(errors)
        if follow_stocks:
            raw += self.sources.stock_news(tickers, names, now, query.filings, errors)
        items = enrich(raw, mention_patterns(tickers, names), tagging.tag)
        seen = SeenStore()
        selected = [it for it in within(items, now, query.hours) if query.show_seen or it["id"] not in seen]
        if query.only_mine:
            selected = [it for it in selected if it["tickers"]]
        if query.limit:
            selected = selected[: query.limit]
        if query.mark_seen:
            seen.mark(selected, now)
            seen.save(now)
        log.info("news: %d new items for %d tickers (%d sources failed)", len(selected), len(tickers), len(errors))
        return {"items": selected, "moves": self.moves(tickers[:12]) if query.with_moves else {}, "tickers": tickers,
                "errors": errors, "hours": query.hours}

    def movers(self, now: dt.datetime, hours: int = 24, any_company: bool = False, limit: int = 30) -> List[dict]:
        """The latest NSE filings, ranked by how far each stock moved today."""
        since = now - dt.timedelta(hours=hours)
        universe = None if any_company else set(self.market.fo_stocks())
        by_symbol: Dict[str, List[dict]] = {}
        for filing in self.sources.latest_filings():
            if not (filing["time"] and filing["time"] >= since and filing["tickers"]):
                continue
            symbol = filing["tickers"][0]
            if universe is None or symbol in universe:
                by_symbol.setdefault(symbol, []).append(filing)
        symbols = list(by_symbol)[:limit]
        quotes = self.moves(symbols)
        ranked = []
        for symbol in symbols:
            quote = quotes.get(symbol)
            filings = by_symbol[symbol]
            ranked.append({"symbol": symbol, "change_pct": quote["change_pct"] if quote else None, "price": quote["price"] if quote else None,
                           "filings": [{"time": f["time"], "category": f["category"], "text": f["summary"][:200], "link": f["link"]} for f in filings],
                           "tags": sorted({t for f in filings for t in tagging.tag(f["title"])})})
        ranked.sort(key=lambda r: -(abs(r["change_pct"]) if r["change_pct"] is not None else -1))
        return ranked

    def policy(self, now: dt.datetime, hours: int = 24, only: Optional[List[str]] = None, limit: int = 40) -> dict:
        errors: List[str] = []
        items = enrich(self.sources.policy_items(errors), {}, tagging.tag)
        for item in items:
            item["themes"] = tagging.policy_themes(item["title"] + " " + item.get("summary", "")[:200])
        since = now - dt.timedelta(hours=hours)
        # RBI / SEBI / NSE stamps can be date-only (midnight): keep the whole first day
        picked = [it for it in items if it["time"] and since.replace(hour=0, minute=0) <= it["time"] <= now + dt.timedelta(hours=1)]
        if only:
            picked = [it for it in picked if set(only) & set(it["themes"])]
        picked.sort(key=lambda it: it["time"], reverse=True)
        return {"items": picked[:limit] if limit else picked, "errors": errors, "since": since}
