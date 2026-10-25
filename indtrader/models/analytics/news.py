"""News processing shared by the news agents: identity, de-duplication,
ticker matching, a word-list mood score, time windows and the "seen" store.

Tagging rules are domain knowledge and live with each agent
(``agents/india_news/tagging.py``, ``agents/global_news/themes.py``).
"""

import datetime as dt
import hashlib
import logging
import re
from typing import Callable, Dict, Iterable, List, Pattern

from indtrader.core import settings
from indtrader.core.storage import read_json, write_json

log = logging.getLogger(__name__)

POSITIVE = ("surge", "surges", "jump", "jumps", "soar", "soars", "rally", "rallies", "gain", "gains", "rise", "rises",
            "record high", "beat", "beats", "upgrade", "upgraded", "strong", "growth", "profit up", "wins", "bags",
            "order win", "approval", "approved", "buy", "outperform", "bullish", "higher", "boost", "positive",
            "expands", "dividend", "bonus", "buyback", "recover", "rebound", "top gainer")
NEGATIVE = ("fall", "falls", "drop", "drops", "plunge", "plunges", "slump", "slumps", "crash", "tumble", "tumbles",
            "sink", "sinks", "decline", "declines", "loss", "losses", "miss", "misses", "downgrade", "downgraded",
            "weak", "probe", "penalty", "fine", "raid", "resigns", "default", "fraud", "sell", "bearish", "lower",
            "cut", "cuts", "warning", "pledge", "concern", "slowdown", "top loser", "insolvency", "ban", "halt")
_CORPORATE_WORDS = ("INDIAN", "BHARAT", "STATE", "TATA", "ADANI", "BAJAJ", "HINDUSTAN")

Tagger = Callable[[str], List[str]]


def sentiment(text: str) -> float:
    """-1 (all negative words) to +1 (all positive); 0 when none match."""
    lowered = " " + text.lower() + " "
    pos = sum(len(re.findall(r"\b%s\b" % re.escape(w), lowered)) for w in POSITIVE)
    neg = sum(len(re.findall(r"\b%s\b" % re.escape(w), lowered)) for w in NEGATIVE)
    return 0.0 if pos + neg == 0 else round((pos - neg) / (pos + neg), 2)


def short_name(name: str) -> str:
    """'Reliance Industries Limited' -> 'Reliance Industries'."""
    trimmed = re.sub(r"\b(limited|ltd\.?|ltd|corporation|corp\.?|company|co\.|india|\(india\))\s*$", "", name or "", flags=re.I)
    trimmed = re.sub(r"\s+(limited|ltd\.?)\b.*$", "", trimmed, flags=re.I)
    return trimmed.strip(" .,")


def mention_patterns(tickers: Iterable[str], names: Dict[str, str]) -> Dict[str, Pattern]:
    """One regex per ticker matching the code, the company name and a distinctive first word."""
    patterns = {}
    for ticker in tickers:
        alternatives = [re.escape(ticker)]
        name = short_name(names.get(ticker, ""))
        if name and name.upper() != ticker:
            alternatives.append(re.escape(name))
            first = name.split()[0]
            if len(first) >= 5 and first.upper() not in _CORPORATE_WORDS:
                alternatives.append(re.escape(first))
        patterns[ticker] = re.compile(r"\b(%s)\b" % "|".join(alternatives), re.I)
    return patterns


def item_id(item: dict) -> str:
    key = (item.get("link") or "") + "|" + item["title"].lower()[:120]
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def enrich(items: Iterable[dict], patterns: Dict[str, Pattern], tagger: Tagger) -> List[dict]:
    """Add ``id``, ``tickers``, ``tags`` and ``sentiment``; drop duplicates
    (same link, or the same headline from another feed)."""
    out, seen = [], set()
    for item in items:
        item["id"] = item_id(item)
        normalised = re.sub(r"\W+", " ", item["title"].lower())[:90]
        if item["id"] in seen or normalised in seen:
            continue
        seen.update((item["id"], normalised))
        tickers = set(item.get("tickers") or [])
        tickers.update(t for t, rx in patterns.items() if rx.search(item["title"]))
        item["tickers"] = sorted(tickers)
        item["tags"] = tagger(item["title"])
        item["sentiment"] = sentiment(item["title"] + " " + item.get("summary", "")[:200])
        out.append(item)
    return out


def within(items: Iterable[dict], now: dt.datetime, hours: float) -> List[dict]:
    """Items dated in the last ``hours`` (and not in the future), newest first."""
    since = now - dt.timedelta(hours=hours)
    picked = [it for it in items if it.get("time") and since <= it["time"] <= now + dt.timedelta(minutes=10)]
    return sorted(picked, key=lambda it: it["time"], reverse=True)


class SeenStore:
    """Remembers which items were shown, for 30 days (workspace/state/news.json)."""

    def __init__(self, path: str = "") -> None:
        self.path = path or settings.path("state", "news.json")
        self.seen: Dict[str, str] = (read_json(self.path, {}) or {}).get("seen", {})

    def __contains__(self, item_id_: str) -> bool:
        return item_id_ in self.seen

    def mark(self, items: Iterable[dict], now: dt.datetime) -> None:
        for item in items:
            self.seen[item["id"]] = now.isoformat()

    def save(self, now: dt.datetime) -> None:
        cutoff = (now - dt.timedelta(days=30)).isoformat()
        self.seen = {k: v for k, v in self.seen.items() if v >= cutoff}
        write_json(self.path, {"seen": self.seen})
