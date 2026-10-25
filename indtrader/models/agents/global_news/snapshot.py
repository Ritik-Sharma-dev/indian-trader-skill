"""The overnight snapshot: US, futures, fear and rates, commodities, Asia,
Europe and Indian ADRs, with a rule-of-thumb mood score for the Indian open.

Changes are one-day changes against Yahoo's own previous close
(``chartPreviousClose`` per symbol): the multi-symbol daily feed skips
sessions and once turned one-day moves into two-day moves.
"""

import logging
from typing import Dict, List, Tuple

from indtrader.core.errors import DataError
from indtrader.core.formatting import pct

log = logging.getLogger(__name__)

GROUPS: List[Tuple[str, List[Tuple[str, str]]]] = [
    ("US", [("S&P 500", "^GSPC"), ("Nasdaq", "^IXIC"), ("Dow Jones", "^DJI"), ("Russell 2000", "^RUT")]),
    ("US futures", [("S&P fut", "ES=F"), ("Nasdaq fut", "NQ=F"), ("Dow fut", "YM=F")]),
    ("Fear and rates", [("US VIX", "^VIX"), ("US 10Y yield", "^TNX"), ("Dollar index", "DX-Y.NYB"), ("USD/INR", "USDINR=X")]),
    ("Commodities", [("Brent crude", "BZ=F"), ("WTI crude", "CL=F"), ("Gold", "GC=F"), ("Silver", "SI=F"), ("Copper", "HG=F"), ("Bitcoin", "BTC-USD")]),
    ("Asia", [("Nikkei", "^N225"), ("Hang Seng", "^HSI"), ("Shanghai", "000001.SS"), ("Kospi", "^KS11"), ("Taiwan", "^TWII")]),
    ("Europe", [("FTSE 100", "^FTSE"), ("DAX", "^GDAXI"), ("CAC 40", "^FCHI")]),
    ("Indian ADRs (NYSE)", [("Infosys ADR", "INFY"), ("Wipro ADR", "WIT"), ("HDFC Bank ADR", "HDB"), ("ICICI Bank ADR", "IBN"), ("Dr Reddy's ADR", "RDY")]),
]
ADRS = ("INFY", "WIT", "HDB", "IBN", "RDY")


class GlobalSnapshot:
    def __init__(self, market) -> None:
        self.market = market

    def collect(self) -> List[dict]:
        quotes = self.market.raw_quotes([symbol for _, group in GROUPS for _, symbol in group])
        if not quotes:
            raise DataError("no global quotes from Yahoo")
        snapshot = []
        for title, items in GROUPS:
            rows = []
            for label, symbol in items:
                quote = quotes.get(symbol)
                if not quote or quote["last"] is None:
                    continue
                row = {"name": label, "symbol": symbol, "last": quote["last"], "prev": quote["prev"], "change_pct": quote["change_pct"]}
                if symbol == "^TNX" and quote["prev"] is not None:
                    row["change_bp"] = round((quote["last"] - quote["prev"]) * 100, 1)
                if quote["time"]:
                    row["time"] = quote["time"].strftime("%d %b %H:%M")
                rows.append(row)
            snapshot.append({"group": title, "rows": rows})
        return snapshot


def mood(snapshot: List[dict]) -> dict:
    """A rule-of-thumb score for the Indian open from overnight markets."""
    by_symbol: Dict[str, dict] = {r["symbol"]: r for group in snapshot for r in group["rows"]}

    def change(symbol: str):
        row = by_symbol.get(symbol)
        return row["change_pct"] if row and row["change_pct"] is not None else None

    score, notes = 0, []
    for symbol, label in (("ES=F", "S&P futures"), ("NQ=F", "Nasdaq futures")):
        value = change(symbol)
        if value is not None and abs(value) >= 0.3:
            score += 1 if value > 0 else -1
            notes.append("%s %s" % (label, pct(value)))
    asia = [change(s) for s in ("^N225", "^HSI", "^KS11", "^TWII") if change(s) is not None]
    if asia:
        average = sum(asia) / len(asia)
        if abs(average) >= 0.5:
            score += 1 if average > 0 else -1
            notes.append("Asia average %s" % pct(average))
    for symbol, label, threshold, extra in (("^VIX", "US VIX", 5, ""), ("BZ=F", "Brent", 1.5, " (India imports ~85% of its oil)"),
                                            ("DX-Y.NYB", "dollar index", 0.4, "")):
        value = change(symbol)
        if value is not None and abs(value) >= threshold:
            score += -1 if value > 0 else 1
            notes.append("%s %s%s" % (label, pct(value), extra))
    yield_row = by_symbol.get("^TNX")
    if yield_row and yield_row.get("change_bp") is not None and abs(yield_row["change_bp"]) >= 5:
        score += -1 if yield_row["change_bp"] > 0 else 1
        notes.append("US 10Y %+.1f bp" % yield_row["change_bp"])
    adrs = [change(s) for s in ADRS if change(s) is not None]
    label = ("positive" if score >= 2 else "mildly positive" if score == 1 else
             "negative" if score <= -2 else "mildly negative" if score == -1 else "neutral")
    return {"score": score, "label": label, "notes": notes, "adr_avg_pct": round(sum(adrs) / len(adrs), 2) if adrs else None}
