"""The full cost of an Indian intraday trade (rates in ``config["charges"]``).

* brokerage: flat per order for options; futures and equity pay the lower
  of the flat fee or a percentage of the order value
* STT: options 0.15% of the sell premium, futures 0.05% of the sell value
  (Budget 2026 rates), equity intraday 0.025% sell, delivery 0.1% both sides
* exchange transaction charge on turnover (premium for options)
* SEBI fee: Rs 10 per crore
* stamp duty: buy side only
* GST: 18% on brokerage + exchange + SEBI fees

Check the rates against the broker's contract note.
"""

from typing import Dict, Optional

from indtrader.core import settings
from indtrader.core.errors import ValidationError

KINDS = ("option", "future", "equity_intraday", "equity_delivery")


def charges(kind: str, buy_value: float, sell_value: float, cfg: Optional[settings.Settings] = None,
            orders: int = 2) -> Dict[str, float]:
    """Round-trip costs for ``buy_value`` and ``sell_value`` in rupees
    (premium x quantity for options)."""
    if kind not in KINDS:
        raise ValidationError("charge type %r: use %s" % (kind, ", ".join(KINDS)))
    rates = (cfg if cfg is not None else settings.load())["charges"]
    flat = rates["brokerage_per_order"]
    if kind == "option":
        brokerage = flat * orders
    else:
        cap = rates["brokerage_pct_cap"] / 100
        brokerage = sum(min(flat, value * cap) for value in (buy_value, sell_value)[:orders])
    stt, exchange, stamp = rates["stt"], rates["exchange_txn"], rates["stamp_duty"]
    turnover = buy_value + sell_value
    if kind == "option":
        stt_paid = sell_value * stt["option_sell_pct"] / 100
        exchange_paid = turnover * exchange["option_pct"] / 100
        stamp_paid = buy_value * stamp["option_buy_pct"] / 100
    elif kind == "future":
        stt_paid = sell_value * stt["future_sell_pct"] / 100
        exchange_paid = turnover * exchange["future_pct"] / 100
        stamp_paid = buy_value * stamp["future_buy_pct"] / 100
    elif kind == "equity_intraday":
        stt_paid = sell_value * stt["equity_intraday_sell_pct"] / 100
        exchange_paid = turnover * exchange["equity_pct"] / 100
        stamp_paid = buy_value * stamp["equity_intraday_buy_pct"] / 100
    else:
        stt_paid = turnover * stt["equity_delivery_pct"] / 100
        exchange_paid = turnover * exchange["equity_pct"] / 100
        stamp_paid = buy_value * stamp["equity_delivery_buy_pct"] / 100
    sebi = turnover * rates["sebi_per_crore"] / 1e7
    gst = (brokerage + exchange_paid + sebi) * rates["gst_pct"] / 100
    parts = {"brokerage": brokerage, "stt": stt_paid, "exchange": exchange_paid, "sebi": sebi, "stamp": stamp_paid, "gst": gst}
    parts = {name: round(value, 2) for name, value in parts.items()}
    parts["total"] = round(sum(parts.values()), 2)
    return parts
