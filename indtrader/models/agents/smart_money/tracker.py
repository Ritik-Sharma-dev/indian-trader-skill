"""Smart money: what institutions, insiders and big holders did, on one page.

* FII / DII cash-market flows for the day and the run of the last days
* FII positioning in index futures and options (participant open interest)
* the day's block and bulk deals
* insider open-market trades, insider clusters, pledges and takeover-code
  filings (the insider tracker, last few days)

Each part reads on its own; the verdict lists what lines up. Flows lag
prices and say nothing about the next five minutes: context for the day,
never an entry signal.
"""

import datetime as dt
import logging
from typing import List, Optional

from indtrader.core.errors import IndianTraderError
from indtrader.core.formatting import num
from indtrader.models.analytics.flows import MoneyFlows
from indtrader.models.analytics.insiders import InsiderTracker

log = logging.getLogger(__name__)


def fii_run(history: dict, days: int = 5) -> Optional[dict]:
    """Net FII and DII cash flows over the last ``days`` recorded sessions (rupees crore)."""
    def day_of(key: str) -> dt.date:
        return dt.datetime.strptime(key, "%d-%b-%Y").date()

    keys = sorted((k for k in history if history[k].get("FII")), key=day_of)[-days:]
    if not keys:
        return None
    fii = sum(history[k]["FII"]["net"] or 0 for k in keys)
    dii = sum((history[k].get("DII") or {}).get("net") or 0 for k in keys)
    selling_days = sum(1 for k in keys if (history[k]["FII"]["net"] or 0) < 0)
    return {"days": len(keys), "fii_net": round(fii, 2), "dii_net": round(dii, 2), "fii_selling_days": selling_days}


def verdict(flows: dict, insiders: Optional[dict]) -> List[str]:
    lines = []
    cash = (flows.get("fiidii") or {}).get("FII") or {}
    run = flows.get("fii_run")
    if cash.get("net") is not None:
        day = (flows.get("fiidii") or {}).get("date") or "the latest session"
        lines.append("FIIs %s %s crore in cash on %s" % ("sold" if cash["net"] < 0 else "bought", num(abs(cash["net"]), 0), day))
    if run and run["days"] >= 3:
        lines.append("over %d sessions FIIs net %s crore (%d selling days), DIIs net %s crore" % (
            run["days"], num(run["fii_net"], 0), run["fii_selling_days"], num(run["dii_net"], 0)))
        if run["fii_net"] < 0 < run["dii_net"] and run["dii_net"] >= abs(run["fii_net"]) * 0.8:
            lines.append("domestic funds are absorbing the FII selling: dips get bought more often")
    view = ((flows.get("participants") or {}).get("view") or {}).get("FII") or {}
    if view.get("fut_long_pct") is not None:
        share = view["fut_long_pct"]
        lines.append("FIIs are %.0f%% long in index futures: %s" % (share, "heavily short, so sharp short-covering rallies are possible" if share < 25 else
                                                                   "net short" if share < 45 else "balanced" if share <= 55 else "net long"))
    if insiders:
        for group in insiders.get("clusters", [])[:3]:
            lines.append("insider cluster: %d insiders %s %s in the open market" % (
                len(group["people"]), "bought" if group["kind"] == "buy" else "sold", group["symbol"] or group["company"]))
        summary = insiders.get("summary") or {}
        if summary.get("pledges_enforced"):
            lines.append("%d pledge(s) enforced by lenders: forced selling risk in those names" % summary["pledges_enforced"])
    return lines


class SmartMoneyTracker:
    def __init__(self, market) -> None:
        self.market = market

    def collect(self, now: dt.datetime, insider_days: int = 3) -> dict:
        flows = MoneyFlows(self.market).collect(now, "all")
        if flows.get("fiidii"):
            flows["fii_run"] = fii_run(flows["fiidii"].get("history") or {})
        insiders = None
        try:
            insiders = InsiderTracker(self.market).collect(now, days=insider_days, mark_seen=False)
        except IndianTraderError as exc:
            flows["errors"].append("insiders: %s" % exc)
        return {"flows": flows, "insiders": insiders, "verdict": verdict(flows, insiders),
                "errors": list(flows.get("errors", [])) + (insiders or {}).get("errors", [])}


def directional_deals(deals: List[dict]) -> List[dict]:
    """Drop round trips: a client that bought and sold the same stock the same day (market makers,
    arbitrage desks) has no view on it."""
    sides = {}
    for deal in deals:
        sides.setdefault((deal["symbol"], deal.get("client")), set()).add((deal.get("side") or "").upper())
    return [d for d in deals if len(sides[(d["symbol"], d.get("client"))]) == 1]
