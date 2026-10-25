"""The decision maker: one clear instruction for intraday F&O, now.

It sits on top of the live engine (which finds setups on closed 5-minute
candles) and the day's context (global markets, option chain, FII
positioning, trend, the open), and answers with one action:

    BUY CALL / BUY PUT   the day's signal passed every rule: buy now (LIMIT, 1 lot)
    HOLD                 in the trade: the stop, target and square-off time
    EXIT                 sell the option now (stop, target, trend turned, 15:15)
    WAIT                 no signal yet: the exact triggers that would start a trade
    NO TRADE             the rules say stand aside today, and why
    DONE                 today's one trade is finished

Before the open it gives the day plan: which opens make the day tradeable,
the lean from the research, the levels and the triggers to watch.

Only the engine's first signal of the day counts. A signal the user could not
act on in time is reported as missed and never chased. The decision state is
kept in ``workspace/state/decision-<SYMBOL>-<date>.json``. Nothing here can
place an order.
"""

import datetime as dt
import logging
from dataclasses import asdict, dataclass, field
from typing import List, Optional

from indtrader.core import clock, settings
from indtrader.core.context import AppContext
from indtrader.core.errors import IndianTraderError, ValidationError
from indtrader.core.formatting import inr, num
from indtrader.core.storage import read_json, write_json
from indtrader.models.agents.decision_maker.context import DayContext, confidence
from indtrader.models.agents.decision_maker.journal import DecisionJournal
from indtrader.models.agents.decision_maker.rules import DecisionRules, gap_pct, gated_backtest, skip_reason
from indtrader.models.agents.live_monitor.monitor import LiveMonitor, stats
from indtrader.models.agents.risk_manager.status import daily_stop
from indtrader.models.data import bars as barlib
from indtrader.models.data.symbols import safe_name
from indtrader.models.trading.charges import charges

log = logging.getLogger(__name__)

ACTIONS = ("BUY CALL", "BUY PUT", "HOLD", "EXIT", "WAIT", "NO TRADE", "DONE")


@dataclass
class Decision:
    symbol: str
    time: str
    action: str
    headline: str
    confidence: Optional[str] = None
    price: Optional[float] = None
    why: List[str] = field(default_factory=list)
    do: List[str] = field(default_factory=list)
    triggers: List[str] = field(default_factory=list)
    trade: Optional[dict] = None
    context: Optional[dict] = None

    def as_dict(self) -> dict:
        return asdict(self)


def _signals(events: List[dict]) -> List[dict]:
    """The engine's signals today, in order: entries and the ones it reported as missed."""
    return [e for e in events if e["type"] == "ENTRY" or (e["type"] == "INFO" and e["text"].startswith("missed"))]


def _side_word(side: str) -> str:
    return "PUT" if side == "short" else "CALL"


