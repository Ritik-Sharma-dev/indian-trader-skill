"""Insider and large-holder trades: who inside the company is buying or selling.

Two public SEBI disclosures, both filed within two trading days:

* **PIT Reg 7(2)** (insider trading rules): promoters, directors, KMP and
  designated employees report every trade over Rs 10 lakh a quarter. Read
  from BSE's feed (most companies are listed on both exchanges).
* **SAST Reg 29** (takeover code): anyone crossing 5 % of a company, and
  every 2 % change after that. Read from NSE.

Most filings are noise for a trader: ESOP allotments, gifts, pledges moved
between family members. The signal is an insider buying or selling **in the
open market** with their own money, and several insiders doing it together
(a cluster). Pledge creation by a promoter is flagged as a risk.
"""

import datetime as dt
import logging
import re
from typing import Dict, Iterable, List, Optional

from indtrader.core import settings
from indtrader.core.errors import IndianTraderError
from indtrader.core.storage import fingerprint
from indtrader.models.analytics.news import SeenStore
from indtrader.models.data.symbols import name_key

log = logging.getLogger(__name__)

OPEN_MARKET = ("market purchase", "market sale", "open market")
CORE_INSIDERS = re.compile(r"promoter|director|kmp|key managerial", re.IGNORECASE)
EMPLOYEE_TRUST = re.compile(r"\b(ESOP|ESOS|ESPS)\b|\bemployees?'?\s+(welfare|benefit|stock|share)\b|\bwelfare trust\b", re.IGNORECASE)
MANAGEMENT_FILINGS = re.compile(r"resign|cessation|appointment|change in (directors|management|kmp)|director/kmp|\bKMP\b|retire", re.IGNORECASE)


def _number(value) -> Optional[float]:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _date(text: Optional[str]) -> Optional[dt.date]:
    if not text:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%d-%b-%Y", "%d-%B-%Y"):
        try:
            return dt.datetime.strptime(text[:19] if "T" in text else text[:11], fmt).date()
        except ValueError:
            continue
    return None


def _iso(text: Optional[str]) -> Optional[str]:
    day = _date(text)
    return day.isoformat() if day else None


def _stamp(text: Optional[str]) -> Optional[str]:
    """'2026-10-22T19:45:29.053' or '23-Oct-2026 13:20' -> '2026-10-22 19:45'."""
    if not text:
        return None
    for fmt, size in (("%Y-%m-%dT%H:%M:%S", 19), ("%d-%b-%Y %H:%M", 17)):
        try:
            return dt.datetime.strptime(text[:size], fmt).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue
    return text


class SymbolMatcher:
    """Maps a company name (as BSE spells it) to its NSE symbol; an ambiguous name maps to nothing."""

    def __init__(self, names: Dict[str, str]) -> None:
        self.by_key: Dict[str, Optional[str]] = {}
        for symbol, name in names.items():
            key = name_key(name)
            self.by_key[key] = None if key in self.by_key else symbol

    def __call__(self, company: str) -> Optional[str]:
        return self.by_key.get(name_key(company))


def classify(mode: str, direction: str) -> str:
    """buy / sell (open market), pledge, or other (ESOP, allotment, gift, inter-se ...)."""
    mode_l, direction_l = (mode or "").lower(), (direction or "").lower()
    if "pledge" in mode_l or direction_l in ("invoke", "revoke", "pledge invoke", "pledge revoke"):
        return "pledge"
    if mode_l in OPEN_MARKET:
        if "purchase" in mode_l or direction_l in ("acquisition", "buy"):
            return "buy"
        if "sale" in mode_l or direction_l in ("disposal", "sale", "sell"):
            return "sell"
    return "other"


def _row_id(prefix: str, record: dict, fields: tuple) -> str:
    """A stable id per row. The exchanges reuse one filing number for every row of a multi-line filing,
    so the number alone would make the seen-store hide rows that were never shown."""
    return "%s-%s" % (prefix, fingerprint([record.get(f) for f in fields]))


def pledge_label(mode: str, direction: str) -> str:
    """The exchanges' pledge wording is confusing: a transaction type of 'Invoke' means a pledge was
    *created*, while the mode 'Invocation of pledge' means the lender enforced it (sold or took the shares)."""
    mode_l, direction_l = (mode or "").lower(), (direction or "").lower()
    if "invocation" in mode_l:
        return "Pledge enforced"
    if "creation" in mode_l or direction_l == "invoke":
        return "Pledge created"
    if "revo" in mode_l or direction_l == "revoke":
        return "Pledge released"
    return mode or "-"


