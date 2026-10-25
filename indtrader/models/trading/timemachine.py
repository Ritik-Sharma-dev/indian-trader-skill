"""Time Machine: replays a planned trade before a rupee is risked.

1. Data: 60 days of 5-minute bars of the underlying. Only FULL sessions
   before the plan's date count: 75 bars, 09:15 to 15:30 IST.
2. Pool: for each bar slot 1..74, every past session's bar as ratios to
   the previous close, (open, high, low, close) / previous close, so each
   slot keeps its own time-of-day character (the open is wilder than noon).
3. A replay starts at the entry price at the entry time and walks to
   ``square_off_by``. Bar i draws slot j = i + randint(-window, window) and one
   past bar from that slot, scaled to the current price. The stop is checked
   before the target inside a bar; a bar that OPENS past the stop fills at
   its open (a gap), not at the stop.
4. Outcomes: target first, stop first, or neither (closed at square-off).
5. Options: the exit premium is Black-Scholes at the plan's IV with the time
   left at the exit bar (theta included), anchored to the entry premium.
6. History: the same opening-range rule re-run on every past session.

Seeded (default 19): the numbers can be repeated. A replay of the last 60
days, not a forecast.
"""

import datetime as dt
import logging
import random
from typing import Dict, List, Optional, Sequence, Set, Tuple

from indtrader.core import clock
from indtrader.core.errors import DataError, ValidationError
from indtrader.core.formatting import inr
from indtrader.models.analytics import blackscholes as bs
from indtrader.models.analytics import indicators as ind
from indtrader.models.data import bars as barlib
from indtrader.models.trading.charges import charges
from indtrader.models.trading.planner import levels

log = logging.getLogger(__name__)

BARS = 75     # 09:15 .. 15:25 bar starts
Pool = List[List[Tuple[float, float, float, float]]]


