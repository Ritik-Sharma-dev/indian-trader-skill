"""The live monitor: data, persistence, ticks, replays and backtests.

A tick processes every 5-minute bar closed since the last tick, maps a new
entry to the ATM option of the nearest expiry, and checks the live quote
between bars so a touched stop or target is reported at once. A signal more
than one bar old is reported as missed and never chased.

State: ``workspace/state/live-<SYMBOL>-<date>.json``; event log:
``workspace/live/<SYMBOL>-<date>.log``; latest tick: ``live/latest-<SYMBOL>.json``.
A tick returns data (:class:`Tick`); presenting it is the views' job
(:mod:`indtrader.views.live`). It never places an order.
"""

import datetime as dt
import logging
import os
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from indtrader.core import clock, settings
from indtrader.core.context import AppContext
from indtrader.core.errors import DataError, IndianTraderError
from indtrader.core.formatting import num
from indtrader.core.storage import read_json, write_json
from indtrader.models.agents.live_monitor.engine import LiveEngine, new_state
from indtrader.models.agents.live_monitor.strategy import STEP, daily_regime
from indtrader.models.analytics.option_chain import OptionChainAnalyzer, OptionChainService, pick_strike
from indtrader.models.data import bars as barlib
from indtrader.models.data.symbols import safe_name
from indtrader.models.trading.planner import option_levels

log = logging.getLogger(__name__)


@dataclass
class Tick:
    """The result of one live check. ``state`` is None when the market is not open."""

    symbol: str
    time: dt.datetime
    events: List[dict]
    state: Optional[dict]
    quote: Optional[dict]
    market: dict

    @property
    def is_open(self) -> bool:
        return self.state is not None


def serialise_events(events: List[dict]) -> List[dict]:
    return [{"type": e["type"], "time": e["time"].isoformat(), "text": e["text"]} for e in events]


def stats(trades: List[dict]) -> Optional[dict]:
    if not trades:
        return None
    wins = [t for t in trades if t["points"] > 0]
    r_values = [t["r"] for t in trades]
    equity = peak = drawdown = 0.0
    for r in r_values:
        equity += r
        peak = max(peak, equity)
        drawdown = min(drawdown, equity - peak)
    by_setup: Dict[Tuple[str, str], List[float]] = {}
    for trade in trades:
        by_setup.setdefault((trade["setup"], trade["side"]), []).append(trade["r"])
    return {"trades": len(trades), "wins": len(wins), "win_rate": len(wins) / len(trades),
            "total_r": round(sum(r_values), 2), "avg_r": round(sum(r_values) / len(r_values), 3), "max_dd_r": round(drawdown, 2),
            "total_points": round(sum(t["points"] for t in trades), 1),
            "by_setup": {"%s %s" % key: {"n": len(v), "avg_r": round(sum(v) / len(v), 2), "total_r": round(sum(v), 2)}
                         for key, v in by_setup.items()},
            "exits": {reason: sum(1 for t in trades if t["exit_reason"] == reason) for reason in sorted({t["exit_reason"] for t in trades})}}


