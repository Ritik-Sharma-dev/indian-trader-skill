"""News processing shared by the news agents: identity, de-duplication,
ticker matching, a word-list mood score, time windows and the "seen" store.

Tagging rules are domain knowledge and live with each agent
(``agents/india_news/tagging.py``, ``agents/global_news/themes.py``).
"""

import datetime as dt
import hashlib
import logging
import re
import sqlite3
from contextlib import closing
from typing import Callable, Dict, Iterable, List, Optional, Pattern, Set

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
_JOINERS = ("&", "and", "of", "the", "for")

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


def name_terms(ticker: str, name: str, others: Iterable[str] = (), former: Iterable[str] = ()) -> List[str]:
    """How the news names a company: its name, the shortest start of it no other listed company
    shares, and brand-like symbols (current or former) that are not just the name squashed."""
    base = short_name(name)
    terms = [base] if base else []
    taken = [short_name(o).lower() for o in others if o and short_name(o).lower() != base.lower()]
    words = base.split()
    for size in range(1, len(words)):
        prefix = " ".join(words[:size])
        if words[size - 1].lower() in _JOINERS or len(prefix) < 4 or prefix.upper() in _CORPORATE_WORDS:
            continue
        if not any(o.startswith(prefix.lower()) for o in taken):
            terms.append(prefix)
            if size > 1 or len(words) < 3:
                break
    squashed = re.sub(r"[^a-z0-9]", "", base.lower())
    for code in [ticker] + list(former):
        lowered = code.lower()
        if not code.isalpha() or len(code) < 3 or (squashed and squashed.startswith(lowered)):
            continue
        if lowered in (t.lower() for t in terms) or any(o.startswith(lowered) for o in taken):
            continue
        terms.append(code.upper() if len(code) <= 4 else code.title())
    return terms or [ticker]


def search_terms(terms: List[str]) -> List[str]:
    """The terms worth a web search: a lone first word of the name brings in strangers."""
    first = terms[0].split()[0].lower() if terms and terms[0] else ""
    return [t for i, t in enumerate(terms) if i == 0 or " " in t or t.lower() != first]


def mention_patterns(tickers: Iterable[str], names: Dict[str, str], terms: Optional[Dict[str, List[str]]] = None) -> Dict[str, Pattern]:
    """One regex per ticker matching the code and the names the news uses for the company."""
    patterns = {}
    for ticker in tickers:
        alternatives = [re.escape(ticker)]
        if terms and terms.get(ticker):
            alternatives += [re.escape(t) for t in terms[ticker] if t.upper() != ticker]
        else:
            name = short_name(names.get(ticker, ""))
            if name and name.upper() != ticker:
                alternatives.append(re.escape(name))
                first = name.split()[0]
                if len(first) >= 5 and first.upper() not in _CORPORATE_WORDS:
                    alternatives.append(re.escape(first))
        patterns[ticker] = re.compile(r"\b(%s)\b" % "|".join(alternatives), re.I)
    return patterns


_MARKET_CONTEXT = re.compile(r"\b(shares?|stocks?|NSE|BSE|Sensex|Nifty|crore|lakh|Q[1-4]|FY\d\d|results?|profit|loss|revenue|earnings"
                             r"|target|IPO|listing|rating|brokerage|dividend|orders?|stake|acqui\w*|investors?|valuation|m-?cap"
                             r"|rall(y|ies)|falls?|rises?|jumps?|surges?|slumps?|gains?|board|CEO|CFO|MD|merger|demerger)\b|₹|\bRs\.?\s?\d", re.I)


_SECURITY_CODE = re.compile(r"\(([A-Z0-9&_-]{2,})\.(?:NS|BO)\)|\bNSE:\s?([A-Z0-9&_-]{2,})")
_FUND_PRODUCT = re.compile(r"\bETFs?\b|\bIndex Fund\b|\bMutual Fund\b|\bFund\s*\(G\)|\bDirect Plan\b|\bNAV\b")


def market_context(text: str) -> bool:
    return bool(_MARKET_CONTEXT.search(text or ""))


_FOREIGN_EXCHANGE = r"(LSE|LON|NYSE|NASDAQ|AMEX|OTC|TSX|ASX|TWSE|TPE|HKEX|HKG|SGX|KRX|TYO|ETR|EPA|FRA|SIX|JSE)"
_FOREIGN_SUFFIX = r"(PLC|Inc|Corp|Corporation|GmbH|AG|SA|NV|ASA|AB|Co\.?,? Ltd)"


def foreign_namesake(title: str, names: Iterable[str]) -> bool:
    """The headline is about a company abroad with the same name: 'NCC Group PLC', 'LSE:NCC'."""
    for name in names:
        word = re.escape(name)
        if re.search(r"\b%s\b(\s+[A-Z]\w*){0,2}\s+%s\b|\b%s\s?:\s?%s\b" % (word, _FOREIGN_SUFFIX, _FOREIGN_EXCHANGE, word), title or "", re.I):
            return True
    return False


