"""Shareholding patterns: who owns a company, and who added or cut last quarter.

Every listed company files its shareholding pattern within 21 days of each
quarter end (SEBI LODR Reg 31). The XBRL file has the split by category
(promoters, foreign institutions, mutual funds, insurance, retail ...) and
names every public shareholder with more than 1 %. That makes it India's
answer to the US 13F, from the company's side: instead of "what does this
fund own", it answers "who owns this stock", and :meth:`find` turns it round
to search a list of stocks for one investor's name.

Holdings are a snapshot at the quarter end, filed up to three weeks later.
"""

import datetime as dt
import html
import logging
import re
from typing import Dict, Iterable, List, Optional

from indtrader.core.errors import DataError, IndianTraderError, ValidationError
from indtrader.models.data.symbols import name_key

log = logging.getLogger(__name__)

# context prefix in the XBRL -> (label, top-level group or None)
CATEGORIES = (
    ("ShareholdingOfPromoterAndPromoterGroup", "Promoters", None),
    ("InstitutionsForeign", "Foreign institutions (FPI/FDI)", None),
    ("InstitutionsDomestic", "Domestic institutions (DII)", None),
    ("MutualFundsOrUTI", "  Mutual funds", "InstitutionsDomestic"),
    ("InsuranceCompanies", "  Insurance companies", "InstitutionsDomestic"),
    ("ProvidentFundsOrPensionFunds", "  Provident / pension funds", "InstitutionsDomestic"),
    ("AlternativeInvestmentFunds", "  AIFs", "InstitutionsDomestic"),
    ("Banks", "  Banks", "InstitutionsDomestic"),
    ("Governments", "Government", None),
    ("NonInstitutions", "Non-institutions", None),
    ("ResidentIndividualShareholdersHoldingNominalShareCapitalUpToRsTwoLakh", "  Retail (up to Rs 2 lakh)", "NonInstitutions"),
    ("ResidentIndividualShareholdersHoldingNominalShareCapitalInExcessOfRsTwoLakh", "  HNI individuals (over Rs 2 lakh)", "NonInstitutions"),
    ("NonResidentIndians", "  NRIs", "NonInstitutions"),
    ("BodiesCorporate", "  Corporate bodies", "NonInstitutions"),
    ("PublicShareholding", "Public (total)", None),
)
PROMOTER_DOMAINS = ("IndividualsOrHUF", "OthersIndianShareholders", "IndividualsForeign", "OthersForeign", "ForeignIndividuals")

_CONTEXT_PCT = re.compile(r'<in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares\s+contextRef="([^"]+)"[^>]*>([^<]+)<')
_HOLDER = re.compile(r'<in-bse-shp:NameOfTheShareholder\s+contextRef="D_([^"]+)"[^>]*>([^<]+)<')
_SINGLE = r'<in-bse-shp:%s\s+contextRef="[^"]+"[^>]*>([^<]+)<'


def _humanise(prefix: str) -> str:
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", prefix).replace("Or ", "/ ").strip()


def _single(xml: str, tag: str) -> Optional[str]:
    match = re.search(_SINGLE % tag, xml)
    return html.unescape(match.group(1)).strip() if match else None


def parse_xbrl(xml: str) -> dict:
    """Category percentages and the named holders (over 1 %) from one shareholding-pattern XBRL file."""
    percents: Dict[str, float] = {}
    for context, value in _CONTEXT_PCT.findall(xml):
        try:
            percents[context] = round(float(value) * 100, 2)      # the file stores fractions: 0.5044
        except ValueError:
            continue
    if not percents:
        raise DataError("no shareholding percentages in the XBRL file (format changed?)")
    categories = {prefix: percents.get(prefix + "_ContextI") for prefix, _, _ in CATEGORIES}
    holders = []
    for context, name in _HOLDER.findall(xml):
        domain = context.rsplit("_Context", 1)[0]
        holders.append({"name": html.unescape(name).strip(), "group": domain, "category": _humanise(domain),
                        "promoter": domain in PROMOTER_DOMAINS, "pct": percents.get(context)})
    return {"symbol": _single(xml, "Symbol"), "company": _single(xml, "NameOfTheCompany"), "date": _single(xml, "DateOfReport"),
            "categories": categories, "holders": holders}


def _float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _quarter(text: str) -> Optional[dt.date]:
    try:
        return dt.datetime.strptime(text.title(), "%d-%b-%Y").date()
    except (AttributeError, ValueError):
        return None


def _broadcast(record: dict) -> dt.datetime:
    try:
        return dt.datetime.strptime((record.get("broadcastDate") or "").title(), "%d-%b-%Y %H:%M:%S")
    except ValueError:
        return dt.datetime.min


def filings(history: Iterable[dict]) -> List[dict]:
    """One filing per quarter end, newest first (a revision filed later replaces the original)."""
    by_quarter: Dict[dt.date, dict] = {}
    for record in history:
        quarter = _quarter(record.get("date") or "")
        if not quarter:
            continue
        current = by_quarter.get(quarter)
        if current is None or _broadcast(record) > _broadcast(current):
            by_quarter[quarter] = record
    return [dict(by_quarter[q], quarter=q.isoformat()) for q in sorted(by_quarter, reverse=True)]


