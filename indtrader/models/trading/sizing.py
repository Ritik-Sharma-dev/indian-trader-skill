"""Position sizing in LOTS, the proposed order, and the profit-goal table.

Size = the smallest of:

* max loss: ``max_loss_per_trade`` / (loss per lot at the stop + charges)
* trade cap: capital x ``max_capital_per_trade_pct`` / cost per lot
* cash: (capital - cash buffer - money in open paper trades) / cost per lot
* max lots: ``max_lots_per_trade``

Cost per lot: option = premium x lot; future = estimated margin; equity
intraday = value / leverage. Zero lots is a refusal, never a smaller trade.
The proposed order is written to ``workspace/orders.json`` for the risk
check; it is never sent anywhere.
"""

import datetime as dt
import logging
import math
from dataclasses import dataclass
from typing import Dict, Iterable, Tuple

from indtrader.core import settings
from indtrader.core.formatting import inr
from indtrader.core.storage import fingerprint, read_json
from indtrader.models.trading.charges import charges

log = logging.getLogger(__name__)

UNLIMITED = 10 ** 6
DEFAULT_LOT_STEPS = (1, 2, 3, 5, 10, 20, 40)


@dataclass
class TradeEconomics:
    """What one unit of the planned trade costs, earns and loses."""

    kind: str            # charge type: option, future, equity_intraday
    unit: int            # quantity per lot (1 for equity)
    cost_per_lot: float  # premium, margin or MIS margin for one lot
    entry: float
    stop: float
    target: float
    long: bool
    cfg: dict

    @classmethod
    def from_plan(cls, plan: dict, cfg: dict) -> "TradeEconomics":
        instrument, underlying = plan["instrument"], plan["underlying"]
        kind = instrument["type"]
        if kind == "option":
            premium = instrument["premium"]
            return cls("option", instrument["lot"], premium["entry"] * instrument["lot"], premium["entry"],
                       premium["stop"], premium["target"], True, cfg)    # buying an option is always long the premium
        long = plan["side"] == "long"
        if kind == "future":
            return cls("future", instrument["lot"], instrument["margin_per_lot_est"], underlying["entry"],
                       underlying["stop"], underlying["target"], long, cfg)
        return cls("equity_intraday", 1, underlying["entry"] / cfg["equity_intraday_leverage"], underlying["entry"],
                   underlying["stop"], underlying["target"], long, cfg)

    def result(self, quantity: int, exit_price: float) -> Tuple[float, Dict[str, float]]:
        """(gross P&L, charges) for ``quantity`` closed at ``exit_price``."""
        move = (exit_price - self.entry) if self.long else (self.entry - exit_price)
        buy, sell = (self.entry, exit_price) if self.long else (exit_price, self.entry)
        return move * quantity, charges(self.kind, buy * quantity, sell * quantity, self.cfg)

    def loss_at_stop(self, lots: int) -> float:
        gross, costs = self.result(lots * self.unit, self.stop)
        return -gross + costs["total"]


def open_capital() -> float:
    """Money tied up in open paper trades."""
    trades = (read_json(settings.path("paper.json"), {}) or {}).get("trades", [])
    return sum(t.get("capital_used", 0) or 0 for t in trades if t.get("status") == "open")