def slot_of(t: dt.time) -> int:
    return int(((t.hour * 60 + t.minute) - (9 * 60 + 15)) // 5)


def bar_close_time(day: dt.date, slot: int) -> dt.datetime:
    return clock.at(day, clock.OPEN) + dt.timedelta(minutes=5 * (slot + 1))


def full_sessions(bars: List[dict], before: dt.date) -> List[List[dict]]:
    return [session for day, session in sorted(barlib.by_session(bars).items())
            if day < before and len(session) == BARS and slot_of(session[0]["t"]) == 0]


def build_pool(sessions: Sequence[List[dict]]) -> Pool:
    pool: Pool = [[] for _ in range(BARS)]
    for session in sessions:
        for i in range(1, BARS):
            prev_close, bar = session[i - 1]["c"], session[i]
            pool[i].append((bar["o"] / prev_close, bar["h"] / prev_close, bar["l"] / prev_close, bar["c"] / prev_close))
    return pool


def simulate(pool: Pool, rnd: random.Random, entry: float, stop: float, target: float, long: bool, first_slot: int,
             last_slot: int, window: int = 2, checkpoints: Optional[Set[int]] = None) -> Tuple[str, float, int, Dict[int, float]]:
    """One replay: (outcome, exit price, exit slot, prices at checkpoints)."""
    price = entry
    marks: Dict[int, float] = {}
    for slot in range(first_slot, last_slot + 1):
        drawn = min(BARS - 1, max(1, slot + rnd.randint(-window, window)))
        o, h, l, c = rnd.choice(pool[drawn])            # noqa: E741
        bar_open, bar_high, bar_low, bar_close = price * o, price * h, price * l, price * c
        if long:
            if bar_low <= stop:
                return "stop", (bar_open if bar_open < stop else stop), slot, marks
            if bar_high >= target:
                return "target", (bar_open if bar_open > target else target), slot, marks
        else:
            if bar_high >= stop:
                return "stop", (bar_open if bar_open > stop else stop), slot, marks
            if bar_low <= target:
                return "target", (bar_open if bar_open < target else target), slot, marks
        price = bar_close
        if checkpoints is not None and slot in checkpoints:
            marks[slot] = price
    return "neither", price, last_slot, marks


def percentile(sorted_values: Sequence[float], q: float) -> Optional[float]:
    if not sorted_values:
        return None
    return sorted_values[min(len(sorted_values) - 1, int(q * len(sorted_values)))]


def history_replay(sessions: Sequence[List[dict]], plan: dict, last_slot: int, cfg: dict) -> Optional[dict]:
    """The plan's opening-range rule on every past session, bar by bar."""
    rule = plan.get("rule", {})
    stop_rule = rule.get("stop", "or-mid")
    if plan.get("setup") != "orb" or stop_rule.startswith("price"):
        return None
    or_bars = max(1, int(rule.get("or_minutes", 15)) // 5)
    long = plan["side"] == "long"
    start_time = clock.parse_hhmm(cfg["no_entries_before"])
    end_time = clock.parse_hhmm(cfg["no_entries_after"])
    result = {"sessions": len(sessions), "fired": 0, "target": 0, "stop": 0, "neither": 0, "r": []}
    for session in sessions:
        high, low = max(b["h"] for b in session[:or_bars]), min(b["l"] for b in session[:or_bars])
        trigger = None
        for i in range(or_bars, len(session)):
            close_time = (session[i]["t"] + dt.timedelta(minutes=5)).time()
            if close_time < start_time:
                continue
            if close_time > end_time:
                break
            if (long and session[i]["c"] > high) or (not long and session[i]["c"] < low):
                trigger = i
                break
            if (long and session[i]["c"] < low) or (not long and session[i]["c"] > high):
                break                                    # broke the other way first: no trade
        if trigger is None:
            continue
        entry = session[trigger]["c"]
        atr = ind.last(ind.atr(session[:trigger + 1], min(14, trigger + 1)))
        try:
            lv = levels(plan["side"], entry, stop_rule, rule.get("target", "2R"), high, low, atr)
        except (ValidationError, DataError):
            continue
        result["fired"] += 1
        outcome, exit_price = "neither", session[min(last_slot, len(session) - 1)]["c"]
        for bar in session[trigger + 1: last_slot + 1]:
            if long:
                if bar["l"] <= lv["stop"]:
                    outcome, exit_price = "stop", min(bar["o"], lv["stop"])
                    break
                if bar["h"] >= lv["target"]:
                    outcome, exit_price = "target", max(bar["o"], lv["target"])
                    break
            else:
                if bar["h"] >= lv["stop"]:
                    outcome, exit_price = "stop", max(bar["o"], lv["stop"])
                    break
                if bar["l"] <= lv["target"]:
                    outcome, exit_price = "target", min(bar["o"], lv["target"])
                    break
        result[outcome] += 1
        result["r"].append(round(((exit_price - entry) if long else (entry - exit_price)) / lv["risk_points"], 2))
    result["avg_r"] = round(sum(result["r"]) / len(result["r"]), 2) if result["r"] else None
    return result


def verdict(result: dict, underlying: dict) -> Tuple[str, List[str]]:
    decided = result["p_target"] + result["p_stop"]
    win_share = result["p_target"] / decided if decided else 0
    breakeven = result["breakeven_win_rate"]
    notes = ["Of replays that hit a level, %.0f%% hit the target first; at R:R %.2f you need %.0f%% to break even."
             % (win_share * 100, underlying["rr"], breakeven * 100)]
    if result["p_neither"] > 0.4:
        notes.append("%.0f%% were still open at %s: the target may be too far for the time left." % (result["p_neither"] * 100, result["until"]))
    past = result.get("history")
    if past and past["fired"]:
        notes.append("History: the rule fired on %d of %d past sessions: %d target, %d stop, %d neither (avg %+.2fR)." % (
            past["fired"], past["sessions"], past["target"], past["stop"], past["neither"], past["avg_r"] or 0))
    edge = result["pnl_mean_after_charges"]
    if edge > 0 and win_share > breakeven + 0.05:
        label = "leans favourable"
    elif edge < 0 and win_share < breakeven - 0.05:
        label = "leans unfavourable"
    else:
        label = "close to a coin flip"
    notes.append("Average outcome after charges: %s %s." % (inr(edge, sign=True), result["unit"]))
    return label, notes


class TimeMachine:
    def __init__(self, market, cfg) -> None:
        self.market = market
        self.cfg = cfg

    def run(self, plan: dict, replays: int = 10000, seed: int = 19, window: int = 2, until: Optional[str] = None) -> dict:
        symbol, day = plan["symbol"], dt.date.fromisoformat(plan["date"])
        _, bars = self.market.candles(symbol, "5m", "60d")
        sessions = full_sessions(bars, day)
        if len(sessions) < 10:
            raise DataError("only %d full sessions of %s in the data; need 10+" % (len(sessions), symbol))
        pool = build_pool(sessions)
        underlying = plan["underlying"]
        long = plan["side"] == "long"
        entry_time = clock.parse_hhmm(plan.get("entry_time") or "09:30")
        first_slot = slot_of(entry_time)
        until_time = clock.parse_hhmm(until or plan.get("square_off_by") or self.cfg["square_off_by"])
        last_slot = min(BARS - 1, slot_of(until_time) - 1)
        if first_slot > last_slot:
            raise ValidationError("the entry time %s is after the square-off %s" % (plan.get("entry_time"), clock.hm(until_time)))
        payoff = _Payoff(plan, day, entry_time, self.cfg)

        rnd = random.Random(seed)
        counts = {"target": 0, "stop": 0, "neither": 0}
        r_multiples, pnls, finals, green = [], [], [], 0
        checkpoints = set(range(first_slot + 5, last_slot + 1, 6)) | {last_slot}
        fan: Dict[int, List[float]] = {}
        for n in range(replays):
            outcome, exit_price, exit_slot, marks = simulate(pool, rnd, underlying["entry"], underlying["stop"], underlying["target"],
                                                             long, first_slot, last_slot, window, checkpoints if n < 2000 else None)
            counts[outcome] += 1
            move = (exit_price - underlying["entry"]) if long else (underlying["entry"] - exit_price)
            r_multiples.append(move / underlying["risk_points"])
            pnl = payoff.per_lot(exit_price, exit_slot)
            pnls.append(pnl)
            green += pnl > 0
            if outcome == "neither":
                finals.append(exit_price)
            for slot, price in marks.items():
                fan.setdefault(slot, []).append(price)
        pnls_sorted, finals = sorted(pnls), sorted(finals)
        mean_pnl = sum(pnls) / len(pnls)
        round_trip = payoff.round_trip_charges(mean_pnl)
        result = {
            "symbol": symbol, "date": plan["date"], "side": plan["side"], "replays": replays, "seed": seed, "window": window,
            "sessions_used": len(sessions), "first_session": sessions[0][0]["t"].date().isoformat(),
            "last_session": sessions[-1][0]["t"].date().isoformat(), "entry_time": clock.hm(entry_time), "until": clock.hm(until_time),
            "p_target": counts["target"] / replays, "p_stop": counts["stop"] / replays, "p_neither": counts["neither"] / replays,
            "p_green": green / replays, "avg_r": sum(r_multiples) / len(r_multiples), "unit": payoff.unit,
            "pnl_mean": mean_pnl, "pnl_median": percentile(pnls_sorted, 0.5), "pnl_p5": percentile(pnls_sorted, 0.05),
            "pnl_p95": percentile(pnls_sorted, 0.95), "charges_round_trip": round_trip, "pnl_mean_after_charges": mean_pnl - round_trip,
            "close_median": percentile(finals, 0.5), "close_p5": percentile(finals, 0.05), "close_p95": percentile(finals, 0.95),
            "breakeven_win_rate": 1 / (1 + underlying["rr"]),
            "fan": [{"time": bar_close_time(day, slot).strftime("%H:%M"), "p10": percentile(sorted(v), 0.1),
                     "p50": percentile(sorted(v), 0.5), "p90": percentile(sorted(v), 0.9)} for slot, v in sorted(fan.items())],
            "instrument": plan.get("instrument", {}).get("type"),
        }
        result["history"] = history_replay(sessions, plan, last_slot, self.cfg)
        result["verdict"], result["notes"] = verdict(result, underlying)
        log.info("time machine %s %s: target %.1f%% stop %.1f%% (%d replays)", symbol, plan["side"],
                 result["p_target"] * 100, result["p_stop"] * 100, replays)
        return result


class _Payoff:
    """P&L per lot at an exit, for options (repriced) or linear instruments."""

    def __init__(self, plan: dict, day: dt.date, entry_time: dt.time, cfg: dict) -> None:
        self.cfg = cfg
        self.day = day
        self.underlying = plan["underlying"]
        self.long = plan["side"] == "long"
        instrument = plan.get("instrument", {})
        self.kind = instrument.get("type")
        self.lot = instrument.get("lot", 1)
        self.unit = "per lot (%d)" % self.lot if self.lot > 1 else "per share"
        self.rate = cfg["risk_free_rate_pct"] / 100
        if self.kind == "option":
            self.expiry_at = clock.expiry_close(dt.date.fromisoformat(instrument["expiry"]))
            self.strike, self.option, self.iv = instrument["strike"], instrument["kind"], instrument["iv"]
            self.entry_premium = instrument["premium"]["entry"]
            years = clock.years_to(self.expiry_at, clock.at(day, entry_time))
            self.anchor = self.entry_premium - bs.price(self.option, self.underlying["entry"], self.strike, years, self.rate, self.iv)

    def per_lot(self, exit_price: float, exit_slot: int) -> float:
        if self.kind == "option":
            years = clock.years_to(self.expiry_at, bar_close_time(self.day, exit_slot))
            premium = max(0.05, bs.price(self.option, exit_price, self.strike, years, self.rate, self.iv) + self.anchor)
            return (premium - self.entry_premium) * self.lot
        move = (exit_price - self.underlying["entry"]) if self.long else (self.underlying["entry"] - exit_price)
        return move * self.lot

    def round_trip_charges(self, mean_pnl: float) -> float:
        """Charges for one lot, round trip, at the average exit."""
        if self.kind == "option":
            exit_premium = max(0.05, self.entry_premium + mean_pnl / self.lot)
            return charges("option", self.entry_premium * self.lot, exit_premium * self.lot, self.cfg)["total"]
        price = self.underlying["entry"]
        if self.kind == "future":
            return charges("future", price * self.lot, price * self.lot, self.cfg)["total"]
        return charges("equity_intraday", price, price, self.cfg)["total"]