def from_bse(record: dict, matcher: SymbolMatcher) -> dict:
    qty, value = _number(record.get("Fld_SecurityNo")), _number(record.get("Fld_SecurityValue"))
    company = record.get("Companyname") or ""
    mode = record.get("ModeOfAquisation") or "-"
    kind = classify(mode, record.get("Fld_TransactionType"))
    if kind == "pledge":
        mode = pledge_label(mode, record.get("Fld_TransactionType"))
    category = record.get("Fld_PersonCatgName") or "-"
    if kind in ("buy", "sell") and (EMPLOYEE_TRUST.search(record.get("Fld_PromoterName") or "") or category.strip().lower() == "trust"):
        kind = "trust"
    return {
        "source": "PIT", "id": _row_id("pit", record, ("Fld_ID", "Fld_PromoterName", "Fld_SecurityNo", "Fld_FromDate", "Fld_ToDate",
                                                       "ModeOfAquisation", "Fld_TransactionType")),
        "symbol": matcher(company), "bse_code": record.get("Fld_ScripCode"),
        "company": company, "person": record.get("Fld_PromoterName"), "category": category,
        "kind": kind, "mode": mode, "security": record.get("Fld_SecurityTypeName") or "-",
        "qty": qty, "value": value, "price": round(value / qty, 2) if qty and value else None,
        "traded_from": _iso(record.get("Fld_FromDate")), "traded_to": _iso(record.get("Fld_ToDate")),
        "filed": _stamp(record.get("Fld_CreateDate")), "pct_before": _number(record.get("Fld_PercentofShareholdingPre")),
        "pct_after": _number(record.get("Fld_PercentofShareholdingPost")), "exchange": record.get("Fld_TradeExchange"),
        "link": ("https://www.bseindia.com" + record["xbrlurl"]) if record.get("xbrlurl") else None,
    }


def from_sast(record: dict) -> dict:
    sale = (record.get("acqSaleType") or "").lower().startswith("sale")
    mode = record.get("acquisitionMode") or "-"
    qty = _number(record.get("noOfShareSale") if sale else record.get("noOfShareAcq"))
    return {
        "source": "SAST", "id": _row_id("sast", record, ("application_no", "symbol", "acquirerName", "noOfShareAcq", "noOfShareSale",
                                                         "totAftShare", "timestamp")),
        "symbol": record.get("symbol"), "company": record.get("company"),
        "person": record.get("acquirerName"), "category": "Promoter" if record.get("promoterType") == "Y" else "Large holder",
        "kind": classify(mode, "sale" if sale else "acquisition"), "mode": mode, "security": record.get("acqType") or "-",
        "qty": qty, "value": None, "price": None, "traded_from": None, "traded_to": record.get("acquirerDate"),
        "filed": _stamp(record.get("timestamp")), "pct_change": _number(record.get("totSaleShare") if sale else record.get("totAcqShare")),
        "pct_after": _number(record.get("totAftShare")), "side": "sale" if sale else "acquisition", "link": record.get("attachement"),
    }


def dedupe(trades: Iterable[dict]) -> List[dict]:
    """BSE repeats some filings under new ids; keep one per (company, person, mode, quantity, dates, value)."""
    out, keys = [], set()
    for trade in trades:
        key = (trade["source"], trade["company"], trade["person"], trade["mode"], trade["qty"], trade["traded_to"], trade["value"])
        if key not in keys:
            keys.add(key)
            out.append(trade)
    return out


def clusters(trades: Iterable[dict], min_people: int = 2) -> List[dict]:
    """Companies where several insiders bought (or sold) in the open market in the window."""
    groups: Dict[tuple, dict] = {}
    for trade in trades:
        if trade["source"] != "PIT" or trade["kind"] not in ("buy", "sell"):
            continue
        key = (trade["symbol"] or trade["company"], trade["kind"])
        group = groups.setdefault(key, {"symbol": trade["symbol"], "company": trade["company"], "kind": trade["kind"],
                                        "people": set(), "value": 0.0, "filings": 0})
        group["people"].add(trade["person"])
        group["value"] += trade["value"] or 0
        group["filings"] += 1
    out = [dict(g, people=sorted(g["people"])) for g in groups.values() if len(g["people"]) >= min_people]
    return sorted(out, key=lambda g: (-len(g["people"]), -g["value"]))