def _holder_key(name: str) -> str:
    return name_key(name)[:28]


def holder_changes(latest: List[dict], previous: List[dict]) -> List[dict]:
    """Named holders now and a quarter ago: added, cut, new (crossed 1 %) or gone (fell under 1 % or sold).

    Names are matched loosely: filings spell the same holder 'Ltd' one quarter
    and 'Limited' the next, and cut long names at different lengths.
    Placeholder rows with no holding (0 %) are dropped.
    """
    latest = [h for h in latest if h["pct"]]
    previous = [h for h in previous if h["pct"]]
    before = {_holder_key(h["name"]): h for h in previous}
    out = []
    for holder in latest:
        old = before.pop(_holder_key(holder["name"]), None)
        change = None if old is None or holder["pct"] is None or old["pct"] is None else round(holder["pct"] - old["pct"], 2)
        out.append(dict(holder, before=old["pct"] if old else None, change=change, status="new" if old is None else "held"))
    out += [dict(old, before=old["pct"], pct=None, change=None, status="gone") for old in before.values()]
    return sorted(out, key=lambda h: -(h["pct"] or 0))


# Holders some companies file under a short form (TCS lists "LIC of India"):
# a search for either spelling finds both.
ALIASES = (("life insurance corporation", "lic"),)


def search_pattern(name: str):
    text = name.strip().lower()
    parts = [r"\b%s\b" % re.escape(text) if len(text) <= 4 else re.escape(text)]    # "lic" must not match "pub-lic"
    for long_form, short_form in ALIASES:
        if text == short_form or (len(text) > 4 and text in long_form) or long_form in text:
            parts += [re.escape(long_form), r"\b%s\b" % short_form]
    return re.compile("|".join(parts), re.IGNORECASE)


class ShareholdingService:
    def __init__(self, market) -> None:
        self.market = market

    def _quarters(self, symbol: str) -> List[dict]:
        quarters = filings(self.market.nse.shareholding_history(symbol.upper()))
        if not quarters:
            raise DataError("NSE has no shareholding filings for %s" % symbol.upper())
        return quarters

    def _parsed(self, filing: dict) -> dict:
        if not filing.get("xbrl"):
            raise DataError("the %s filing has no XBRL file" % filing["quarter"])
        return parse_xbrl(self.market.nse.shareholding_xbrl(filing["xbrl"]))

    def pattern(self, symbol: str) -> dict:
        """The latest quarter against the one before: categories, named holders, and the promoter trend."""
        quarters = self._quarters(symbol)
        latest = self._parsed(quarters[0])
        previous = None
        if len(quarters) > 1:
            try:
                previous = self._parsed(quarters[1])
            except IndianTraderError as exc:
                log.warning("%s previous quarter unreadable: %s", symbol, exc)
        rows = []
        for prefix, label, parent in CATEGORIES:
            now_pct = latest["categories"].get(prefix)
            old_pct = previous["categories"].get(prefix) if previous else None
            if now_pct is None and old_pct is None:
                continue
            rows.append({"key": prefix, "label": label, "parent": parent, "pct": now_pct, "before": old_pct,
                         "change": round(now_pct - old_pct, 2) if now_pct is not None and old_pct is not None else None})
        trend = [{"quarter": q["quarter"], "promoters": _float(q.get("pr_and_prgrp")), "public": _float(q.get("public_val"))}
                 for q in quarters[:8]]
        return {"symbol": symbol.upper(), "company": latest["company"] or quarters[0].get("name"), "quarter": quarters[0]["quarter"],
                "previous_quarter": quarters[1]["quarter"] if previous else None, "filed": quarters[0].get("broadcastDate"),
                "categories": rows, "holders": holder_changes(latest["holders"], previous["holders"] if previous else []),
                "promoter_trend": trend, "link": quarters[0].get("xbrl")}

    def find(self, name: str, symbols: List[str]) -> dict:
        """Every stock in ``symbols`` whose latest pattern names a holder matching ``name`` (over 1 %)."""
        if len(name.strip()) < 3:
            raise ValidationError("give at least 3 letters of the investor's name")
        pattern = search_pattern(name)
        hits, errors = [], []
        for symbol in symbols:
            try:
                quarter = self._quarters(symbol)[0]
                for holder in self._parsed(quarter)["holders"]:
                    if pattern.search(holder["name"]):
                        hits.append(dict(holder, symbol=symbol.upper(), quarter=quarter["quarter"]))
            except IndianTraderError as exc:
                log.info("find %s: %s skipped (%s)", name, symbol, exc)
                errors.append("%s: %s" % (symbol, exc))
        hits.sort(key=lambda h: -(h["pct"] or 0))
        return {"name": name, "searched": len(symbols), "hits": hits, "errors": errors}
