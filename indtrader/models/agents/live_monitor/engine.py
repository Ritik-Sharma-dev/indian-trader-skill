"""The live engine: a state machine fed one closed bar at a time.

The state is a plain JSON-able dict so it survives between ticks
(``workspace/state/live-<SYMBOL>-<date>.json``). Feeding the bars one tick
at a time gives exactly the trades of feeding the whole day at once: the
tests prove it, so a replay of a past day is what the live monitor would
have said.
"""

import datetime as dt
import logging
from typing import List, Optional

from indtrader.core.formatting import num
from indtrader.models.agents.live_monitor.strategy import STEP, LiveStrategy, snapshot

log = logging.getLogger(__name__)


def new_state(symbol: str, day: dt.date, regime: Optional[str] = None) -> dict:
    return {"symbol": symbol, "date": day.isoformat(), "regime": regime, "last_bar": None, "trade": None, "trades": [],
            "or_break": None, "level_done": {"long": False, "short": False}, "orb_done": False,
            "cooldown_until": None, "events": []}


class LiveEngine:
    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self.strategy = LiveStrategy(cfg)

    @staticmethod
    def close_trade(state: dict, reason: str, price: float, when: dt.datetime) -> dict:
        trade = state["trade"]
        points = (trade["entry"] - price) if trade["side"] == "short" else (price - trade["entry"])
        trade.update({"exit": round(price, 2), "exit_time": when.strftime("%H:%M"), "exit_reason": reason,
                      "points": round(points, 2), "r": round(points / trade["risk"], 2)})
        state["trades"].append(trade)
        state["trade"] = None
        state["cooldown_until"] = (when + 2 * STEP).isoformat()
        log.info("%s live exit %s (%s) at %.2f: %+.2f pts", state["symbol"], trade["side"], reason, price, points)
        return trade

    def process(self, state: dict, prev: List[dict], session: List[dict], live: bool = False,
                now: Optional[dt.datetime] = None) -> List[dict]:
        """Feed every bar that closed since ``state["last_bar"]``; returns events."""
        events: List[dict] = []
        start = 0
        if state["last_bar"]:
            start = next((k + 1 for k, b in enumerate(session) if b["t"].isoformat() == state["last_bar"]), 0)
        for i in range(start, len(session)):
            snap = snapshot(prev, session, i)
            self._track_opening_break(state, session[i], snap)
            if state["trade"]:
                events += self._manage(state, session, i, snap)
            if not state["trade"]:
                events += self._look_for_entry(state, session, i, snap, live, now)
            state["last_bar"] = session[i]["t"].isoformat()
            state["last_snap"] = {k: (v.isoformat() if isinstance(v, dt.datetime) else v) for k, v in snap.items() if k != "pivots"}
            state["last_snap"]["pivots"] = snap.get("pivots")
        return events

    @staticmethod
    def _track_opening_break(state: dict, bar: dict, snap: dict) -> None:
        if snap["or_high"] is None or state["or_break"] is not None:
            return
        if bar["c"] > snap["or_high"]:
            state["or_break"] = "up"
        elif bar["c"] < snap["or_low"]:
            state["or_break"] = "down"

    def _manage(self, state: dict, session: List[dict], i: int, snap: dict) -> List[dict]:
        result = self.strategy.manage(state["trade"], session, i, snap)
        if not result:
            return []
        reason, price = result
        if reason == "move-stop":
            kind = "breakeven" if price == state["trade"]["entry"] else "trailing"
            return [{"type": "UPDATE", "time": snap["close_t"], "text": "move stop to %s (%s)" % (num(price), kind)}]
        trade = self.close_trade(state, reason, price, snap["close_t"])
        return [{"type": "EXIT", "time": snap["close_t"], "trade": trade,
                 "text": "EXIT %s (%s) at %s: %+.2f points (%+.2fR)" % (trade["side"].upper(), reason, num(price), trade["points"], trade["r"])}]

    def _look_for_entry(self, state: dict, session: List[dict], i: int, snap: dict, live: bool,
                        now: Optional[dt.datetime]) -> List[dict]:
        signal = self.strategy.find_entry(state, session, i, snap)
        if not signal:
            return []
        if signal["setup"] == "orb":
            state["orb_done"] = True
        if signal["setup"] == "level":
            state["level_done"][signal["side"]] = True
        if live and now is not None and (now - snap["close_t"]) > STEP * 1.2:
            log.info("%s live signal %s %s at %s is stale: not taken", state["symbol"], signal["side"], signal["setup"], signal["time"])
            return [{"type": "INFO", "time": snap["close_t"],
                     "text": "missed %s %s signal at %s (more than one bar old): not taken" % (signal["side"], signal["setup"], signal["time"])}]
        state["trade"] = signal
        log.info("%s live entry %s (%s) at %.2f, stop %.2f, target %.2f", state["symbol"], signal["side"], signal["setup"],
                 signal["entry"], signal["stop"], signal["target"])
        return [{"type": "ENTRY", "time": snap["close_t"], "trade": signal,
                 "text": "ENTRY %s (%s) at %s: %s. Stop %s, target %s (risk %s pts)" % (
                     signal["side"].upper(), signal["setup"], num(signal["entry"]), signal["why"], num(signal["stop"]),
                     num(signal["target"]), num(signal["risk"]))}]
