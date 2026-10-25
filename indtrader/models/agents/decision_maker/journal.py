"""The decision journal: what the decision maker said each live day, and how it turned out.

The rules were chosen on past sessions (in-sample). The only honest test is
forward: every real-time decision is logged here, never a replay or a test
run, so after a few weeks :func:`summary` shows the live record, including
whether HIGH-confidence days really beat LOW ones (the research votes were
never backtested; this is where they get measured).

File: ``workspace/journal/decisions.json``, one record per symbol and day.
"""

import datetime as dt
import logging
from typing import Dict, List, Optional

from indtrader.core import settings
from indtrader.core.storage import read_json, write_json

log = logging.getLogger(__name__)


class DecisionJournal:
    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path or settings.path("journal", "decisions.json")
        self.data: Dict[str, dict] = read_json(self.path, {}) or {}

    @staticmethod
    def key(symbol: str, day: dt.date) -> str:
        return "%s %s" % (day.isoformat(), symbol)

    def record(self, symbol: str, day: dt.date, decision, gap: Optional[float], context: dict) -> dict:
        """Fold one decision into the day's record: the action history (changes only) and the outcome."""
        entry = self.data.setdefault(self.key(symbol, day), {"date": day.isoformat(), "symbol": symbol, "actions": []})
        entry["gap_pct"] = gap
        entry["lean"] = context.get("lean")
        entry["votes"] = {v["name"]: v["vote"] for v in context.get("votes", [])}
        if not entry["actions"] or entry["actions"][-1]["action"] != decision.action:
            entry["actions"].append({"time": decision.time[11:16], "action": decision.action, "headline": decision.headline})
        trade = decision.trade
        if decision.action == "NO TRADE":
            entry["outcome"] = {"taken": False, "reason": decision.headline}
        elif trade and decision.action in ("BUY CALL", "BUY PUT", "HOLD", "EXIT", "DONE"):
            entry["outcome"] = {"taken": True, "side": trade["side"], "setup": trade["setup"], "entry_time": trade["time"],
                                "entry": trade["entry"], "confidence": decision.confidence,
                                "exit_time": trade.get("exit_time"), "exit_reason": trade.get("exit_reason"),
                                "points": trade.get("points"), "r": trade.get("r")}
        elif decision.action == "DONE" and not trade:
            entry["outcome"] = {"taken": False, "reason": decision.headline}
        write_json(self.path, self.data)
        return entry

    def summary(self) -> dict:
        days = sorted(self.data.values(), key=lambda e: (e["date"], e["symbol"]))
        finished = [e for e in days if (e.get("outcome") or {}).get("taken") and e["outcome"].get("r") is not None]
        by_confidence: Dict[str, List[float]] = {}
        for entry in finished:
            by_confidence.setdefault(entry["outcome"]["confidence"] or "-", []).append(entry["outcome"]["r"])
        skipped = [e for e in days if (e.get("outcome") or {}).get("taken") is False]
        rs = [e["outcome"]["r"] for e in finished]
        return {"days": len(days), "trades": len(finished), "wins": sum(1 for r in rs if r > 0), "total_r": round(sum(rs), 2),
                "avg_r": round(sum(rs) / len(rs), 2) if rs else None,
                "by_confidence": {k: {"trades": len(v), "total_r": round(sum(v), 2), "wins": sum(1 for r in v if r > 0)}
                                  for k, v in sorted(by_confidence.items())},
                "no_trade_days": len(skipped), "first": days[0]["date"] if days else None, "last": days[-1]["date"] if days else None,
                "recent": days[-10:]}
