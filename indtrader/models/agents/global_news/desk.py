"""The global desk: snapshot + mood, calendar, and themed headlines."""

import datetime as dt
import logging
from typing import List

from indtrader.core.errors import IndianTraderError
from indtrader.models.agents.global_news.snapshot import GlobalSnapshot, mood
from indtrader.models.agents.global_news.sources import GlobalNewsSources
from indtrader.models.agents.global_news.themes import IMPACT, themes_of
from indtrader.models.analytics.news import enrich, within

log = logging.getLogger(__name__)


def theme_summary(items: List[dict]) -> List[dict]:
    counts = {}
    for item in items:
        for theme in item.get("themes", []):
            counts[theme] = counts.get(theme, 0) + 1
    return [{"theme": t, "count": n, "india_impact": IMPACT[t]} for t, n in sorted(counts.items(), key=lambda kv: -kv[1])]


class GlobalDesk:
    def __init__(self, market) -> None:
        self.market = market
        self.sources = GlobalNewsSources(market.http)

    def headlines(self, now: dt.datetime, hours: int = 18, errors=None, themed_only: bool = True) -> List[dict]:
        errors = errors if errors is not None else []
        items = enrich(self.sources.headlines(errors), {}, lambda _title: [])
        picked = within(items, now, hours)
        for item in picked:
            item["themes"] = themes_of(item["title"])
        return [it for it in picked if it["themes"]] if themed_only else picked

    def collect(self, now: dt.datetime, what: str = "all", hours: int = 18, themed_only: bool = True) -> dict:
        result: dict = {"errors": [], "hours": hours}
        if what in ("all", "snapshot"):
            try:
                result["snapshot"] = GlobalSnapshot(self.market).collect()
                result["mood"] = mood(result["snapshot"])
            except IndianTraderError as exc:
                log.warning("global snapshot unavailable: %s", exc)
                result["errors"].append("snapshot: %s" % exc)
        if what in ("all", "calendar"):
            try:
                result["calendar"] = self.sources.calendar(now)
            except IndianTraderError as exc:
                log.warning("economic calendar unavailable: %s", exc)
                result["errors"].append("calendar: %s" % exc)
        if what in ("all", "headlines"):
            result["headlines"] = self.headlines(now, hours, result["errors"], themed_only)
            result["themes"] = theme_summary(result["headlines"])
        return result
