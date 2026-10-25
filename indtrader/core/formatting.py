"""Text formatting for terminal output: rupees, numbers, percents, tables, ticks."""

import json
import math
from typing import Any, Optional, Sequence


def inr(value: Optional[float], decimals: int = 2, sign: bool = False) -> str:
    """Indian digit grouping: 1234567.5 -> '₹12,34,567.50'."""
    if value is None:
        return "-"
    text = "%.*f" % (decimals, abs(value))          # round first, so 0.999 -> 1.00
    whole, _, frac = text.partition(".")
    frac = "." + frac if frac else ""
    negative = value < 0 and text.strip("0.") != ""
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups) + "," + tail
    out = "₹" + whole + frac
    if negative:
        return "-" + out
    return "+" + out if sign else out


def num(value: Optional[float], decimals: int = 2) -> str:
    return "-" if value is None else "%.*f" % (decimals, value)


def pct(value: Optional[float], decimals: int = 2, sign: bool = True) -> str:
    if value is None:
        return "-"
    return ("%+.*f%%" if sign else "%.*f%%") % (decimals, value)


def round_tick(price: Optional[float], tick: float = 0.05, mode: str = "nearest") -> Optional[float]:
    """Round to the exchange tick (0.05 for NSE F&O and most equities).

    ``mode`` is ``nearest``, ``down`` or ``up``; stops round away from the entry.
    """
    if price is None:
        return None
    steps = price / tick
    if mode == "down":
        steps = math.floor(steps + 1e-9)
    elif mode == "up":
        steps = math.ceil(steps - 1e-9)
    else:
        steps = math.floor(steps + 0.5)
    return round(steps * tick, 2)


def table(rows: Sequence[Sequence[Any]], headers: Sequence[str], align: Optional[str] = None) -> str:
    """A plain-text table; ``align`` has one 'l' or 'r' per column."""
    cells = [["" if c is None else str(c) for c in row] for row in rows]
    widths = [len(h) for h in headers]
    for row in cells:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    align = align or ("l" + "r" * (len(headers) - 1))

    def line(row: Sequence[str]) -> str:
        return "  ".join(c.ljust(widths[i]) if align[i] == "l" else c.rjust(widths[i]) for i, c in enumerate(row)).rstrip()

    return "\n".join([line(headers), "  ".join("-" * w for w in widths)] + [line(r) for r in cells])


def to_json(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)


def print_json(data: Any) -> None:
    print(to_json(data))
