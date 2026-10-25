"""Money flows: who is buying and selling.

* FII/FPI and DII cash-market buy / sell / net (rupees crore) for the latest
  day, kept in ``workspace/state/flows.json`` so a history builds up
* participant-wise open interest (FII, DII, Pro, Client) in index futures
  and options: is the FII book net long or short?
* today's bulk, block and short-selling deals
"""

import csv
import datetime as dt
import io
import logging
from typing import List, Optional, Set, Tuple

from indtrader.core import clock, settings
from indtrader.core.errors import DataError, IndianTraderError
from indtrader.core.storage import read_json, write_json

log = logging.getLogger(__name__)


def _number(value) -> Optional[float]:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse_participants(raw: str) -> dict:
    lines = [line for line in raw.splitlines() if line.strip()]
    title = lines[0].strip('"').strip(",").strip('"') if lines else ""
    rows = list(csv.reader(io.StringIO("\n".join(lines[1:]))))
    if not rows:
        raise DataError("participant OI file was empty")
    header = [h.strip() for h in rows[0]]
    out: dict = {"title": title}
    for row in rows[1:]:
        if row and row[0].strip():
            out[row[0].strip()] = {header[i]: _number(row[i]) for i in range(1, min(len(header), len(row)))}
    return out


def participant_view(participants: dict) -> Tuple[dict, List[str]]:
    """Long % in index futures and net index options per participant, with notes."""
    view = {}
    for who in ("FII", "DII", "Pro", "Client"):
        record = participants.get(who)
        if not record:
            continue
        fut_long, fut_short = record.get("Future Index Long") or 0, record.get("Future Index Short") or 0
        view[who] = {
            "fut_long": fut_long, "fut_short": fut_short,
            "fut_long_pct": fut_long / (fut_long + fut_short) * 100 if fut_long + fut_short else None,
            "net_calls": (record.get("Option Index Call Long") or 0) - (record.get("Option Index Call Short") or 0),
            "net_puts": (record.get("Option Index Put Long") or 0) - (record.get("Option Index Put Short") or 0),
        }
    notes = []
    fii = view.get("FII")
    if fii and fii["fut_long_pct"] is not None:
        share = fii["fut_long_pct"]
        reading = ("heavily short (bearish positioning; also short-covering fuel)" if share < 25 else
                   "net short" if share < 45 else "balanced" if share <= 55 else "net long" if share <= 75 else "heavily long")
        notes.append("FIIs hold %.0f%% long in index futures: %s" % (share, reading))
        tilt = (1 if fii["net_calls"] > 0 else -1) + (1 if fii["net_puts"] < 0 else -1)
        notes.append("FII index options: net calls %+d, net puts %+d (%s)" % (
            fii["net_calls"], fii["net_puts"], "bullish tilt" if tilt > 0 else "bearish tilt" if tilt < 0 else "mixed"))
    return view, notes


class MoneyFlows:
    def __init__(self, market) -> None:
        self.market = market

    def fii_dii(self) -> dict:
        out: dict = {}
        for record in self.market.nse.fii_dii() or []:
            who = "FII" if "FII" in (record.get("category") or "").upper() else "DII"
            out[who] = {"buy": _number(record.get("buyValue")), "sell": _number(record.get("sellValue")),
                        "net": _number(record.get("netValue"))}
            out["date"] = record.get("date")
        if "FII" not in out:
            raise DataError("NSE FII/DII data was empty")
        history_path = settings.path("state", "flows.json")
        history = read_json(history_path, {}) or {}
        if out.get("date") and not self.market.offline:
            history[out["date"]] = {"FII": out["FII"], "DII": out.get("DII")}
            write_json(history_path, history)
        out["history"] = history
        return out

    def participants(self, now: dt.datetime) -> dict:
        """The latest participant OI file (published about 19:00 IST)."""
        day = clock.prev_trading_day(now.date(), include=now.time() >= dt.time(19, 0))
        last_error: Optional[Exception] = None
        for _ in range(6):
            try:
                raw = self.market.nse.participant_oi_csv(day)
                if "Client Type" in raw:
                    parsed = parse_participants(raw)
                    parsed["date"] = day.isoformat()
                    return parsed
            except IndianTraderError as exc:
                last_error = exc
            day = clock.prev_trading_day(day)
        raise DataError("no participant OI file found (%s)" % last_error)

    def deals(self, symbols: Optional[Set[str]] = None) -> dict:
        payload = self.market.nse.large_deals()
        out: dict = {"date": payload.get("as_on_date")}
        for key, label in (("BULK_DEALS_DATA", "bulk"), ("BLOCK_DEALS_DATA", "block"), ("SHORT_DEALS_DATA", "short")):
            rows = []
            for record in payload.get(key) or []:
                if symbols and (record.get("symbol") or "").upper() not in symbols:
                    continue
                qty, price = _number(record.get("qty")), _number(record.get("watp"))
                rows.append({"symbol": record.get("symbol"), "name": record.get("name"), "client": record.get("clientName"),
                             "side": record.get("buySell"), "qty": qty, "price": price,
                             "value_cr": qty * price / 1e7 if qty and price else None, "date": record.get("date")})
            rows.sort(key=lambda r: -(r["value_cr"] or 0))
            out[label] = rows
        return out

    def collect(self, now: dt.datetime, what: str = "all", symbols: Optional[List[str]] = None) -> dict:
        """Each part is independent: a failing source adds a note."""
        result: dict = {"errors": []}
        if what in ("all", "fiidii"):
            try:
                result["fiidii"] = self.fii_dii()
            except IndianTraderError as exc:
                log.warning("FII/DII unavailable: %s", exc)
                result["errors"].append("FII/DII: %s" % exc)
        if what in ("all", "participants"):
            try:
                participants = self.participants(now)
                view, notes = participant_view(participants)
                result["participants"] = {"date": participants["date"], "view": view, "notes": notes}
            except IndianTraderError as exc:
                log.warning("participant OI unavailable: %s", exc)
                result["errors"].append("participant OI: %s" % exc)
        if what in ("all", "deals"):
            try:
                result["deals"] = self.deals({s.upper() for s in symbols} if symbols else None)
            except IndianTraderError as exc:
                log.warning("deals unavailable: %s", exc)
                result["errors"].append("deals: %s" % exc)
        return result
