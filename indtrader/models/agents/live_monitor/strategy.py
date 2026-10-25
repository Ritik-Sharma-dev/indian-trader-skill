"""The live trading rules: indicators at a bar, entries, stops and management.

Indicators on 5-minute bars: opening range (first 15 minutes), VWAP (time-
weighted for indices), EMA 9/21, SuperTrend(10, 3), RSI(14), ATR(14) and the
previous day's high / low / close. Bias = three votes: price vs VWAP,
SuperTrend direction, EMA 9 vs EMA 21 (-3 all bearish ... +3 all bullish).

Entries (inside the entry window, at most ``live_max_trades`` a day, one at
a time, two bars of cooldown after an exit, never more than 2.5 ATR from VWAP):

* orb: a close beyond the opening range while the bias is not against it
  (closes beyond the range with the bias against them wait until it turns)
* pullback: after the range broke, price returns to VWAP or the range edge
  and the bar closes back in the break direction, bias at least -1 / +1
* level: the first close beyond the previous day's low / high, bias -2 / +2

Stop: beyond the last three bars plus 0.1 ATR (the range middle for orb), at
least 0.6 ATR; skipped if wider than 3 ATR. Target 2R. Management: stop
first, then target; at +1R the stop moves to the entry; beyond +1.5R it
trails 1 ATR behind the close; a close across VWAP with SuperTrend flipped
exits; everything exits at ``square_off_by``.
"""

import datetime as dt
from typing import List, Optional, Tuple

from indtrader.core import clock
from indtrader.core.formatting import num, round_tick
from indtrader.models.analytics import indicators as ind

STEP = dt.timedelta(minutes=5)
OPENING_RANGE_BARS = 3


def snapshot(prev: List[dict], session: List[dict], i: int) -> dict:
    """Indicator values at bar ``i`` of today's session (bars 0..i closed)."""
    upto = prev + session[:i + 1]
    closes = [b["c"] for b in upto]
    vwap, _ = ind.vwap(session[:i + 1])
    st_line, st_dir = ind.supertrend(upto)
    ema9, ema21 = ind.ema(closes, 9), ind.ema(closes, 21)
    atr = ind.atr(upto, 14)
    rsi = ind.rsi(closes, 14)
    opening = ind.opening_range(session[:i + 1], OPENING_RANGE_BARS * 5, 5)
    bar = session[i]
    snap = {"t": bar["t"], "close_t": bar["t"] + STEP, "close": bar["c"], "high": bar["h"], "low": bar["l"], "open": bar["o"],
            "vwap": vwap[-1], "st": st_line[-1], "st_dir": st_dir[-1], "ema9": ema9[-1], "ema21": ema21[-1],
            "atr": atr[-1] or (bar["h"] - bar["l"]), "rsi": rsi[-1],
            "or_high": opening[0] if opening else None, "or_low": opening[1] if opening else None,
            "day_high": max(b["h"] for b in session[:i + 1]), "day_low": min(b["l"] for b in session[:i + 1]),
            "day_open": session[0]["o"]}
    ema_vote = (1 if (ema9[-1] or 0) > (ema21[-1] or 0) else -1) if ema9[-1] and ema21[-1] else 0
    snap["bias"] = (1 if bar["c"] > vwap[-1] else -1) + (st_dir[-1] or 0) + ema_vote
    if prev:
        last_day = [b for b in prev if b["t"].date() == prev[-1]["t"].date()]
        high, low, close = max(b["h"] for b in last_day), min(b["l"] for b in last_day), last_day[-1]["c"]
        snap.update({"pdh": high, "pdl": low, "pdc": close, "pivots": ind.pivots(high, low, close)})
    return snap


def bias_text(bias: int) -> str:
    named = {3: "STRONG BULLISH", 1: "BULLISH", -1: "BEARISH", -3: "STRONG BEARISH"}
    if bias in named:
        return named[bias]
    return "NEUTRAL" if bias == 0 else ("BULLISH" if bias > 0 else "BEARISH")


def daily_regime(daily_closes: List[float]) -> Optional[str]:
    """'up' above a rising 20-day EMA, 'down' below a falling one, else None.
    Uses closes BEFORE the trading day."""
    if len(daily_closes) < 25:
        return None
    average = ind.ema(daily_closes, 20)
    if daily_closes[-1] > average[-1] and average[-1] > average[-4]:
        return "up"
    if daily_closes[-1] < average[-1] and average[-1] < average[-4]:
        return "down"
    return None