class LiveMonitor:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.market = ctx.market
        self.engine = LiveEngine(ctx.cfg)

    # -- persistence ------------------------------------------------------------------

    @staticmethod
    def state_path(symbol: str, day: dt.date) -> str:
        return settings.path("state", "live-%s-%s.json" % (safe_name(symbol), day.isoformat()))

    @staticmethod
    def append_log(symbol: str, day: dt.date, text: str) -> None:
        with open(settings.path("live", "%s-%s.log" % (safe_name(symbol), day.isoformat())), "a", encoding="utf-8") as fh:
            fh.write(text + "\n")

    def load_state(self, symbol: str, day: dt.date) -> Optional[dict]:
        return read_json(self.state_path(symbol, day))

    def reset(self, symbol: str, day: dt.date) -> None:
        path = self.state_path(symbol, day)
        if os.path.exists(path):
            os.remove(path)
            log.info("live state for %s on %s cleared", symbol, day)

    # -- data ---------------------------------------------------------------------------

    def load_bars(self, symbol: str, now: dt.datetime) -> Tuple[List[dict], List[dict]]:
        """(the previous two sessions, today's closed bars)."""
        rng = "5d" if (now.date() == clock.now_ist().date() and not self.market.offline) else "60d"
        _, bars = self.market.candles(symbol, "5m", rng)
        sessions = barlib.by_session(barlib.closed(bars, now, "5m"))
        prev_days = [d for d in sorted(sessions) if d < now.date()][-2:]
        return [b for d in prev_days for b in sessions[d]], sessions.get(now.date(), [])

    def regime_for(self, symbol: str, day: dt.date) -> Optional[str]:
        try:
            _, daily = self.market.candles(symbol, "1d", "6mo")
        except IndianTraderError as exc:
            log.warning("no daily bars for %s: %s", symbol, exc)
            return None
        daily = self.market.fill_daily_holes(symbol, [b for b in daily if b["t"].date() < day], clock.at(day, clock.OPEN))
        return daily_regime([b["c"] for b in daily if b["t"].date() < day])

    def option_for(self, symbol: str, trade: dict, now: dt.datetime) -> dict:
        """The ATM option of the nearest expiry for an entry, with premium levels."""
        try:
            chain = OptionChainService(self.market).fetch(symbol, now, "near")
            lot = self.market.lot_size(symbol)
            analysis = OptionChainAnalyzer(self.ctx.cfg).analyze(chain, now, lot)
            kind = "PE" if trade["side"] == "short" else "CE"
            pick = pick_strike(analysis, kind, "atm")
            levels = option_levels(pick, {"entry": trade["entry"], "stop": trade["init_stop"], "target": trade["target"]},
                                   now, 30, self.ctx.cfg, chain["expiry"])
            return {"tradingsymbol": "%s %s %s %s" % (symbol, chain["expiry"].strftime("%d%b%y").upper(), num(pick["strike"], 0), kind),
                    "lot": lot, "premium_now": pick["premium"], "bid": pick["bid"], "ask": pick["ask"],
                    "premium_stop": levels["stop"], "premium_target": levels["target"],
                    "risk_per_lot": round((pick["premium"] - levels["stop"]) * lot, 2),
                    "reward_per_lot": round((levels["target"] - pick["premium"]) * lot, 2)}
        except IndianTraderError as exc:
            log.warning("option lookup for the %s entry failed: %s", symbol, exc)
            return {"error": str(exc)}

    # -- live ----------------------------------------------------------------------------

    def tick(self, symbol: str, now: Optional[dt.datetime] = None) -> Tick:
        """One live check: the new events, the engine state and the live quote."""
        now = now or self.ctx.now
        market_state = clock.market_status(now)
        if market_state["state"] != "open":
            return Tick(symbol, now, [], None, None, market_state)
        state = self.load_state(symbol, now.date()) or new_state(symbol, now.date(), self.regime_for(symbol, now.date()))
        prev, session = self.load_bars(symbol, now)
        events = self.engine.process(state, prev, session, live=True, now=now)
        quote = None
        if not self.ctx.replaying:
            try:
                quote = self.market.quote(symbol)
            except IndianTraderError as exc:
                log.info("no live quote for %s: %s", symbol, exc)
        for item in events:
            if item["type"] == "ENTRY":
                item["trade"]["option"] = state["trade"]["option"] = (
                    {"error": "a replay of a past time has no option prices from that moment"} if self.ctx.replaying
                    else self.option_for(symbol, state["trade"], now))
        events += self._check_live_price(state, quote, now)
        state["events"] += serialise_events(events)
        write_json(self.state_path(symbol, now.date()), state)
        for item in events:
            self.append_log(symbol, now.date(), "%s %-6s %s" % (item["time"].strftime("%H:%M"), item["type"], item["text"]))
        write_json(settings.path("live", "latest-%s.json" % safe_name(symbol)),
                   {"time": now.isoformat(timespec="seconds"), "state": state, "events": serialise_events(events)})
        log.debug("%s tick at %s: %d event(s)", symbol, now.strftime("%H:%M"), len(events))
        return Tick(symbol, now, events, state, quote, market_state)

    def _check_live_price(self, state: dict, quote: Optional[dict], now: dt.datetime) -> List[dict]:
        """Between bars: has the live price already reached the stop or target?"""
        trade = state["trade"]
        if not (trade and quote and quote.get("price")):
            return []
        price = quote["price"]
        if trade["side"] == "short":
            hit = "stop (live price)" if price >= trade["stop"] else "target (live price)" if price <= trade["target"] else None
        else:
            hit = "stop (live price)" if price <= trade["stop"] else "target (live price)" if price >= trade["target"] else None
        if not hit:
            return []
        done = self.engine.close_trade(state, hit, price, now)
        return [{"type": "EXIT", "time": now, "trade": done,
                 "text": "EXIT %s (%s) at %s: %+.2f points (%+.2fR)" % (done["side"].upper(), hit, num(price), done["points"], done["r"])}]

    def run(self, symbol: str, every: int, until: dt.datetime, simulated: bool, report: Callable[[Tick], None]) -> None:
        """Tick every ``every`` seconds until ``until`` or the close, handing each tick to ``report``."""
        moment = self.ctx.now
        while True:
            report(self.tick(symbol, moment))
            if moment >= until or clock.market_status(moment)["state"] == "closed":
                return
            if simulated:
                moment += dt.timedelta(seconds=every)
            else:
                time.sleep(every)
                moment = clock.now_ist()

    # -- history ---------------------------------------------------------------------------

    def replay_day(self, symbol: str, day: dt.date) -> Tuple[dict, List[dict]]:
        """The whole day bar by bar with the live engine (no look-ahead)."""
        _, bars = self.market.candles(symbol, "5m", "60d")
        sessions = barlib.by_session(bars)
        if day not in sessions:
            raise DataError("no 5-minute bars for %s on %s" % (symbol, day))
        prev = [b for d in [d for d in sorted(sessions) if d < day][-2:] for b in sessions[d]]
        state = new_state(symbol, day, self.regime_for(symbol, day))
        events = self.engine.process(state, prev, sessions[day])
        if state["trade"]:                                  # data ended before square-off
            last = sessions[day][-1]
            self.engine.close_trade(state, "end of data", last["c"], last["t"] + STEP)
        return state, events

    def backtest(self, symbol: str, sessions: int = 40) -> Tuple[List[dt.date], List[dict]]:
        _, bars = self.market.candles(symbol, "5m", "60d")
        days = [d for d, s in sorted(barlib.by_session(bars).items()) if len(s) >= 70][2:][-sessions:]
        trades = []
        for day in days:
            state, _ = self.replay_day(symbol, day)
            trades += [dict(t, date=day.isoformat()) for t in state["trades"]]
        log.info("live backtest %s: %d trades over %d sessions", symbol, len(trades), len(days))
        return days, trades
