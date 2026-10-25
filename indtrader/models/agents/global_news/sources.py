"""US and global news sources: RSS feeds and the economic calendar."""

import datetime as dt
import logging
from typing import List, Sequence

from indtrader.core import clock
from indtrader.models.data.feeds import FeedReader

log = logging.getLogger(__name__)

US_FEEDS = [
    ("CNBC Top", "https://www.cnbc.com/id/100003114/device/rss/rss.html", "rss-cnbc-top.xml"),
    ("CNBC Markets", "https://www.cnbc.com/id/15839069/device/rss/rss.html", "rss-cnbc-markets.xml"),
    ("CNBC Economy", "https://www.cnbc.com/id/20910258/device/rss/rss.html", "rss-cnbc-economy.xml"),
    ("CNBC World", "https://www.cnbc.com/id/100727362/device/rss/rss.html", "rss-cnbc-world.xml"),
    ("CNBC Asia", "https://www.cnbc.com/id/19832390/device/rss/rss.html", "rss-cnbc-asia.xml"),
    ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories", "rss-mw-top.xml"),
    ("Google News US",
     "https://news.google.com/rss/search?q=stock+market+OR+Fed+OR+%22Wall+Street%22+when:1d&hl=en-US&gl=US&ceid=US:en",
     "rss-gnews-us.xml"),
    ("Google News India-global",
     "https://news.google.com/rss/search?q=Indian+stock+market+global+cues+when:1d&hl=en-IN&gl=IN&ceid=IN:en",
     "rss-gnews-india-global.xml"),
]

CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
DEFAULT_COUNTRIES = ("USD", "CNY", "EUR", "JPY", "GBP", "All")
DEFAULT_IMPACTS = ("High", "Medium")


class GlobalNewsSources:
    def __init__(self, http) -> None:
        self.http = http
        self.feeds = FeedReader(http)

    def headlines(self, errors: List[str]) -> List[dict]:
        return self.feeds.read_many(US_FEEDS, errors)

    def calendar(self, now: dt.datetime, countries: Sequence[str] = DEFAULT_COUNTRIES, impacts: Sequence[str] = DEFAULT_IMPACTS,
                 days: int = 7) -> List[dict]:
        """This week's economic events (Forex Factory), times in IST."""
        events = []
        for record in self.http.json(CALENDAR_URL, name="ff-calendar-thisweek.json", ttl=1800) or []:
            if record.get("country") not in countries or record.get("impact") not in impacts:
                continue
            try:
                when = dt.datetime.fromisoformat(record["date"]).astimezone(clock.IST)
            except (KeyError, ValueError):
                log.debug("unreadable calendar date in %r", record)
                continue
            if when < now - dt.timedelta(hours=12) or when > now + dt.timedelta(days=days):
                continue
            if when < now:
                status = "past"
            elif when.date() == now.date():
                status = "today"
            elif when.date() == now.date() + dt.timedelta(days=1):
                status = "tomorrow"
            else:
                status = "later"
            events.append({"time": when, "country": record["country"], "event": record.get("title", ""),
                           "impact": record["impact"], "forecast": record.get("forecast") or None,
                           "previous": record.get("previous") or None, "when": status})
        return sorted(events, key=lambda e: e["time"])
