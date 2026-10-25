"""The daily brief: everything worth knowing before (or after) a session.

:meth:`DailyBrief.collect` gathers the sections as data; the page is
rendered by :func:`indtrader.views.reports.brief`. Each section is
independent: a failing source leaves a note, never stops the brief.
"""

import datetime as dt
import logging
from typing import List, Sequence

from indtrader.core import clock, settings
from indtrader.core.context import AppContext
from indtrader.core.errors import IndianTraderError
from indtrader.core.storage import read_json
from indtrader.models.agents.india_news import tagging
from indtrader.models.agents.india_news.sources import IndiaNewsSources
from indtrader.models.agents.market_analyst.pulse import MarketPulse
from indtrader.models.analytics.flows import MoneyFlows
from indtrader.models.analytics.news import enrich, within
from indtrader.models.analytics.option_chain import OptionChainAnalyzer, OptionChainService

log = logging.getLogger(__name__)


class DailyBrief:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    def collect(self, chains: Sequence[str] = ("NIFTY", "BANKNIFTY"), hours: int = 14, headlines: int = 12) -> dict:
        return {"status": clock.market_status(self.ctx.now), "pulse": MarketPulse(self.ctx.market).collect(),
                "flows": MoneyFlows(self.ctx.market).collect(self.ctx.now), "chains": self._chains(chains),
                "events": self._events(), "headlines": self._headlines(hours, headlines), "hours": hours,
                "watchlist": read_json(settings.path("watchlist.json"))}

    def _chains(self, symbols: Sequence[str]) -> List[dict]:
        out = []
        service, analyzer = OptionChainService(self.ctx.market), OptionChainAnalyzer(self.ctx.cfg)
        for symbol in symbols:
            try:
                chain = service.fetch(symbol, self.ctx.now)
                try:
                    lot = self.ctx.market.lot_size(symbol)
                except IndianTraderError:
                    lot = None
                out.append({"symbol": symbol, "analysis": analyzer.analyze(chain, self.ctx.now, lot)})
            except IndianTraderError as exc:
                log.warning("brief: %s chain unavailable: %s", symbol, exc)
                out.append({"symbol": symbol, "error": str(exc)})
        return out

    def _events(self) -> dict:
        try:
            calendar = self.ctx.market.nse.event_calendar()
            fo = set(self.ctx.market.fo_stocks())
        except IndianTraderError as exc:
            return {"items": [], "error": str(exc)}
        today = self.ctx.now.date()
        horizon = clock.next_trading_day(today)
        items = []
        for event in calendar or []:
            try:
                when = dt.datetime.strptime(event.get("date", ""), "%d-%b-%Y").date()
            except ValueError:
                continue
            if today <= when <= horizon and (event.get("symbol") or "").upper() in fo:
                items.append({"symbol": event["symbol"], "purpose": event.get("purpose", ""), "date": when})
        return {"items": items, "error": None}

    def _headlines(self, hours: int, limit: int) -> dict:
        errors: List[str] = []
        items = enrich(IndiaNewsSources(self.ctx.market).market_news(errors), {}, tagging.tag)
        return {"items": within(items, self.ctx.now, hours)[:limit], "errors": errors}
