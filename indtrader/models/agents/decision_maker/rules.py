"""The decision maker's hard rules, and the test that chose them.

The live engine finds setups (opening-range breaks, pullbacks, level
breaks). Run on 58 NIFTY sessions (Jul-Oct 2026) it was close to
break-even overall, but the result split cleanly:

* the **first** signal of the day earned +8.7R, the second lost 5.5R;
* entries before **12:00** earned +7.0R, entries after lost 3.8R;
* days that **opened flat** (less than 0.2 % from the previous close) lost
  in both halves of the sample; days with a real gap earned;
* BANKNIFTY lost on every split.

So the decision maker takes only the day's first signal, only before
12:00, only on a day with a gap, only on NIFTY. These are measured on one
period (in-sample): :func:`gated_backtest` re-runs the measurement so it can
be checked on new data at any time.
"""

import datetime as dt
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from indtrader.core import clock


@dataclass(frozen=True)
class DecisionRules:
    symbols: Tuple[str, ...]
    last_entry: dt.time
    min_gap_pct: float
    trades_per_day: int
    context_refresh_min: int

    @classmethod
    def from_config(cls, cfg: dict) -> "DecisionRules":
        raw = cfg["decision"]
        return cls(tuple(s.upper() for s in raw["symbols"]), clock.parse_hhmm(raw["last_entry"]), float(raw["min_gap_pct"]),
                   int(raw["trades_per_day"]), int(raw["context_refresh_min"]))

    def gap_ok(self, gap_pct: Optional[float]) -> bool:
        return gap_pct is not None and abs(gap_pct) >= self.min_gap_pct

    def in_window(self, entry_time: str) -> bool:
        return clock.parse_hhmm(entry_time) <= self.last_entry

    def gap_levels(self, prev_close: float) -> Tuple[float, float]:
        """The opens that make the day tradeable: at or above the first, or at or below the second."""
        return prev_close * (1 + self.min_gap_pct / 100), prev_close * (1 - self.min_gap_pct / 100)


def gap_pct(prev_close: Optional[float], day_open: Optional[float]) -> Optional[float]:
    return round((day_open / prev_close - 1) * 100, 3) if prev_close and day_open else None


def gated_backtest(trades: List[dict], gaps: Dict[str, Optional[float]], rules: DecisionRules) -> Dict[str, List[dict]]:
    """Split the live engine's backtest trades into the ones the rules take and the ones they skip (with why)."""
    taken: List[dict] = []
    skipped: List[dict] = []
    signals_per_day: Dict[str, int] = {}
    for trade in trades:
        day = trade["date"]
        signals_per_day[day] = signals_per_day.get(day, 0) + 1
        reason = skip_reason(rules, signals_per_day[day], trade["time"], gaps.get(day))
        if reason:
            skipped.append(dict(trade, skip=reason))
        else:
            taken.append(trade)
    return {"taken": taken, "skipped": skipped}


def skip_reason(rules: DecisionRules, signal_number: int, entry_time: str, gap: Optional[float]) -> Optional[str]:
    """Why the rules pass on a signal, or None when they take it. Shared by the live decision and the backtest."""
    if signal_number > rules.trades_per_day:
        return "one trade a day (this is signal %d)" % signal_number
    if not rules.in_window(entry_time):
        return "after %s (late entries lost in the test)" % rules.last_entry.strftime("%H:%M")
    if not rules.gap_ok(gap):
        return "flat open (%s%% from the previous close; flat days lost in the test)" % ("%+.2f" % gap if gap is not None else "?")
    return None
