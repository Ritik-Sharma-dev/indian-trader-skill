"""Paper trading journal: real prices, no real orders.

* open: the proposed order from ``orders.json``, only if the risk check
  passed it today (same fingerprint) and the trader confirmed it. An option
  buys at the live ask (NSE chain), equity / futures at the last price.
* mark: re-prices open trades; closes any at the stop, the target or
  ``square_off_by`` (options exit at the bid).
* close: one trade now. report: win rate, average R, gross, charges, net,
  drawdown and results by setup.

Ledger: ``workspace/paper.json``. Charges are deducted from every close.
"""

import datetime as dt
import logging
from typing import List, Optional, Tuple

from indtrader.core import clock, settings
from indtrader.core.errors import DataError, IndianTraderError, ValidationError
from indtrader.core.storage import read_json, write_json
from indtrader.models.analytics.option_chain import OptionChainService
from indtrader.models.trading.charges import charges
from indtrader.models.trading.risk import RiskLedger

log = logging.getLogger(__name__)

_COPIED_FIELDS = ("symbol", "underlying", "type", "action", "qty", "lots", "lot_size", "stop_loss", "target", "strike",
                  "kind", "expiry", "side", "square_off_by", "fingerprint", "max_loss_net", "reward_net", "capital_used",
                  "underlying_levels")


def _long_premium(trade: dict) -> bool:
    return trade["type"] == "option" or trade["action"] == "BUY"


def _charge_kind(trade: dict) -> str:
    return {"option": "option", "future": "future"}.get(trade["type"], "equity_intraday")


def settle(trade: dict, exit_price: float, when: dt.datetime, reason: str, spot: Optional[float] = None,
           cfg: Optional[dict] = None) -> dict:
    """Close ``trade`` at ``exit_price``: gross, charges, net and R."""
    quantity = trade["qty"]
    long = _long_premium(trade)
    gross = (exit_price - trade["entry"]) * quantity if long else (trade["entry"] - exit_price) * quantity
    buy, sell = (trade["entry"], exit_price) if long else (exit_price, trade["entry"])
    costs = charges(_charge_kind(trade), buy * quantity, sell * quantity, cfg)
    risk_rupees = abs(trade["entry"] - trade["stop_loss"]) * quantity
    trade.update({"status": "closed", "exit": round(exit_price, 2), "closed": when.isoformat(timespec="minutes"),
                  "reason": reason, "gross": round(gross, 2), "charges": costs["total"], "net": round(gross - costs["total"], 2),
                  "r": round(gross / risk_rupees, 2) if risk_rupees else None, "exit_spot": spot})
    log.info("paper %s closed at %.2f (%s): net %.2f", trade["id"], exit_price, reason, trade["net"])
    return trade


def stats(trades: List[dict]) -> Optional[dict]:
    closed = [t for t in trades if t["status"] == "closed"]
    if not closed:
        return None
    wins = [t for t in closed if t["net"] > 0]
    equity = peak = drawdown = 0.0
    for trade in sorted(closed, key=lambda t: t["closed"]):
        equity += trade["net"]
        peak = max(peak, equity)
        drawdown = min(drawdown, equity - peak)
    r_values = [t["r"] for t in closed if t.get("r") is not None]
    return {"trades": len(closed), "wins": len(wins), "win_rate": len(wins) / len(closed),
            "gross": round(sum(t["gross"] for t in closed), 2), "charges": round(sum(t["charges"] for t in closed), 2),
            "net": round(sum(t["net"] for t in closed), 2), "avg_r": round(sum(r_values) / len(r_values), 2) if r_values else None,
            "avg_win": round(sum(t["net"] for t in wins) / len(wins), 2) if wins else None,
            "avg_loss": round(sum(t["net"] for t in closed if t["net"] <= 0) / max(1, len(closed) - len(wins)), 2),
            "max_drawdown": round(drawdown, 2)}