class Decider:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.rules = DecisionRules.from_config(ctx.cfg)
        self.monitor = LiveMonitor(ctx)

    # -- state ------------------------------------------------------------------------------

    @staticmethod
    def _path(symbol: str, day: dt.date) -> str:
        return settings.path("state", "decision-%s-%s.json" % (safe_name(symbol), day.isoformat()))

    def _context(self, memory: dict, symbol: str, now: dt.datetime, regime: Optional[str], gap: Optional[float]) -> dict:
        """The day context, re-read at most every ``context_refresh_min`` minutes (or when the gap becomes known)."""
        cached = memory.get("context")
        if cached:
            age = (now - dt.datetime.fromisoformat(cached["time"])).total_seconds() / 60
            gap_known = any(v["name"] == "open" for v in cached["votes"])
            if 0 <= age < self.rules.context_refresh_min and (gap_known or gap is None):
                return cached
        memory["context"] = DayContext(self.ctx).collect(symbol, now, regime, gap, self.rules.min_gap_pct)
        return memory["context"]

    def _check_symbol(self, symbol: str) -> None:
        if symbol not in self.rules.symbols:
            raise ValidationError("%s is not traded by the decision rules (allowed: %s; BANKNIFTY lost in every test split). "
                                  "Use `live tick %s` for raw signals." % (symbol, ", ".join(self.rules.symbols), symbol))

    # -- the day plan -------------------------------------------------------------------------

    def plan(self, symbol: str) -> Decision:
        """Before or during the session: is today tradeable, the lean, the levels and the triggers."""
        symbol = symbol.upper()
        self._check_symbol(symbol)
        now = self.ctx.now
        day = now.date() if clock.is_trading_day(now.date()) and now.time() < clock.CLOSE else clock.next_trading_day(now.date())
        prev, session = self.monitor.load_bars(symbol, now if day == now.date() else clock.at(day, clock.OPEN))
        if not prev:
            raise IndianTraderError("no previous session bars for %s" % symbol)
        last_day = [b for b in prev if b["t"].date() == prev[-1]["t"].date()]
        pdh, pdl, pdc = max(b["h"] for b in last_day), min(b["l"] for b in last_day), last_day[-1]["c"]
        today = session if day == now.date() else []
        gap = gap_pct(pdc, today[0]["o"]) if today else None
        regime = self.monitor.regime_for(symbol, day)
        memory = read_json(self._path(symbol, day), {}) or {}
        context = self._context(memory, symbol, now, regime, gap)
        write_json(self._path(symbol, day), memory)

        up, down = self.rules.gap_levels(pdc)
        lean = context["lean"]
        why = ["previous close %s, high %s, low %s" % (num(pdc), num(pdh), num(pdl))]
        why += [v["detail"] for v in context["votes"]]
        if gap is None:
            action, headline = "WAIT", ("Plan for %s: trade only if NIFTY opens at or above %s or at or below %s "
                                        "(a %.1f%% gap). A flat open means no trade today." % (day.strftime("%a %d %b"), num(up), num(down),
                                                                                              self.rules.min_gap_pct))
        elif not self.rules.gap_ok(gap):
            action, headline = "NO TRADE", "Flat open (%+.2f%%): the rules stand aside today (flat days lost in the test)." % gap
        else:
            action, headline = "WAIT", "Opened %+.2f%%: today is tradeable. Wait for the first signal after 09:30." % gap
        lean_text = {"BULLISH": "CALL signals get HIGH confidence, PUT signals LOW", "BEARISH": "PUT signals get HIGH confidence, CALL signals LOW",
                     "MIXED": "no side favoured: both sides MEDIUM"}[lean["label"]]
        why.append("research lean %s (%+d): %s" % (lean["label"], lean["score"], lean_text))
        triggers = self._triggers(today, pdh, pdl)
        levels = context["levels"]
        if levels.get("resistance") or levels.get("support"):
            why.append("option walls: resistance %s, support %s, max pain %s" % (
                "/".join(num(s, 0) for s in levels.get("resistance", [])), "/".join(num(s, 0) for s in levels.get("support", [])),
                num(levels.get("max_pain"), 0)))
        do = ["Trade window 09:30-%s, one trade, 1 lot, LIMIT orders, square off by %s." % (
            self.rules.last_entry.strftime("%H:%M"), self.ctx.cfg["square_off_by"]),
            "Run `decide now NIFTY` every 3-5 minutes from 09:30 (or the /in-decide loop) and act only on BUY / EXIT."]
        return Decision(symbol, now.isoformat(timespec="minutes"), action, headline, why=why + context["notes"], do=do,
                        triggers=triggers, context=context)

    def _triggers(self, session: List[dict], pdh: float, pdl: float) -> List[str]:
        if len(session) >= 3:
            or_high, or_low = max(b["h"] for b in session[:3]), min(b["l"] for b in session[:3])
            return ["BUY PUT  when a 5-min candle CLOSES below the opening-range low %s (or below the previous low %s)" % (num(or_low), num(pdl)),
                    "BUY CALL when a 5-min candle CLOSES above the opening-range high %s (or above the previous high %s)" % (num(or_high), num(pdh)),
                    "after a break: BUY in the break direction when price pulls back to VWAP and the candle closes back the right way"]
        return ["at 09:30 the opening range (09:15-09:30 high and low) is set",
                "BUY PUT  on the first 5-min CLOSE below the opening-range low (or the previous low %s)" % num(pdl),
                "BUY CALL on the first 5-min CLOSE above the opening-range high (or the previous high %s)" % num(pdh)]

    # -- the live decision ------------------------------------------------------------------------

    def decide(self, symbol: str) -> Decision:
        symbol = symbol.upper()
        self._check_symbol(symbol)
        now = self.ctx.now
        status = clock.market_status(now)
        if status["state"] != "open":
            plan = self.plan(symbol)
            if now.time() >= clock.CLOSE and clock.is_trading_day(now.date()):
                plan.headline = "Market closed for today. " + plan.headline
            return plan

        events = self.monitor.tick(symbol, now).events
        state = self.monitor.load_state(symbol, now.date())
        snap = state.get("last_snap") or {}
        gap = gap_pct(snap.get("pdc"), snap.get("day_open"))
        memory = read_json(self._path(symbol, now.date()), {}) or {}
        context = self._context(memory, symbol, now, state.get("regime"), gap)
        fresh = {(e["type"], e["time"].isoformat()[:16]) for e in events}       # what happened in this tick
        decision = self._judge(symbol, now, state, snap, gap, context, memory, fresh)
        decision.context = context
        memory["last"] = {"time": decision.time, "action": decision.action, "headline": decision.headline}
        write_json(self._path(symbol, now.date()), memory)
        if not self.ctx.pinned:                     # only real-time decisions go in the forward record
            DecisionJournal().record(symbol, now.date(), decision, gap, context)
        log.info("%s decision at %s: %s", symbol, now.strftime("%H:%M"), decision.action)
        return decision

    def _judge(self, symbol: str, now: dt.datetime, state: dict, snap: dict, gap: Optional[float], context: dict,
               memory: dict, fresh: set) -> Decision:
        stamp, price = now.isoformat(timespec="minutes"), snap.get("close")
        signals = _signals(state["events"])
        base_why = [v["detail"] for v in context["votes"]] + context["notes"]
        if not signals:
            if now.time() > self.rules.last_entry:
                return Decision(symbol, stamp, "NO TRADE", "No signal before %s: no trade today (late entries lost in the test)."
                                % self.rules.last_entry.strftime("%H:%M"), price=price, why=base_why)
            if gap is not None and not self.rules.gap_ok(gap):
                return Decision(symbol, stamp, "NO TRADE", "Flat open (%+.2f%%): stand aside today." % gap, price=price, why=base_why)
            triggers = self._triggers_from_snap(snap)
            return Decision(symbol, stamp, "WAIT", "No signal yet. Watch the triggers; entries until %s."
                            % self.rules.last_entry.strftime("%H:%M"), price=price, why=base_why, triggers=triggers)

        first = signals[0]
        first_time = first["time"][11:16]
        if first["type"] == "INFO":
            words = first["text"].split()            # "missed short orb signal at 09:55 ..."
            return Decision(symbol, stamp, "DONE", "Today's signal (%s, %s) came at %s and was missed: never chase it. No more trades today."
                            % (_side_word(words[1]), words[2], first_time), price=price, why=base_why)
        trade = self._first_trade(state, first_time)
        reason = skip_reason(self.rules, 1, first_time, gap)
        if reason:
            return Decision(symbol, stamp, "NO TRADE", "The %s signal at %s is skipped: %s. No trade today." % (
                _side_word(trade["side"]) if trade else "", first_time, reason), price=price, why=base_why, trade=trade)
        if trade is None:
            return Decision(symbol, stamp, "WAIT", "Signal at %s, trade details not found; check `live status NIFTY`." % first_time, price=price)

        side_word = _side_word(trade["side"])
        blocked = memory.get("risk_block") or (None if memory.get("taken") else daily_stop(self.ctx.cfg, now)) or self._risk_block(trade)
        if blocked:
            memory["risk_block"] = blocked
            return Decision(symbol, stamp, "NO TRADE", "The %s signal at %s is skipped: %s" % (side_word, first_time, blocked),
                            price=price, why=base_why, trade=trade,
                            do=["To take trades like this, set max_loss_per_trade in Indian Trader Skill/workspace/config.json "
                                "to at least the risk shown (or trade a smaller instrument)."])
        level = confidence(context["votes"], trade["side"])
        memory.setdefault("taken", {"time": first_time, "side": trade["side"], "confidence": level})
        why = ["%s at %s: %s" % (trade["setup"].upper(), first_time, trade["why"]),
               "gap %+.2f%% (tradeable), inside the %s entry window, first signal of the day" % (gap, self.rules.last_entry.strftime("%H:%M"))]
        why += base_why
        option = trade.get("option") or {}
        if "exit_reason" in trade:
            exit_new = ("EXIT", "%sT%s" % (state["date"], trade["exit_time"])) in fresh
            result = "%+.1f points (%+.2fR)" % (trade["points"], trade["r"])
            if exit_new:
                return Decision(symbol, stamp, "EXIT", "SELL the %s now: %s at %s, %s." % (side_word, trade["exit_reason"], num(trade["exit"]), result),
                                level, price, why, ["Sell at the bid with a LIMIT order now.", "No more trades today."], trade=trade)
            return Decision(symbol, stamp, "DONE", "Today's trade is finished: %s %s at %s, %s. No more trades today." % (
                side_word, trade["exit_reason"], trade["exit_time"], result), level, price, why, trade=trade)

        entry_new = ("ENTRY", first["time"][:16]) in fresh
        do = []
        if option and not option.get("error"):
            do.append("BUY %s, 1 lot (%d), LIMIT about %s (bid %s / ask %s)." % (option["tradingsymbol"], option["lot"], num(option["premium_now"]),
                                                                              num(option["bid"]), num(option["ask"])))
            do.append("Premium stop about %s, premium target about %s (risk %s, reward %s per lot)." % (
                num(option["premium_stop"]), num(option["premium_target"]), num(option["risk_per_lot"], 0), num(option["reward_per_lot"], 0)))
        else:
            do.append("Option: pick the ATM %s of the nearest expiry yourself (%s)." % (side_word, option.get("error", "no option data")))
        do.append("NIFTY stop %s, target %s. Exit at whichever comes first, or at %s at the latest." % (
            num(trade["stop"]), num(trade["target"]), self.ctx.cfg["square_off_by"]))
        if entry_new:
            do.insert(0, "Confirm in the broker app that the %s candle closed %s %s." % (
                first_time, "below" if trade["side"] == "short" else "above", num(trade["entry"])))
            return Decision(symbol, stamp, "BUY " + side_word, "BUY %s now (%s confidence)." % (side_word, level), level, price, why, do, trade=trade)
        moved = " (stop moved to %s)" % num(trade["stop"]) if trade["stop"] != trade["init_stop"] else ""
        points = (trade["entry"] - price) if trade["side"] == "short" else (price - trade["entry"])
        return Decision(symbol, stamp, "HOLD", "HOLD the %s: %+.1f points (%+.2fR) since %s%s." % (
            side_word, points, points / trade["risk"], first_time, moved), level, price, why, do[-1:], trade=trade)

    def _risk_block(self, trade: dict) -> Optional[str]:
        """The risk check: one lot's loss at the premium stop, plus round-trip charges, against max_loss_per_trade."""
        option = trade.get("option") or {}
        if option.get("error") or option.get("risk_per_lot") is None:
            return None                                     # no premium levels: the user sizes it with /in-budget
        cost = charges("option", option["premium_now"] * option["lot"], option["premium_stop"] * option["lot"], self.ctx.cfg)["total"]
        risk = option["risk_per_lot"] + cost
        limit = self.ctx.cfg["max_loss_per_trade"]
        if risk > limit:
            return "one lot risks %s at the premium stop (charges included), over your max loss of %s per trade." % (inr(risk, 0), inr(limit, 0))
        return None

    @staticmethod
    def _first_trade(state: dict, entry_time: str) -> Optional[dict]:
        for trade in state["trades"] + ([state["trade"]] if state["trade"] else []):
            if trade["time"] == entry_time:
                return trade
        return None

    @staticmethod
    def _triggers_from_snap(snap: dict) -> List[str]:
        out = []
        if snap.get("or_low") is not None:
            out.append("BUY PUT  when a 5-min candle CLOSES below %s (opening-range low)" % num(snap["or_low"]))
            out.append("BUY CALL when a 5-min candle CLOSES above %s (opening-range high)" % num(snap["or_high"]))
        if snap.get("pdl") is not None:
            out.append("also: a close below the previous low %s with a bearish bias, or above the previous high %s with a bullish bias"
                       % (num(snap["pdl"]), num(snap["pdh"])))
        return out or ["the opening range is set at 09:30"]

    # -- the record ---------------------------------------------------------------------------------

    def backtest(self, symbol: str, sessions: int = 58) -> dict:
        """The live engine's backtest split by the decision rules, with the record of each part."""
        symbol = symbol.upper()
        days, trades = self.monitor.backtest(symbol, sessions)
        _, bars = self.ctx.market.candles(symbol, "5m", "60d")
        by_day = barlib.by_session(bars)
        ordered = sorted(by_day)
        gaps = {}
        for day in days:
            index = ordered.index(day)
            gaps[day.isoformat()] = gap_pct(by_day[ordered[index - 1]][-1]["c"], by_day[day][0]["o"]) if index else None
        split = gated_backtest(trades, gaps, self.rules)
        reasons = {}
        for trade in split["skipped"]:
            key = trade["skip"].split(" (")[0]
            reasons.setdefault(key, []).append(trade)
        return {"symbol": symbol, "sessions": len(days), "from": days[0].isoformat() if days else None,
                "to": days[-1].isoformat() if days else None, "all": stats(trades), "taken": stats(split["taken"]),
                "skipped": {k: stats(v) for k, v in reasons.items()}, "trades": split["taken"]}
