"""Where Indian market news comes from (all free).

* market feeds: Economic Times Markets and Stocks, Business Standard
  Markets, Moneycontrol latest, Google News ("Sensex OR Nifty")
* per stock: a Google News search for the company and the company's own
  NSE filings (results, orders, board meetings, acquisitions, ratings)
* policy: RBI press releases and notifications, SEBI, NSE circulars that
  matter to traders, ET Economy and Business Standard Economy
"""

import datetime as dt
import logging
import math
import urllib.parse
from typing import Dict, Iterable, List, Optional

from indtrader.core.errors import IndianTraderError
from indtrader.models.analytics.news import search_terms
from indtrader.models.data.feeds import FeedReader, clean_html, parse_time
from indtrader.models.data.symbols import is_index

log = logging.getLogger(__name__)

MARKET_FEEDS = [
    ("ET Markets", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms", "rss-et-markets.xml"),
    ("ET Stocks", "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms", "rss-et-stocks.xml"),
    ("Business Standard", "https://www.business-standard.com/rss/markets-106.rss", "rss-bs-markets.xml"),
    ("Moneycontrol", "https://www.moneycontrol.com/rss/latestnews.xml", "rss-mc-latest.xml"),
    ("Google News", "https://news.google.com/rss/search?q=Sensex+OR+Nifty+when:1d&hl=en-IN&gl=IN&ceid=IN:en", "rss-gnews-market.xml"),
]

POLICY_FEEDS = [
    ("RBI press release", "https://www.rbi.org.in/pressreleases_rss.xml", "rss-rbi-press.xml"),
    ("RBI notification", "https://www.rbi.org.in/notifications_rss.xml", "rss-rbi-notifications.xml"),
    ("SEBI", "https://www.sebi.gov.in/sebirss.xml", "rss-sebi.xml"),
    ("ET Economy", "https://economictimes.indiatimes.com/news/economy/rssfeeds/1373380680.cms", "rss-et-economy.xml"),
    ("BS Economy", "https://www.business-standard.com/rss/economy-102.rss", "rss-bs-economy.xml"),
]

# NSE circular departments that matter to an equity / F&O trader
NSE_CIRCULAR_DEPTS = frozenset({
    "Futures & Options", "Capital Market (Equities) Trade", "Surveillance & Investigation", "NSE Clearing - Capital Market",
    "NSE Clearing - Futures & Options", "Corporate Communications", "Investor Services Cell", "Member Compliance",
})


def google_feed_url(query: str, days: int = 2, since: Optional[dt.date] = None, until: Optional[dt.date] = None) -> str:
    """A Google News India search: the last ``days``, or ``since`` to ``until`` (both inclusive)."""
    if since:
        window = "after:%s before:%s" % ((since - dt.timedelta(days=1)).isoformat(), ((until or since) + dt.timedelta(days=1)).isoformat())
    else:
        window = "when:%dd" % days
    q = urllib.parse.quote_plus("%s %s" % (query, window))
    return "https://news.google.com/rss/search?q=%s&hl=en-IN&gl=IN&ceid=IN:en" % q


def stock_query(terms: List[str]) -> str:
    return "(%s) (share OR shares OR stock OR NSE OR BSE)" % " OR ".join('"%s"' % t for t in terms)


def parse_announcements(payload) -> List[dict]:
    rows = payload if isinstance(payload, list) else (payload.get("data") or [])
    items = []
    for record in rows:
        symbol = (record.get("symbol") or "").upper()
        category = (record.get("desc") or "").strip()
        text = clean_html(record.get("attchmntText"))
        items.append({"title": "%s: %s" % (symbol, category) + (" - " + text[:200] if text else ""),
                      "link": record.get("attchmntFile") or "", "summary": text[:400],
                      "time": parse_time(record.get("sort_date") or record.get("an_dt")), "source": "NSE filing",
                      "tickers": [symbol] if symbol else [], "company": record.get("sm_name"),
                      "industry": record.get("smIndustry"), "category": category})
    return items


def parse_circulars(payload, departments: Iterable[str] = NSE_CIRCULAR_DEPTS) -> List[dict]:
    wanted = set(departments)
    return [{"title": "NSE %s: %s" % (c.get("circDepartment"), (c.get("sub") or "").strip()),
             "link": c.get("circFilelink") or "", "summary": c.get("circDisplayNo") or "",
             "time": parse_time(c.get("cirDate")), "source": "NSE circular"}
            for c in (payload or {}).get("data", []) if not wanted or c.get("circDepartment") in wanted]


class IndiaNewsSources:
    def __init__(self, market) -> None:
        self.market = market
        self.feeds = FeedReader(market.http)

    def market_news(self, errors: List[str]) -> List[dict]:
        return self.feeds.read_many(MARKET_FEEDS, errors)

    def stock_news(self, tickers: Iterable[str], terms: Dict[str, List[str]], since: dt.datetime, until: dt.datetime,
                   with_filings: bool, errors: List[str], live: bool = True) -> List[dict]:
        """Google News for each ticker's names, plus its NSE filings, from ``since`` to ``until``."""
        items: List[dict] = []
        days = max(1, math.ceil((until - since).total_seconds() / 86400))
        for ticker in tickers:
            if is_index(ticker):
                continue
            query = stock_query(search_terms(terms.get(ticker) or [ticker]))
            url = google_feed_url(query, days) if live else google_feed_url(query, since=since.date(), until=until.date())
            try:
                found = self.feeds.read("Google News", url, "rss-gnews-%s.xml" % ticker)
                items += [dict(item, origin=ticker) for item in found]
            except IndianTraderError as exc:
                log.warning("Google News %s failed: %s", ticker, exc)
                errors.append("Google News %s: %s" % (ticker, exc))
            if with_filings and not ticker.endswith(".BO"):
                start = min(since.date(), until.date() - dt.timedelta(days=7))
                try:
                    items += parse_announcements(self.market.nse.announcements(ticker, start, until.date()))
                except IndianTraderError as exc:
                    log.warning("NSE filings %s failed: %s", ticker, exc)
                    errors.append("NSE filings %s: %s" % (ticker, exc))
        return items

    def latest_filings(self) -> List[dict]:
        return parse_announcements(self.market.nse.announcements())

    def policy_items(self, errors: List[str]) -> List[dict]:
        items: List[dict] = []
        for label, url, name in POLICY_FEEDS:
            try:
                found = self.feeds.read(label, url, name)
            except IndianTraderError as exc:
                log.warning("policy feed %s failed: %s", label, exc)
                errors.append("%s: %s" % (label, exc))
                continue
            if label == "SEBI":       # recovery certificates and attachment orders are noise for traders
                found = [f for f in found if "/enforcement/recovery" not in f["link"]]
            items += found
        try:
            items += parse_circulars(self.market.nse.circulars())
        except IndianTraderError as exc:
            log.warning("NSE circulars failed: %s", exc)
            errors.append("NSE circulars: %s" % exc)
        return items
