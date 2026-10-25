"""Risk manager: PASS or BLOCK for every proposed order, with the reasons.

Reads ``orders.json``, the trader's rules, today's paper trades and NSE's
event calendar. Verdicts go to ``state/risk.json`` keyed by the order's
fingerprint, so the paper journal opens only an order that passed exactly
as it stands.

BLOCK on any of: missing or wrong-side stop; net loss at the stop over
``max_loss_per_trade``; today's losses + open risk + this trade over
``max_daily_loss``; ``max_trades_per_day`` reached; net reward:risk under
``min_reward_risk``; outside the entry window, market closed, or late on
the option's expiry day; option selling or futures when not allowed; a
lottery strike (delta under ``min_option_delta``); illiquid (wide spread or
low OI); lots or capital over the caps; a blocked ticker; a duplicate.
WARN (not blocking): India VIX over ``warn_vix_above``; results or a board
meeting for the stock today or tomorrow (BLOCK if ``block_on_results_day``).
"""

import datetime as dt
import logging
from typing import List, Optional

from indtrader.core import clock, settings
from indtrader.core.errors import IndianTraderError
from indtrader.core.formatting import inr, num
from indtrader.core.storage import read_json, write_json
from indtrader.models.data.symbols import is_index

log = logging.getLogger(__name__)


def paper_trades() -> List[dict]:
    return (read_json(settings.path("paper.json"), {}) or {}).get("trades", [])


def trades_on(day: dt.date) -> List[dict]:
    return [t for t in paper_trades() if (t.get("opened") or "")[:10] == day.isoformat()]


