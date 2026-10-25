"""RSS feeds: fetch, parse and normalise news items.

An item is a dict ``{title, link, summary, time, source}``; ``time`` is an
aware IST datetime or ``None`` when the feed gave no usable date.
"""

import datetime as dt
import email.utils
import html
import logging
import re
import xml.etree.ElementTree as ET
from typing import List, Optional

from indtrader.core import clock
from indtrader.core.errors import DataError
from indtrader.core.http import HttpClient

log = logging.getLogger(__name__)

_DATE_FORMATS = ("%d-%b-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%d %b, %Y %z", "%Y%m%d")


def clean_html(text: Optional[str]) -> str:
    """Tags stripped, entities decoded, whitespace collapsed."""
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", text).strip()


def parse_time(text: Optional[str]) -> Optional[dt.datetime]:
    """RFC 822 dates and the formats NSE, RBI and SEBI use -> IST datetime."""
    if not text:
        return None
    text = text.strip()
    try:
        parsed = email.utils.parsedate_to_datetime(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=clock.IST)
        return parsed.astimezone(clock.IST)
    except (TypeError, ValueError):
        pass
    for fmt in _DATE_FORMATS:
        try:
            parsed = dt.datetime.strptime(text, fmt)
        except ValueError:
            continue
        return parsed.replace(tzinfo=clock.IST) if parsed.tzinfo is None else parsed.astimezone(clock.IST)
    log.debug("unreadable date %r", text)
    return None


def parse_rss(raw: bytes, source: str) -> List[dict]:
    """RSS 2.0 bytes -> items. Google News' "<title> - <publisher>" is split
    into the title and ``source = 'Google News / <publisher>'``."""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        try:                                         # stray bytes before the XML declaration
            root = ET.fromstring(raw.lstrip())
        except ET.ParseError as exc:
            raise DataError("%s: feed is not valid XML (%s)" % (source, exc)) from exc
    items = []
    for node in root.iter("item"):
        title = clean_html(node.findtext("title"))
        link = (node.findtext("link") or "").strip()
        if not title or "/us-stocks/" in link:       # ET's US-stocks section is not Indian market news
            continue
        label = source
        publisher = node.find("source")
        if publisher is not None and publisher.text:
            label = "%s / %s" % (source, publisher.text.strip())
            suffix = " - " + publisher.text.strip()
            if title.endswith(suffix):
                title = title[: -len(suffix)]
        items.append({"title": title, "link": link, "summary": clean_html(node.findtext("description"))[:400],
                      "time": parse_time(node.findtext("pubDate")), "source": label})
    return items


class FeedReader:
    def __init__(self, http: HttpClient) -> None:
        self.http = http

    def read(self, label: str, url: str, name: str) -> List[dict]:
        items = parse_rss(self.http.get(url, name=name), label)
        log.debug("%s: %d items", label, len(items))
        return items

    def read_many(self, feeds, errors: List[str]) -> List[dict]:
        """Read ``[(label, url, name)]``; a failing feed adds to ``errors`` instead of raising."""
        items: List[dict] = []
        for label, url, name in feeds:
            try:
                items += self.read(label, url, name)
            except DataError as exc:
                log.warning("feed %s failed: %s", label, exc)
                errors.append("%s: %s" % (label, exc))
        return items