class PositionSizer:
    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg

    def size(self, plan: dict) -> dict:
        cfg = self.cfg
        equity = plan["instrument"]["type"] == "equity"
        econ = TradeEconomics.from_plan(plan, cfg)
        trade_cap = cfg["capital"] * cfg["max_capital_per_trade_pct"] / 100
        free = cfg["capital"] * (1 - cfg["cash_buffer_pct"] / 100) - open_capital()
        one_lot_loss = econ.loss_at_stop(1)

        limits = {"max loss": math.floor(cfg["max_loss_per_trade"] / one_lot_loss) if one_lot_loss > 0 else UNLIMITED}
        while limits["max loss"] > 0 and econ.loss_at_stop(limits["max loss"]) > cfg["max_loss_per_trade"]:
            limits["max loss"] -= 1                              # charges grow with size
        limits["trade cap"] = math.floor(trade_cap / econ.cost_per_lot) if econ.cost_per_lot > 0 else UNLIMITED
        limits["cash"] = math.floor(max(free, 0) / econ.cost_per_lot) if econ.cost_per_lot > 0 else UNLIMITED
        if not equity:
            limits["max lots"] = int(cfg["max_lots_per_trade"])
        lots = max(0, min(limits.values()))
        binding = min(limits, key=lambda k: limits[k])
        result = {"lots" if not equity else "shares": lots, "unit": econ.unit, "limits": limits, "binding": binding,
                  "cost_per_lot": round(econ.cost_per_lot, 2), "free_capital": round(free, 2), "kind": econ.kind}
        if lots == 0:
            result["refused"] = self._refusal(binding, equity, one_lot_loss, econ.cost_per_lot, trade_cap, free)
            log.info("sizing %s refused: %s", plan["symbol"], result["refused"])
            return result
        quantity = lots * econ.unit
        gross_stop, costs_stop = econ.result(quantity, econ.stop)
        gross_target, costs_target = econ.result(quantity, econ.target)
        result.update({"qty": quantity, "capital_used": round(econ.cost_per_lot * lots, 2),
                       "gross_at_stop": round(gross_stop, 2), "net_at_stop": round(gross_stop - costs_stop["total"], 2),
                       "gross_at_target": round(gross_target, 2), "net_at_target": round(gross_target - costs_target["total"], 2),
                       "charges_at_stop": costs_stop, "charges_at_target": costs_target})
        result["rr_net"] = round(result["net_at_target"] / -result["net_at_stop"], 2) if result["net_at_stop"] < 0 else None
        breakeven_move = costs_target["total"] / quantity
        result["breakeven"] = round(econ.entry + breakeven_move if econ.long else econ.entry - breakeven_move, 2)
        log.info("sizing %s: %d (%s), decided by %s", plan["symbol"], lots, "shares" if equity else "lots", binding)
        return result

    def _refusal(self, binding: str, equity: bool, one_lot_loss: float, cost: float, trade_cap: float, free: float) -> str:
        return {
            "max loss": "one %s loses %s at the stop (with charges), over your max loss %s"
                        % ("share" if equity else "lot", inr(one_lot_loss), inr(self.cfg["max_loss_per_trade"])),
            "trade cap": "one lot costs %s, over your per-trade cap %s" % (inr(cost), inr(trade_cap)),
            "cash": "free capital %s does not cover one lot (%s)" % (inr(free), inr(cost)),
            "max lots": "max_lots_per_trade is 0",
        }[binding]

    def target_table(self, plan: dict, profit: float, lot_steps: Iterable[int] = DEFAULT_LOT_STEPS) -> dict:
        """For a profit goal (net of charges): with n lots, how far must the
        price move, and what is lost if the plan's stop hits?"""
        econ = TradeEconomics.from_plan(plan, self.cfg)
        rows = []
        for lots in lot_steps:
            quantity = lots * econ.unit
            move = profit / quantity
            for _ in range(6):        # charges depend on the exit price: iterate to the fixed point
                exit_price = econ.entry + move if econ.long else econ.entry - move
                _, costs = econ.result(quantity, exit_price)
                move = (profit + costs["total"]) / quantity
            loss = econ.loss_at_stop(lots)
            rows.append({"lots": lots, "qty": quantity, "move_needed": round(move, 2), "move_pct": round(move / econ.entry * 100, 2),
                         "within_plan_target": move <= abs(econ.target - econ.entry), "loss_at_stop": round(loss, 2),
                         "capital": round(econ.cost_per_lot * lots, 2), "loss_vs_goal": round(loss / profit, 1)})
        return {"profit_goal": profit, "unit": "premium" if econ.kind == "option" else "price",
                "entry": econ.entry, "stop": econ.stop, "target": econ.target, "rows": rows}


def order_from(plan: dict, sized: dict, now: dt.datetime) -> dict:
    instrument = plan["instrument"]
    kind = instrument["type"]
    if kind == "option":
        action = "BUY"
        price, stop, target = instrument["premium"]["entry"], instrument["premium"]["stop"], instrument["premium"]["target"]
        symbol, product = instrument["tradingsymbol"], "NRML/MIS"
    else:
        action = "BUY" if plan["side"] == "long" else "SELL"
        price, stop, target = plan["underlying"]["entry"], plan["underlying"]["stop"], plan["underlying"]["target"]
        symbol = plan["symbol"] + (" FUT" if kind == "future" else "")
        product = "NRML/MIS" if kind == "future" else "MIS"
    order = {"symbol": symbol, "underlying": plan["symbol"], "type": kind, "action": action,
             "qty": sized["qty"], "lots": sized.get("lots"), "lot_size": sized["unit"] if kind != "equity" else None,
             "order_type": "LIMIT", "price": price, "stop_loss": stop, "target": target, "product": product,
             "side": plan["side"], "square_off_by": plan["square_off_by"], "underlying_levels": plan["underlying"],
             "date": plan["date"]}
    if kind == "option":
        order.update({k: instrument[k] for k in ("strike", "kind", "expiry", "delta", "spread_pct", "oi", "iv")})
    order["fingerprint"] = fingerprint({k: order[k] for k in ("symbol", "action", "qty", "price", "stop_loss", "target", "date")})
    order.update({"max_loss_net": -sized["net_at_stop"], "reward_net": sized["net_at_target"], "rr_net": sized["rr_net"],
                  "capital_used": sized["capital_used"], "charges_est": sized["charges_at_target"]["total"],
                  "breakeven": sized["breakeven"], "made": now.isoformat(timespec="minutes"), "paper": True})
    return order