class RiskManager:
    def __init__(self, cfg: dict, market=None) -> None:
        self.cfg = cfg
        self.market = market

    def events_for(self, symbol: str, day: dt.date) -> Optional[List[dict]]:
        """Board meetings and results today or on the next trading day."""
        if self.market is None:
            return None
        try:
            calendar = self.market.nse.event_calendar()
        except IndianTraderError as exc:
            log.warning("event calendar unavailable: %s", exc)
            return None
        next_day = clock.next_trading_day(day)
        found = []
        for event in calendar or []:
            if (event.get("symbol") or "").upper() != symbol.upper():
                continue
            try:
                when = dt.datetime.strptime(event.get("date", ""), "%d-%b-%Y").date()
            except ValueError:
                continue
            if day <= when <= next_day:
                found.append({"date": when.isoformat(), "purpose": event.get("purpose"), "desc": (event.get("bm_desc") or "")[:160]})
        return found

    def check(self, order: dict, now: dt.datetime, vix: Optional[float] = None, trades: Optional[List[dict]] = None,
              use_events: bool = True) -> dict:
        cfg = self.cfg
        block: List[str] = []
        warn: List[str] = []
        day = now.date()
        trades = trades_on(day) if trades is None else trades
        kind = order["type"]
        long_premium = kind == "option" or order["action"] == "BUY"

        stop = order.get("stop_loss")
        if cfg["require_stop"] and not stop:
            block.append("stop: no stop-loss")
        elif stop:
            if long_premium and stop >= order["price"]:
                block.append("stop: %s is not below the entry %s" % (num(stop), num(order["price"])))
            if not long_premium and stop <= order["price"]:
                block.append("stop: %s is not above the entry %s" % (num(stop), num(order["price"])))
        if order.get("max_loss_net", 0) > cfg["max_loss_per_trade"] + 0.01:
            block.append("loss: %s at the stop is over your max %s" % (inr(order["max_loss_net"]), inr(cfg["max_loss_per_trade"])))
        realised = sum(min(0, t.get("net", 0) or 0) for t in trades if t.get("status") == "closed")
        open_risk = sum(t.get("max_loss_net", 0) or 0 for t in trades if t.get("status") == "open")
        used = -realised + open_risk
        if used + order.get("max_loss_net", 0) > cfg["max_daily_loss"] + 0.01:
            block.append("daily: %s already lost or at risk today + %s here is over the daily limit %s"
                         % (inr(used), inr(order.get("max_loss_net", 0)), inr(cfg["max_daily_loss"])))
        if len(trades) >= cfg["max_trades_per_day"]:
            block.append("count: %d trades already today (max %d)" % (len(trades), cfg["max_trades_per_day"]))
        if any(t.get("fingerprint") == order["fingerprint"] for t in trades):
            block.append("duplicate: this exact order was already taken today")
        if order.get("rr_net") is None or order["rr_net"] < cfg["min_reward_risk"]:
            block.append("reward: R:R after charges %s is under your minimum %s" % (num(order.get("rr_net")), num(cfg["min_reward_risk"])))
        block += self._clock_rules(order, now)
        block += self._permission_rules(order)
        block += self._size_rules(order)
        if vix is not None and vix > cfg["warn_vix_above"]:
            warn.append("India VIX %.1f is above %s: bigger swings, size down" % (vix, cfg["warn_vix_above"]))
        if use_events and not is_index(order["underlying"]):
            events = self.events_for(order["underlying"], day)
            if events:
                message = "event: %s" % "; ".join("%s %s" % (e["date"], e["purpose"]) for e in events)
                (block if cfg["block_on_results_day"] else warn).append(message)
        verdict = "BLOCK" if block else "PASS"
        log.info("risk %s %s x%s: %s%s", order["symbol"], order["action"], order.get("qty"), verdict,
                 (" (" + "; ".join(block) + ")") if block else "")
        return {"verdict": verdict, "block": block, "warn": warn, "fingerprint": order["fingerprint"],
                "checked": now.isoformat(timespec="seconds"), "daily_used": round(used, 2), "trades_today": len(trades)}

    def _clock_rules(self, order: dict, now: dt.datetime) -> List[str]:
        cfg, day, t = self.cfg, now.date(), now.time()
        found = []
        if order.get("date") and order["date"] != day.isoformat():
            found.append("window: the order is for %s, today is %s" % (order["date"], day))
        if not clock.is_trading_day(day):
            found.append("window: market closed today (%s)" % clock.holiday_name(day))
            return found
        start, end = clock.parse_hhmm(cfg["no_entries_before"]), clock.parse_hhmm(cfg["no_entries_after"])
        if not start <= t <= end:
            found.append("window: %s is outside your entry window %s-%s" % (now.strftime("%H:%M"), cfg["no_entries_before"], cfg["no_entries_after"]))
        if order["type"] == "option" and order.get("expiry") == day.isoformat() and t > clock.parse_hhmm(cfg["expiry_day_no_entries_after"]):
            found.append("window: expiry day after %s (premium decays fastest now)" % cfg["expiry_day_no_entries_after"])
        return found

    def _permission_rules(self, order: dict) -> List[str]:
        cfg, kind = self.cfg, order["type"]
        found = []
        if kind == "option" and order["action"] == "SELL" and not cfg["allow_option_selling"]:
            found.append("selling: option writing is switched off (allow_option_selling)")
        if kind == "future" and not cfg["allow_futures"]:
            found.append("futures: switched off (allow_futures)")
        if kind == "equity" and not cfg.get("allow_equity_intraday", True):
            found.append("equity: intraday equity is switched off")
        if order["underlying"].upper() in [b.upper() for b in cfg.get("blocked", [])]:
            found.append("blocked: %s is on your blocked list" % order["underlying"])
        if kind == "option":
            delta = abs(order.get("delta") or 0)
            if delta < cfg["min_option_delta"]:
                found.append("lottery: delta %.2f is under %.2f (far out of the money)" % (delta, cfg["min_option_delta"]))
            spread = order.get("spread_pct")
            if spread is not None and spread > cfg["max_option_spread_pct"]:
                found.append("liquidity: bid-ask spread %.1f%% is over %.1f%%" % (spread, cfg["max_option_spread_pct"]))
            if (order.get("oi") or 0) < cfg["min_option_oi"]:
                found.append("liquidity: OI %s is under %s" % (order.get("oi"), cfg["min_option_oi"]))
        return found

    def _size_rules(self, order: dict) -> List[str]:
        cfg = self.cfg
        found = []
        if order.get("lots") and order["lots"] > cfg["max_lots_per_trade"]:
            found.append("size: %d lots is over max_lots_per_trade %d" % (order["lots"], cfg["max_lots_per_trade"]))
        cap = cfg["capital"] * cfg["max_capital_per_trade_pct"] / 100
        if order.get("capital_used", 0) > cap + 0.01:
            found.append("size: %s capital is over the per-trade cap %s" % (inr(order["capital_used"]), inr(cap)))
        free = cfg["capital"] * (1 - cfg["cash_buffer_pct"] / 100) - sum(
            t.get("capital_used", 0) or 0 for t in paper_trades() if t.get("status") == "open")
        if order.get("capital_used", 0) > free + 0.01:
            found.append("size: needs %s, free capital is %s" % (inr(order["capital_used"]), inr(free)))
        return found


class RiskLedger:
    """Verdicts by order fingerprint (state/risk.json), kept for a week."""

    def __init__(self) -> None:
        self.path = settings.path("state", "risk.json")

    def record(self, results: List[dict], now: dt.datetime) -> None:
        cutoff = (now.date() - dt.timedelta(days=7)).isoformat()
        state = {k: v for k, v in (read_json(self.path, {}) or {}).items() if v.get("checked", "")[:10] >= cutoff}
        for result in results:
            state[result["fingerprint"]] = result
        write_json(self.path, state)

    def passed(self, order_fingerprint: str, now: dt.datetime) -> bool:
        record = (read_json(self.path, {}) or {}).get(order_fingerprint)
        return bool(record and record["verdict"] == "PASS" and record["checked"][:10] == now.date().isoformat())