def name_in(person: str, text: str) -> bool:
    """Every part of a person's name (3+ letters) appears in the text."""
    parts = [p for p in re.findall(r"[a-z]+", (person or "").lower()) if len(p) >= 3]
    lowered = (text or "").lower()
    return len(parts) >= 2 and all(re.search(r"\b%s\b" % p, lowered) for p in parts)


class InsiderTracker:
    def __init__(self, market) -> None:
        self.market = market

    def link_management_filings(self, trades: List[dict], start: dt.date, end: dt.date, errors: List[str], limit: int = 15) -> None:
        """Mark insider trades whose person also appears in the company's management-change filings."""
        people: Dict[str, List[dict]] = {}
        for trade in trades:
            if trade["source"] == "PIT" and trade["kind"] in ("buy", "sell") and trade["symbol"]:
                people.setdefault(trade["symbol"], []).append(trade)
        for symbol in list(people)[:limit]:
            try:
                payload = self.market.nse.announcements(symbol, start, end)
            except IndianTraderError as exc:
                log.info("no filings for %s: %s", symbol, exc)
                errors.append("management filings %s: %s" % (symbol, exc))
                continue
            rows = payload if isinstance(payload, list) else (payload or {}).get("data") or []
            filings = [r for r in rows if MANAGEMENT_FILINGS.search("%s %s" % (r.get("desc") or "", r.get("attchmntText") or ""))]
            for trade in people[symbol]:
                trade["linked"] = [{"category": (r.get("desc") or "").strip(), "filed": _stamp(r.get("an_dt") or r.get("sort_date")),
                                    "text": (r.get("attchmntText") or "")[:160]}
                                   for r in filings if name_in(trade["person"], "%s %s" % (r.get("desc") or "", r.get("attchmntText") or ""))]

    def collect(self, now: dt.datetime, days: int = 7, symbols: Optional[List[str]] = None, show_all: bool = False,
                min_value: float = 0, only_new: bool = False, mark_seen: bool = True) -> dict:
        """Insider (PIT) and takeover-code (SAST) filings of the last ``days``; each source fails on its own."""
        start, end = now.date() - dt.timedelta(days=days), now.date()
        wanted = {s.upper() for s in symbols} if symbols else None
        result: dict = {"from": start.isoformat(), "to": end.isoformat(), "errors": [], "trades": []}
        trades: List[dict] = []
        try:
            matcher = SymbolMatcher(self.market.listed_companies())
            trades += [from_bse(r, matcher) for r in self.market.bse.insider_trades(start, end)]
        except IndianTraderError as exc:
            log.warning("BSE insider feed unavailable: %s", exc)
            result["errors"].append("insider trades (BSE): %s" % exc)
        try:
            trades += [from_sast(r) for r in self.market.nse.sast_filings(start, end)]
        except IndianTraderError as exc:
            log.warning("NSE SAST feed unavailable: %s", exc)
            result["errors"].append("takeover-code filings (NSE): %s" % exc)

        trades = dedupe(trades)
        if wanted:
            trades = [t for t in trades if (t["symbol"] or "").upper() in wanted]
        result["total_filings"] = len(trades)
        if not show_all:
            trades = [t for t in trades if t["kind"] != "other"]
        if min_value:
            trades = [t for t in trades if t["source"] == "SAST" or (t["value"] or 0) >= min_value]
        seen = SeenStore(settings.path("state", "insiders.json"))
        for trade in trades:
            trade["new"] = trade["id"] not in seen
        if only_new:
            trades = [t for t in trades if t["new"]]
        if mark_seen and not self.market.offline:
            seen.mark(trades, now)
            seen.save(now)
        trades.sort(key=lambda t: t["filed"] or "", reverse=True)
        if wanted:
            self.link_management_filings(trades, start, end, result["errors"])
        result["trades"] = trades
        result["clusters"] = clusters(trades)
        pit = [t for t in trades if t["source"] == "PIT"]
        result["summary"] = {
            "insider_buys": sum(1 for t in pit if t["kind"] == "buy" and CORE_INSIDERS.search(t["category"])),
            "insider_sells": sum(1 for t in pit if t["kind"] == "sell" and CORE_INSIDERS.search(t["category"])),
            "buy_value": round(sum(t["value"] or 0 for t in pit if t["kind"] == "buy"), 2),
            "sell_value": round(sum(t["value"] or 0 for t in pit if t["kind"] == "sell"), 2),
            "pledges_created": sum(1 for t in pit if t["mode"] == "Pledge created"),
            "pledges_enforced": sum(1 for t in pit if t["mode"] == "Pledge enforced"),
            "sast": sum(1 for t in trades if t["source"] == "SAST"),
        }
        return result
