"""IndiaNewsAgent: the data half of the India market news report.

Collects the market headlines, policy and regulation updates, the filings
the market is reacting to, money flows and today's / tomorrow's results,
and writes ``india-news-data.md``. The Claude agent ``india-market-news``
reads it and adds web research and judgement.
"""

import datetime as dt
from typing import List

from indtrader.core import clock
from indtrader.core.errors import IndianTraderError
from indtrader.models.agents.base import Agent
from indtrader.models.agents.india_news.desk import NewsDesk, NewsQuery
from indtrader.models.analytics.flows import MoneyFlows


class IndiaNewsAgent(Agent):
    name = "india-news"
    title = "India market news (data)"

    def collect(self) -> dict:
        ctx = self.ctx
        desk = NewsDesk(ctx.market, ctx.cfg)
        findings: dict = {"errors": []}
        query = NewsQuery(hours=18, show_seen=True, mark_seen=False, stocks=False, limit=40, with_moves=False)
        headlines = desk.news(query, ctx.now)
        findings["headlines"] = headlines["items"]
        findings["errors"] += headlines["errors"]
        policy = desk.policy(ctx.now, hours=36, limit=30)
        findings["policy"] = policy["items"]
        findings["errors"] += policy["errors"]
        try:
            findings["movers"] = desk.movers(ctx.now, hours=24, limit=20)
        except IndianTraderError as exc:
            self.log.warning("movers unavailable: %s", exc)
            findings["errors"].append("movers: %s" % exc)
        flows = MoneyFlows(ctx.market).collect(ctx.now)
        findings["flows"] = {k: v for k, v in flows.items() if k != "errors"}
        findings["errors"] += flows["errors"]
        findings["events"] = self._events()
        return findings

    def _events(self) -> List[str]:
        try:
            calendar = self.ctx.market.nse.event_calendar()
            fo = set(self.ctx.market.fo_stocks())
        except IndianTraderError as exc:
            self.log.warning("event calendar unavailable: %s", exc)
            return []
        today = self.ctx.now.date()
        horizon = clock.next_trading_day(today)
        events = []
        for event in calendar or []:
            try:
                when = dt.datetime.strptime(event.get("date", ""), "%d-%b-%Y").date()
            except ValueError:
                continue
            if today <= when <= horizon and (event.get("symbol") or "").upper() in fo:
                events.append("%s: %s (%s)" % (event["symbol"], event.get("purpose", ""), when.strftime("%d %b")))
        return events
