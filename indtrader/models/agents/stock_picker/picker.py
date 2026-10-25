"""The F&O stocks worth watching today, long and short.

Three readings per F&O stock, each worth a point:

* **relative strength**: its 20-day return minus NIFTY's (leaders keep
  leading intraday more often than laggards turn round)
* **today's move**: up or down at least 1 % (from the F&O gainers and
  losers lists, or the last two daily closes)
* **open-interest buildup** in its futures (NSE OI spurts): price up with OI
  up is long buildup, price down with OI up short buildup; price up with OI
  down is short covering, price down with OI down long unwinding

Long candidates score on strength, an up day and long buildup or short
covering; short candidates the mirror. The top names are a watchlist for
the opening-range and pullback setups (`scan orb`), not trades.
"""

import datetime as dt
import logging
from typing import Dict, List, Optional

from indtrader.core import clock
from indtrader.core.errors import IndianTraderError
from indtrader.core.formatting import pct

log = logging.getLogger(__name__)

ROLLOVER_DAYS = 5          # calendar days before the monthly expiry when futures OI is mostly rollover

BUILDUP = {(1, 1): "long buildup", (-1, 1): "short buildup", (1, -1): "short covering", (-1, -1): "long unwinding"}


def buildup(price_change_pct: Optional[float], oi_change_pct: Optional[float]) -> Optional[str]:
    if not price_change_pct or not oi_change_pct:
        return None
    return BUILDUP[(1 if price_change_pct > 0 else -1, 1 if oi_change_pct > 0 else -1)]


def futures_buildup(rows: List[dict]) -> Dict[str, dict]:
    """Per stock: OI change summed over every listed expiry, so a roll from this month to the next
    is not read as positions closed and opened; the price change is the near-month future's."""
    totals: Dict[str, dict] = {}
    for row in rows:
        if row.get("instrumentType") != "FUTSTK":
            continue
        entry = totals.setdefault(row["symbol"], {"change": 0.0, "prev": 0.0, "expiries": set(), "price": None, "near": None})
        entry["change"] += row.get("changeInOI") or 0
        entry["prev"] += row.get("prevOI") or 0
        entry["expiries"].add(row.get("expiryDate"))
        expiry = row.get("expiryDate") or ""
        if entry["near"] is None or _expiry_key(expiry) < _expiry_key(entry["near"]):
            entry["near"], entry["price"] = expiry, row.get("pChange")
    out = {}
    for symbol, entry in totals.items():
        oi_pct = round(entry["change"] / entry["prev"] * 100, 2) if entry["prev"] else None
        out[symbol] = {"price_change_pct": entry["price"], "oi_change_pct": oi_pct, "buildup": buildup(entry["price"], oi_pct),
                       "expiries_seen": len(entry["expiries"])}
    return out


def _expiry_key(text: str) -> tuple:
    try:
        return (dt.datetime.strptime(text, "%d-%b-%Y").date(),)
    except ValueError:
        return (dt.date.max,)


def movers(payload: dict) -> Dict[str, float]:
    """``{SYMBOL: change %}`` from NSE's F&O gainers or losers list."""
    return {r["symbol"]: r.get("perChange") for r in ((payload or {}).get("FOSec") or {}).get("data") or []}


def score(row: dict, side: str, count_oi: bool = True) -> List[str]:
    """The reasons a stock counts for one side (each reason is a point). ``count_oi`` is off in the
    monthly expiry week, when rollover swamps the OI change."""
    sign = 1 if side == "long" else -1
    reasons = []
    if row.get("rs_20d") is not None and row["rs_20d"] * sign >= 2:
        reasons.append("%s NIFTY by %.1f points over 20 days" % ("beats" if sign > 0 else "lags", abs(row["rs_20d"])))
    if row.get("change_pct") is not None and row["change_pct"] * sign >= 1:
        reasons.append("%s %s today" % ("up" if sign > 0 else "down", pct(row["change_pct"])))
    wanted = ("long buildup", "short covering") if sign > 0 else ("short buildup", "long unwinding")
    if count_oi and row.get("buildup") in wanted:
        reasons.append("%s in futures (OI %s)" % (row["buildup"], pct(row.get("oi_change_pct"))))
    return reasons


class StockPicker:
    def __init__(self, market) -> None:
        self.market = market

    def pick(self, now: dt.datetime, top: int = 8) -> dict:
        errors: List[str] = []
        expiry = clock.monthly_expiry("RELIANCE", now.date())
        rollover = 0 <= (expiry - now.date()).days <= ROLLOVER_DAYS
        universe = self.market.fo_stocks()
        closes = self.market.spark(universe + ["NIFTY"], rng="3mo", interval="1d", name_prefix="picker-spark")
        nifty = (closes.get("NIFTY") or {}).get("closes") or []
        nifty_20d = (nifty[-1] / nifty[-21] - 1) * 100 if len(nifty) > 21 else None
        try:
            oi = futures_buildup(self.market.nse.oi_spurts_contracts())
        except IndianTraderError as exc:
            errors.append("OI spurts: %s" % exc)
            oi = {}
        moves: Dict[str, float] = {}
        for kind in ("gainers", "loosers"):
            try:
                moves.update(movers(self.market.nse.variations(kind)))
            except IndianTraderError as exc:
                errors.append("F&O %s: %s" % (kind, exc))
        rows = []
        for symbol in universe:
            series = (closes.get(symbol) or {}).get("closes") or []
            if len(series) < 22:
                continue
            ret_20d = (series[-1] / series[-21] - 1) * 100
            change = moves.get(symbol, (series[-1] / series[-2] - 1) * 100)
            row = {"symbol": symbol, "last": series[-1], "change_pct": round(change, 2), "ret_20d": round(ret_20d, 2),
                   "rs_20d": round(ret_20d - nifty_20d, 2) if nifty_20d is not None else None}
            row.update(oi.get(symbol, {"buildup": None, "oi_change_pct": None}))
            row["long"], row["short"] = score(row, "long", not rollover), score(row, "short", not rollover)
            rows.append(row)
        longs = sorted((r for r in rows if len(r["long"]) >= 2), key=lambda r: (-len(r["long"]), -(r["rs_20d"] or 0)))
        shorts = sorted((r for r in rows if len(r["short"]) >= 2), key=lambda r: (-len(r["short"]), r["rs_20d"] or 0))
        return {"universe": len(universe), "scanned": len(rows), "nifty_20d": round(nifty_20d, 2) if nifty_20d is not None else None,
                "longs": longs[:top], "shorts": shorts[:top], "buildups": sum(1 for r in rows if r["buildup"]), "errors": errors,
                "rollover": rollover, "monthly_expiry": expiry.isoformat()}
