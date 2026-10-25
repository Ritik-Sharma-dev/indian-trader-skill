"""The risk desk: can the trader take a trade now, and how big?

It reads the user's limits (``config.json``), today's paper journal
(realised P&L, open trades and their risk), the decision maker's state
(today's one trade), and the market (India VIX, expiry day, the typical
risk of a NIFTY trade from the live rules' recent stops), and answers:

    STOP     the daily loss limit or the trade limit is used up, or today's trade is done
    BLOCKED  one lot of a typical trade risks more than max_loss_per_trade
    CAUTION  allowed, with warnings (high VIX, expiry day, little loss budget left)
    CLEAR    allowed: how many lots fit the limits

The decision maker calls :func:`daily_stop` before any BUY. Nothing here
changes the limits; only the user does, in ``config.json``.
"""

import datetime as dt
import logging
import statistics
from typing import List, Optional

from indtrader.core import settings
from indtrader.core.errors import IndianTraderError
from indtrader.core.formatting import inr, num
from indtrader.core.storage import read_json, write_json
from indtrader.models.agents.live_monitor.monitor import LiveMonitor
from indtrader.models.trading.charges import charges

log = logging.getLogger(__name__)


def today_trades(journal: dict, day: dt.date) -> List[dict]:
    return [t for t in (journal or {}).get("trades", []) if (t.get("opened") or "")[:10] == day.isoformat()]


def day_pnl(trades: List[dict]) -> dict:
    closed = [t for t in trades if t.get("status") == "closed"]
    open_ = [t for t in trades if t.get("status") == "open"]
    return {"trades": len(trades), "closed": len(closed), "open": len(open_),
            "realised": round(sum(t.get("net") or 0 for t in closed), 2),
            "open_risk": round(sum(t.get("max_loss_net") or 0 for t in open_), 2)}


def daily_stop(cfg: dict, now: dt.datetime) -> Optional[str]:
    """Why no new trade is allowed today, from the paper journal and the limits; None when allowed."""
    pnl = day_pnl(today_trades(read_json(settings.path("paper.json"), {"trades": []}), now.date()))
    if -pnl["realised"] + pnl["open_risk"] >= cfg["max_daily_loss"]:
        return "today's losses and open risk (%s) have reached the daily limit of %s" % (inr(-pnl["realised"] + pnl["open_risk"], 0),
                                                                                       inr(cfg["max_daily_loss"], 0))
    if pnl["trades"] >= cfg["max_trades_per_day"]:
        return "%d trades today: the limit is %d" % (pnl["trades"], cfg["max_trades_per_day"])
    return None


def lot_risk(premium: float, delta: float, index_risk_pts: float, lot: int, cfg: dict) -> float:
    """Loss on one lot if the index hits a stop ``index_risk_pts`` away (delta approximation), with charges."""
    loss_per_unit = min(premium, abs(delta) * index_risk_pts)
    sell = max(premium - loss_per_unit, 0.05)
    return round(loss_per_unit * lot + charges("option", premium * lot, sell * lot, cfg)["total"], 2)


class RiskDesk:
    def __init__(self, ctx) -> None:
        self.ctx = ctx
        self.cfg = ctx.cfg

    def typical_risk_points(self, symbol: str = "NIFTY") -> Optional[float]:
        """The median stop distance of the live rules' recent trades, cached for the day."""
        path = settings.path("state", "risk-profile.json")
        cached = read_json(path, {}) or {}
        key = "%s %s" % (self.ctx.now.date().isoformat(), symbol)
        if key in cached:
            return cached[key]
        try:
            _, trades = LiveMonitor(self.ctx).backtest(symbol, 30)
        except IndianTraderError as exc:
            log.warning("typical risk unavailable: %s", exc)
            return None
        value = round(statistics.median(t["risk"] for t in trades), 1) if trades else None
        if not self.ctx.pinned:
            write_json(path, {key: value})
        return value

    def status(self, symbol: str = "NIFTY", option: Optional[dict] = None, vix: Optional[float] = None,
               expiry_day: bool = False, decision_done: bool = False) -> dict:
        cfg, now = self.cfg, self.ctx.now
        pnl = day_pnl(today_trades(read_json(settings.path("paper.json"), {"trades": []}), now.date()))
        used = -pnl["realised"] + pnl["open_risk"]
        budget = max(cfg["max_daily_loss"] - used, 0.0)
        points = self.typical_risk_points(symbol)
        risk_per_lot = (lot_risk(option["premium"], option.get("delta") or 0.5, points, option["lot"], cfg)
                        if option and points and option.get("lot") else None)
        per_trade = min(cfg["max_loss_per_trade"], budget)
        lots = int(per_trade // risk_per_lot) if risk_per_lot else None
        if lots is not None and option and option.get("cost_per_lot"):
            capital_lots = int(cfg["capital"] * cfg["max_capital_per_trade_pct"] / 100 // option["cost_per_lot"])
            lots = min(lots, capital_lots, cfg["max_lots_per_trade"])
        reasons, warnings = [], []
        stop = daily_stop(cfg, now)
        if stop:
            reasons.append(stop)
        if decision_done:
            reasons.append("the decision maker's one trade for today is done")
        if vix and vix >= cfg["warn_vix_above"]:
            warnings.append("India VIX %s is above %s: wider swings, stops hit more often" % (num(vix), cfg["warn_vix_above"]))
        if expiry_day:
            warnings.append("expiry day: no entries after %s" % cfg["expiry_day_no_entries_after"])
        if 0 < budget < cfg["max_loss_per_trade"]:
            warnings.append("only %s of today's loss budget is left" % inr(budget, 0))
        if reasons:
            level = "STOP"
        elif lots == 0:
            level = "BLOCKED"
            reasons.append("one lot risks about %s at a typical stop (%s index points), over your max loss of %s per trade" % (
                inr(risk_per_lot, 0), num(points, 0), inr(cfg["max_loss_per_trade"], 0)))
        else:
            level = "CAUTION" if warnings else "CLEAR"
        return {"level": level, "reasons": reasons, "warnings": warnings, "pnl": pnl, "loss_budget": round(budget, 2),
                "typical_risk_points": points, "risk_per_lot": risk_per_lot, "lots_allowed": lots,
                "limits": {k: cfg[k] for k in ("capital", "max_loss_per_trade", "max_daily_loss", "max_trades_per_day", "max_lots_per_trade",
                                               "max_capital_per_trade_pct")},
                "option": option}