def other_security(title: str, ticker: str) -> bool:
    """The headline is about a fund, or names another listed code (``(GROWWMETAL.NS)``) and not this one."""
    codes = {a or b for a, b in _SECURITY_CODE.findall(title or "")}
    return bool(_FUND_PRODUCT.search(title or "")) or (bool(codes) and ticker.upper() not in codes)


def publisher(item: dict) -> str:
    """'Google News / Groww' -> 'Groww'."""
    source = item.get("source") or ""
    return source.split(" / ", 1)[1] if " / " in source else ""


def item_id(item: dict) -> str:
    key = (item.get("link") or "") + "|" + item["title"].lower()[:120]
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def _words(title: str) -> Set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", title.lower()) if len(w) >= 3}


def _same_story(a: dict, b: dict, threshold: float = 0.6) -> bool:
    if "NSE filing" in (a.get("source"), b.get("source")) or not (a.get("time") and b.get("time")):
        return False
    if abs((a["time"] - b["time"]).total_seconds()) > 36 * 3600:
        return False
    first, second = a["_words"], b["_words"]
    return bool(first and second) and len(first & second) / len(first | second) >= threshold


def enrich(items: Iterable[dict], patterns: Dict[str, Pattern], tagger: Tagger) -> List[dict]:
    """Add ``id``, ``tickers``, ``tags`` and ``sentiment``; drop duplicates (same link, the same
    headline from another feed, or a reworded copy of a story already kept: counted in ``similar``)."""
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
        item["_words"] = _words(item["title"])
        twin = next((kept for kept in out if _same_story(kept, item)), None)
        if twin is not None:
            twin["similar"] = twin.get("similar", 0) + 1
            twin["tickers"] = sorted(set(twin["tickers"]) | tickers)
            continue
        item["tags"] = tagger(item["title"])
        item["sentiment"] = sentiment(item["title"] + " " + item.get("summary", "")[:200])
        out.append(item)
    for item in out:
        item.pop("_words", None)
    return out


def within(items: Iterable[dict], now: dt.datetime, hours: float) -> List[dict]:
    """Items dated in the last ``hours`` (and not in the future), newest first."""
    return between(items, now - dt.timedelta(hours=hours), now + dt.timedelta(minutes=10))


def between(items: Iterable[dict], since: dt.datetime, until: dt.datetime) -> List[dict]:
    picked = [it for it in items if it.get("time") and since <= it["time"] <= until]
    return sorted(picked, key=lambda it: it["time"], reverse=True)


class NewsArchive:
    """Every item a news run has fetched (workspace/news/archive.sqlite), so past days can be read again."""

    COLUMNS = ("id", "time", "title", "link", "source", "summary", "tickers", "tags", "sentiment", "similar")

    def __init__(self, path: str = "") -> None:
        self.path = path or settings.path("news", "archive.sqlite")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.execute("CREATE TABLE IF NOT EXISTS items (id TEXT PRIMARY KEY, time TEXT, title TEXT, link TEXT, source TEXT, "
                     "summary TEXT, tickers TEXT, tags TEXT, sentiment REAL, similar INTEGER)")
        return conn

    def save(self, items: Iterable[dict]) -> int:
        rows = [(it["id"], it["time"].isoformat(), it["title"], it.get("link") or "", it.get("source") or "", (it.get("summary") or "")[:400],
                 ",".join(it.get("tickers") or []), ",".join(it.get("tags") or []), it.get("sentiment") or 0.0, it.get("similar") or 0)
                for it in items if it.get("time") and it.get("id")]
        try:
            with closing(self._connect()) as conn, conn:
                conn.executemany("INSERT OR REPLACE INTO items VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        except sqlite3.Error as exc:
            log.warning("news archive not saved: %s", exc)
            return 0
        return len(rows)

    def load(self, since: dt.datetime, until: dt.datetime, tickers: Optional[Iterable[str]] = None) -> List[dict]:
        wanted = {t.upper() for t in tickers} if tickers else None
        try:
            with closing(self._connect()) as conn:
                rows = conn.execute("SELECT %s FROM items WHERE time >= ? AND time <= ?" % ", ".join(self.COLUMNS),
                                    (since.isoformat(), until.isoformat())).fetchall()
        except sqlite3.Error as exc:
            log.warning("news archive unreadable: %s", exc)
            return []
        out = []
        for row in rows:
            item = dict(zip(self.COLUMNS, row))
            item["time"] = dt.datetime.fromisoformat(item["time"])
            item["tickers"] = [t for t in item["tickers"].split(",") if t]
            item["tags"] = [t for t in item["tags"].split(",") if t]
            item["archived"] = True
            if wanted is None or wanted & set(item["tickers"]):
                out.append(item)
        return out


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
