"""Market pulse: Indian indices and sectors, India VIX, breadth and global cues.

Indian indices come from NSE's allIndices (Yahoo for the main ones if NSE
fails), SENSEX from BSE, global cues from Yahoo. GIFT Nifty has no free
feed; US futures and Asia stand in for the overnight mood.
"""

import logging
from typing import Optional

from indtrader.core.errors import IndianTraderError
from indtrader.models.data.symbols import GLOBAL_CUES

log = logging.getLogger(__name__)

KEY_INDICES = ["NIFTY 50", "NIFTY BANK", "NIFTY FINANCIAL SERVICES", "NIFTY MIDCAP SELECT",
               "NIFTY NEXT 50", "NIFTY MIDCAP 100", "NIFTY SMALLCAP 100", "INDIA VIX"]
YAHOO_FALLBACK = (("NIFTY 50", "NIFTY"), ("NIFTY BANK", "BANKNIFTY"), ("SENSEX", "SENSEX"), ("INDIA VIX", "INDIAVIX"))


def _number(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def vix_reading(vix: float) -> str:
    if vix < 13:
        return "calm (cheap options, smaller moves)"
    if vix < 18:
        return "normal"
    if vix < 25:
        return "elevated (bigger swings, pricier options)"
    return "high fear (wide swings; size down)"


class MarketPulse:
    def __init__(self, market) -> None:
        self.market = market

    def collect(self, with_global: bool = True) -> dict:
        result: dict = {"indices": [], "sectors": [], "breadth": None, "global": [], "errors": []}
        try:
            self._nse(result)
        except IndianTraderError as exc:
            log.warning("NSE indices unavailable, using Yahoo: %s", exc)
            result["errors"].append("NSE indices: %s (using Yahoo for the main indices)" % exc)
            self._yahoo_fallback(result)
        self._sensex(result)
        if with_global:
            self._global(result)
        vix = next((i for i in result["indices"] if i["name"] == "INDIA VIX"), None)
        if vix and vix["last"]:
            result["vix_note"] = vix_reading(vix["last"])
            # India VIX is annualised: the daily one-sigma move is about VIX / sqrt(365) percent
            result["nifty_expected_daily_move_pct"] = vix["last"] / (365 ** 0.5)
        return result

    def _nse(self, result: dict) -> None:
        payload = self.market.nse.all_indices()
        by_name = {r["index"]: r for r in payload["data"]}
        for name in KEY_INDICES:
            record = by_name.get(name)
            if record:
                result["indices"].append({
                    "name": name, "last": _number(record.get("last")), "change": _number(record.get("variation")),
                    "change_pct": _number(record.get("percentChange")), "high": _number(record.get("high")),
                    "low": _number(record.get("low")), "prev_close": _number(record.get("previousClose")),
                    "pe": _number(record.get("pe")), "week_ago": _number(record.get("oneWeekAgoVal")),
                    "month_change_pct": _number(record.get("perChange30d")),
                    "advances": record.get("advances"), "declines": record.get("declines")})
        sectors = [r for r in payload["data"] if r.get("key") == "SECTORAL INDICES"]
        result["sectors"] = sorted(({"name": r["index"], "change_pct": _number(r.get("percentChange")), "last": _number(r.get("last"))}
                                    for r in sectors), key=lambda s: -(s["change_pct"] or 0))
        result["breadth"] = {"advances": int(payload.get("advances") or 0), "declines": int(payload.get("declines") or 0),
                             "unchanged": int(payload.get("unchanged") or 0), "timestamp": payload.get("timestamp")}

    def _quote_row(self, name: str, symbol: str) -> dict:
        quote = self.market.quote(symbol)
        return {"name": name, "last": quote["price"], "change": quote["change"], "change_pct": quote["change_pct"],
                "high": quote["day_high"], "low": quote["day_low"], "prev_close": quote["prev_close"]}

    def _yahoo_fallback(self, result: dict) -> None:
        for name, symbol in YAHOO_FALLBACK:
            try:
                result["indices"].append(self._quote_row(name, symbol))
            except IndianTraderError as exc:
                result["errors"].append("%s: %s" % (name, exc))

    def _sensex(self, result: dict) -> None:
        if any(i["name"] == "SENSEX" for i in result["indices"]):
            return
        try:
            result["indices"].insert(1, self._quote_row("SENSEX", "SENSEX"))
        except IndianTraderError as exc:
            log.warning("SENSEX unavailable: %s", exc)
            result["errors"].append("SENSEX: %s" % exc)

    def _global(self, result: dict) -> None:
        quotes = self.market.raw_quotes([symbol for _, symbol in GLOBAL_CUES])
        if not quotes:
            result["errors"].append("global cues: no quotes")
            return
        for label, symbol in GLOBAL_CUES:
            quote = quotes.get(symbol)
            if quote and quote["last"] is not None:
                result["global"].append({"name": label, "symbol": symbol, "last": quote["last"], "change_pct": quote["change_pct"]})
