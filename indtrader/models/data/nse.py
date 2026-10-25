"""NSE website APIs and archive files (public, unofficial).

All endpoints live here, so a change on NSE's side is fixed in one place.
Offline file names are part of the contract with the recorded test
snapshots: keep them stable.
"""

import csv
import datetime as dt
import io
import logging
import urllib.parse
from typing import Any, Dict, List, Optional

from indtrader.core.errors import DataError, ValidationError
from indtrader.core.http import HttpClient

log = logging.getLogger(__name__)

API = "https://www.nseindia.com/api/"
ARCHIVES = "https://nsearchives.nseindia.com/content/"

INDEX_LISTS: Dict[str, str] = {
    "nifty50": "ind_nifty50list.csv", "nifty100": "ind_nifty100list.csv",
    "nifty200": "ind_nifty200list.csv", "nifty500": "ind_nifty500list.csv",
    "niftybank": "ind_niftybanklist.csv", "niftyit": "ind_niftyitlist.csv",
}


def parse_lots(raw: str) -> Dict[str, dict]:
    """fo_mktlots.csv -> ``{SYMBOL: {"lot": n, "underlying": name}}`` (nearest month with a value)."""
    out: Dict[str, dict] = {}
    header_seen = False
    for row in csv.reader(io.StringIO(raw)):
        row = [cell.strip() for cell in row]
        if not row or not any(row):
            continue
        if not header_seen:
            header_seen = True
            continue
        if len(row) < 3 or not row[1] or row[1].upper() == "SYMBOL":
            continue
        lot = next((int(cell) for cell in row[2:] if cell.isdigit()), None)
        if lot:
            out[row[1].upper()] = {"lot": lot, "underlying": row[0]}
    return out