class LiveStrategy:
    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self.entry_start = clock.parse_hhmm(cfg["no_entries_before"])
        self.entry_end = clock.parse_hhmm(cfg["no_entries_after"])
        self.square_off = clock.parse_hhmm(cfg["square_off_by"])

    @staticmethod
    def stop_for(side: str, setup: str, session: List[dict], i: int, snap: dict) -> Tuple[float, float]:
        atr = snap["atr"]
        if setup == "orb" and snap["or_high"]:
            stop = (snap["or_high"] + snap["or_low"]) / 2
        else:
            recent = session[max(0, i - 2): i + 1]
            stop = (max(b["h"] for b in recent) + 0.1 * atr) if side == "short" else (min(b["l"] for b in recent) - 0.1 * atr)
        risk = (stop - snap["close"]) if side == "short" else (snap["close"] - stop)
        if risk < 0.6 * atr:
            risk = 0.6 * atr
            stop = snap["close"] + risk if side == "short" else snap["close"] - risk
        return round_tick(stop, 0.05, "up" if side == "short" else "down"), risk

    def candidates(self, state: dict, session: List[dict], i: int, snap: dict) -> List[Tuple[str, str, str]]:
        close, vwap, atr, bias = snap["close"], snap["vwap"], snap["atr"], snap["bias"]
        found = []
        if not state["orb_done"]:
            if close > snap["or_high"] and bias >= 0:
                found.append(("long", "orb", "close above the opening range %s with the bias %+d" % (num(snap["or_high"]), bias)))
            elif close < snap["or_low"] and bias <= 0:
                found.append(("short", "orb", "close below the opening range %s with the bias %+d" % (num(snap["or_low"]), bias)))
        if state["or_break"] == "down":
            zone = min(vwap, snap["or_low"])
            if snap["high"] >= zone - 0.2 * atr and close < zone and close < snap["open"] and bias <= -1:
                found.append(("short", "pullback", "bounced to VWAP / range low %s and closed back below" % num(zone)))
        elif state["or_break"] == "up":
            zone = max(vwap, snap["or_high"])
            if snap["low"] <= zone + 0.2 * atr and close > zone and close > snap["open"] and bias >= 1:
                found.append(("long", "pullback", "dipped to VWAP / range high %s and closed back above" % num(zone)))
        prev_close = session[i - 1]["c"] if i > 0 else None
        if snap.get("pdl") and not state["level_done"]["short"] and close < snap["pdl"] and bias <= -2 \
                and prev_close is not None and prev_close >= snap["pdl"]:
            found.append(("short", "level", "closed below the previous day's low %s" % num(snap["pdl"])))
        if snap.get("pdh") and not state["level_done"]["long"] and close > snap["pdh"] and bias >= 2 \
                and prev_close is not None and prev_close <= snap["pdh"]:
            found.append(("long", "level", "closed above the previous day's high %s" % num(snap["pdh"])))
        return found

    def find_entry(self, state: dict, session: List[dict], i: int, snap: dict) -> Optional[dict]:
        moment = snap["close_t"].time()
        if moment < self.entry_start or moment > self.entry_end:
            return None
        if state["trade"] or len(state["trades"]) >= self.cfg.get("live_max_trades", 2):
            return None
        if state["cooldown_until"] and snap["close_t"].isoformat() < state["cooldown_until"]:
            return None
        if snap["or_high"] is None or abs(snap["close"] - snap["vwap"]) > 2.5 * snap["atr"]:
            return None
        regime = state.get("regime") if self.cfg.get("live_trend_filter", False) else None
        for side, setup, why in self.candidates(state, session, i, snap):
            if (regime == "down" and side == "long") or (regime == "up" and side == "short"):
                continue                                   # against the daily trend
            stop, risk = self.stop_for(side, setup, session, i, snap)
            if risk > 3 * snap["atr"]:
                continue
            target = round_tick(snap["close"] - 2 * risk if side == "short" else snap["close"] + 2 * risk)
            return {"side": side, "setup": setup, "why": why, "entry": snap["close"], "stop": stop, "init_stop": stop,
                    "target": target, "risk": round(risk, 2), "time": snap["close_t"].strftime("%H:%M"), "bar": i}
        return None

    def manage(self, trade: dict, session: List[dict], i: int, snap: dict) -> Optional[Tuple[str, float]]:
        """An exit ``(reason, price)``, a stop move ``("move-stop", price)``, or None."""
        bar = session[i]
        short = trade["side"] == "short"
        if short:
            if bar["h"] >= trade["stop"]:
                return "stop", max(trade["stop"], bar["o"]) if bar["o"] > trade["stop"] else trade["stop"]
            if bar["l"] <= trade["target"]:
                return "target", trade["target"]
        else:
            if bar["l"] <= trade["stop"]:
                return "stop", min(trade["stop"], bar["o"]) if bar["o"] < trade["stop"] else trade["stop"]
            if bar["h"] >= trade["target"]:
                return "target", trade["target"]
        if snap["close_t"].time() >= self.square_off:
            return "square-off", bar["c"]
        if (short and bar["c"] > snap["vwap"] and snap["st_dir"] == 1) or (not short and bar["c"] < snap["vwap"] and snap["st_dir"] == -1):
            return "trend turned", bar["c"]
        # the best move since entry, from this bar's extreme: the day's high / low can predate the trade
        best = max((trade["entry"] - bar["l"]) if short else (bar["h"] - trade["entry"]), trade.get("best", 0))
        trade["best"] = best
        new_stop = trade["stop"]
        if best >= trade["risk"]:
            new_stop = min(new_stop, trade["entry"]) if short else max(new_stop, trade["entry"])
        if best >= 1.5 * trade["risk"]:
            trail = bar["c"] + snap["atr"] if short else bar["c"] - snap["atr"]
            new_stop = min(new_stop, trail) if short else max(new_stop, trail)
        new_stop = round_tick(new_stop, 0.05, "up" if short else "down")
        if new_stop != trade["stop"]:
            trade["stop"] = new_stop
            return "move-stop", new_stop
        return None