class PaperJournal:
    def __init__(self, market, cfg: dict) -> None:
        self.market = market
        self.cfg = cfg
        self.path = settings.path("paper.json")
        self.ledger = read_json(self.path, {"trades": []}) or {"trades": []}

    @property
    def trades(self) -> List[dict]:
        return self.ledger["trades"]

    def save(self) -> None:
        write_json(self.path, self.ledger)

    def find_open(self, trade_id: str) -> dict:
        trade = next((t for t in self.trades if t["id"] == trade_id and t["status"] == "open"), None)
        if not trade:
            raise ValidationError("no open trade %s" % trade_id)
        return trade

    def live_price(self, trade: dict, now: dt.datetime, side: str) -> Tuple[float, float]:
        """(fill price, underlying spot); ``side`` is 'entry' (ask) or 'exit' (bid)."""
        if trade["type"] == "option":
            chain = OptionChainService(self.market).fetch(trade["underlying"], now, trade["expiry"])
            row = next((r for r in chain["rows"] if abs(r["strike"] - trade["strike"]) < 1e-6), None)
            leg = row and row[trade["kind"].lower()]
            if not leg:
                raise DataError("no quote for %s" % trade["symbol"])
            bid, ask = leg["bid"] or leg["ltp"], leg["ask"] or leg["ltp"]
            return (ask if side == "entry" else bid), chain["spot"]
        quote = self.market.quote(trade["underlying"])
        return quote["price"], quote["price"]

    def open(self, order: dict, now: dt.datetime, confirmed: bool, force: bool = False, price: Optional[float] = None,
             note: Optional[str] = None, setup: Optional[str] = None) -> Tuple[dict, float]:
        """Record the order as an open paper trade; returns (trade, slippage)."""
        if not force and not RiskLedger().passed(order["fingerprint"], now):
            raise ValidationError("this order has not passed /in-risk today; run the risk check first")
        if not confirmed:
            raise ValidationError("paper trades open only with your explicit yes: add --yes after the user confirms")
        if any(t["fingerprint"] == order["fingerprint"] and t["opened"][:10] == now.date().isoformat() for t in self.trades):
            raise ValidationError("this order is already in the journal today")
        trade = {key: order.get(key) for key in _COPIED_FIELDS}
        fill, spot = (price, None) if price is not None else self.live_price(trade, now, "entry")
        trade.update({"id": "%s-%d" % (now.strftime("%Y%m%d"), len(self.trades) + 1), "opened": now.isoformat(timespec="minutes"),
                      "entry": round(fill, 2), "planned_entry": order["price"], "entry_spot": spot, "status": "open",
                      "setup": setup, "note": note})
        self.trades.append(trade)
        self.save()
        log.info("paper %s opened: %s %s x%d at %.2f", trade["id"], trade["action"], trade["symbol"], trade["qty"], fill)
        return trade, fill - order["price"]

    def mark(self, now: dt.datetime, price: Optional[float] = None) -> List[dict]:
        """Re-price open trades; returns one event per trade."""
        events = []
        square_off = clock.parse_hhmm(self.cfg["square_off_by"])
        for trade in [t for t in self.trades if t["status"] == "open"]:
            try:
                last, spot = (price, None) if price is not None else self.live_price(trade, now, "exit")
            except IndianTraderError as exc:
                log.warning("paper %s: no price (%s)", trade["id"], exc)
                events.append({"trade": trade, "error": str(exc)})
                continue
            long = _long_premium(trade)
            hit = None
            if long:
                hit = "stop" if last <= trade["stop_loss"] else "target" if last >= trade["target"] else None
            else:
                hit = "stop" if last >= trade["stop_loss"] else "target" if last <= trade["target"] else None
            opened_day = dt.date.fromisoformat(trade["opened"][:10])
            if not hit and (now.date() > opened_day or now.time() >= square_off):
                hit = "square-off"
            trade["last"], trade["last_time"] = round(last, 2), now.isoformat(timespec="minutes")
            if hit:
                settle(trade, last, now, hit, spot, self.cfg)
                events.append({"trade": trade, "closed": hit, "price": last})
            else:
                events.append({"trade": trade, "price": last, "mtm": (last - trade["entry"]) * trade["qty"] * (1 if long else -1)})
        self.save()
        return events

    def close(self, trade_id: str, now: dt.datetime, price: Optional[float] = None, reason: Optional[str] = None) -> dict:
        trade = self.find_open(trade_id)
        exit_price, spot = (price, None) if price is not None else self.live_price(trade, now, "exit")
        settle(trade, exit_price, now, reason or "manual", spot, self.cfg)
        self.save()
        return trade