class NseClient:
    def __init__(self, http: HttpClient) -> None:
        self.http = http

    def _api(self, endpoint: str, name: str, ttl: float = 0) -> Any:
        return self.http.json(API + endpoint, name=name, nse=True, ttl=ttl)

    # -- market --------------------------------------------------------------------

    def all_indices(self, ttl: float = 0) -> dict:
        payload = self._api("allIndices", "nse-allindices.json", ttl=ttl)
        if not payload.get("data"):
            raise DataError("NSE allIndices returned nothing")
        return payload

    def holidays(self) -> dict:
        return self._api("holiday-master?type=trading", "nse-holidays.json")

    def lot_size_csv(self) -> str:
        return self.http.text(ARCHIVES + "fo/fo_mktlots.csv", name="fo_mktlots.csv", nse=True)

    def index_members(self, list_name: str) -> List[dict]:
        """``[{symbol, name, industry}]`` for an NSE index list (cached a day)."""
        filename = INDEX_LISTS.get(list_name.lower())
        if not filename:
            raise ValidationError("unknown list %r (try: %s, fo)" % (list_name, ", ".join(INDEX_LISTS)))
        raw = self.http.text(ARCHIVES + "indices/" + filename, name=filename, nse=True, ttl=86400)
        rows = []
        for record in csv.DictReader(io.StringIO(raw)):
            record = {k.strip(): (v or "").strip() for k, v in record.items() if k}
            if record.get("Symbol"):
                rows.append({"symbol": record["Symbol"], "name": record.get("Company Name", ""),
                             "industry": record.get("Industry", "")})
        return rows

    # -- options ----------------------------------------------------------------------

    def option_expiries(self, symbol: str) -> List[dt.date]:
        payload = self._api("option-chain-contract-info?symbol=%s" % symbol, "nse-oc-info-%s.json" % symbol)
        out = []
        for text in payload.get("expiryDates") or []:
            try:
                out.append(dt.datetime.strptime(text, "%d-%b-%Y").date())
            except ValueError:
                log.warning("unreadable expiry %r for %s", text, symbol)
        if not out:
            raise DataError("NSE returned no expiries for %s (is it in F&O?)" % symbol)
        return sorted(out)

    def option_chain(self, symbol: str, expiry: dt.date, kind: str) -> dict:
        """Raw option-chain-v3 JSON; ``kind`` is 'Indices' or 'Equity'."""
        endpoint = "option-chain-v3?type=%s&symbol=%s&expiry=%s" % (kind, symbol, expiry.strftime("%d-%b-%Y"))
        return self._api(endpoint, "nse-oc-%s-%s.json" % (symbol, expiry.isoformat()))

    # -- flows ------------------------------------------------------------------------

    def fii_dii(self) -> list:
        return self._api("fiidiiTradeReact", "nse-fiidii.json")

    def large_deals(self) -> dict:
        return self._api("snapshot-capital-market-largedeal", "nse-largedeal.json")

    def participant_oi_csv(self, day: dt.date) -> str:
        name = "fao_participant_oi_%s.csv" % day.strftime("%d%m%Y")
        return self.http.text(ARCHIVES + "nsccl/" + name, name=name, nse=True)

    def oi_spurts_contracts(self) -> List[dict]:
        """Today's biggest open-interest changes per F&O contract (futures and options), flattened."""
        payload = self._api("live-analysis-oi-spurts-contracts", "nse-oi-spurts-contracts.json", ttl=300)
        rows: List[dict] = []
        for group in (payload or {}).get("data") or []:
            for name, items in group.items():
                rows += [dict(item, group=name) for item in items or []]
        return rows

    def variations(self, kind: str = "gainers") -> dict:
        """Top gainers or losers by index group (NIFTY, BANKNIFTY, FOSec = F&O securities ...)."""
        if kind not in ("gainers", "loosers"):
            raise ValidationError("variations: gainers or loosers (NSE's spelling)")
        return self._api("live-analysis-variations?index=%s" % kind, "nse-variations-%s.json" % kind, ttl=300)

    # -- companies and regulation ------------------------------------------------------------

    def announcements(self, symbol: Optional[str] = None, start: Optional[dt.date] = None,
                      end: Optional[dt.date] = None) -> Any:
        if symbol is None:
            return self._api("corporate-announcements?index=equities", "nse-ann-all.json")
        endpoint = "corporate-announcements?index=equities&symbol=%s" % urllib.parse.quote(symbol)
        if start and end:
            endpoint += "&from_date=%s&to_date=%s" % (start.strftime("%d-%m-%Y"), end.strftime("%d-%m-%Y"))
        return self._api(endpoint, "nse-ann-%s.json" % symbol)

    def circulars(self) -> dict:
        return self._api("circulars", "nse-circulars.json")

    # -- ownership and company data --------------------------------------------------------

    def equity_list(self) -> str:
        """EQUITY_L.csv: every listed NSE equity (symbol, name, ISIN), cached a day."""
        return self.http.text(ARCHIVES + "equities/EQUITY_L.csv", name="EQUITY_L.csv", nse=True, ttl=86400)

    def sast_filings(self, start: dt.date, end: dt.date) -> List[dict]:
        """SEBI takeover-code Reg 29 disclosures: crossing 5 %, and each 2 % change after that."""
        endpoint = "corporate-sast-reg29?index=equities&from_date=%s&to_date=%s" % (start.strftime("%d-%m-%Y"), end.strftime("%d-%m-%Y"))
        payload = self._api(endpoint, "nse-sast-%s-%s.json" % (start.isoformat(), end.isoformat()), ttl=1800)
        return (payload or {}).get("data") or []

    def shareholding_history(self, symbol: str) -> List[dict]:
        """Quarterly shareholding-pattern filings, newest first (promoter / public %, XBRL link)."""
        endpoint = "corporate-share-holdings-master?index=equities&symbol=%s" % urllib.parse.quote(symbol)
        payload = self._api(endpoint, "nse-shp-%s.json" % symbol, ttl=6 * 3600)
        if not isinstance(payload, list):
            raise DataError("NSE sent no shareholding list for %s" % symbol)
        return payload

    def shareholding_xbrl(self, url: str) -> str:
        """One shareholding-pattern XBRL file. Filings never change, so it is cached for 90 days."""
        if not url.startswith(ARCHIVES.split("/content/")[0]):
            raise ValidationError("not an NSE archive link: %s" % url)
        return self.http.text(url, name="nse-shp-" + url.rsplit("/", 1)[-1], nse=True, ttl=90 * 86400)

    def stock_info(self, symbol: str) -> dict:
        """Price, P/E, sector P/E, delivery %, 52-week range, volatility and margins for one equity."""
        endpoint = ("NextApi/apiClient/GetQuoteApi?functionName=getSymbolData&marketType=N&series=EQ&symbol=%s"
                    % urllib.parse.quote(symbol))
        payload = self._api(endpoint, "nse-info-%s.json" % symbol, ttl=600)
        try:
            return payload["equityResponse"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise DataError("NSE sent no quote data for %s" % symbol) from exc

    def event_calendar(self) -> list:
        return self._api("event-calendar", "nse-event-calendar.json", ttl=6 * 3600)
