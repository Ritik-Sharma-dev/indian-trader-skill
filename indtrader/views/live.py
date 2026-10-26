"""Terminal views for the live monitor: the status block, events and the plain DECISION line."""

import datetime as dt
from typing import List, Optional

from indtrader.core.formatting import inr, num, pct, table
from indtrader.models.agents.live_monitor.monitor import Tick
from indtrader.models.agents.live_monitor.strategy import bias_text

_REGIME_TEXT = {"down": "DOWN (below a falling 20-day EMA)", "up": "UP (above a rising 20-day EMA)"}


def watch_text(state: dict, snap: dict) -> str:
    if snap.get("or_high") is None:
        return "the opening range (09:15-09:30)"
    parts = []
    if not state["orb_done"]:
        parts.append("a close above %s (CE) or below %s (PE)" % (num(snap["or_high"]), num(snap["or_low"])))
    if state["or_break"] == "down":
        parts.append("a bounce to %s rejected (PE)" % num(min(snap["vwap"], snap["or_low"])))
    if state["or_break"] == "up":
        parts.append("a dip to %s that holds (CE)" % num(max(snap["vwap"], snap["or_high"])))
    if snap.get("pdl") and not state["level_done"]["short"]:
        if snap["close"] < snap["pdl"]:
            parts.append("PDL %s already broken (a fresh signal needs a move back above it first)" % num(snap["pdl"]))
        else:
            parts.append("a close below PDL %s with bearish bias (PE)" % num(snap["pdl"]))
    if snap.get("pdh") and not state["level_done"]["long"]:
        if snap["close"] > snap["pdh"]:
            parts.append("PDH %s already broken (a fresh signal needs a move back below it first)" % num(snap["pdh"]))
        else:
            parts.append("a close above PDH %s with bullish bias (CE)" % num(snap["pdh"]))
    return "; ".join(parts) or "nothing more today (limits reached)"


def decision_text(state: dict, snap: dict, now: dt.datetime, cfg: Optional[dict] = None) -> str:
    """One plain instruction: what to do now, and the exact trigger for the next trade."""
    cfg = cfg or {}
    start, end = cfg.get("no_entries_before", "09:30"), cfg.get("no_entries_after", "14:30")
    clock_now = now.strftime("%H:%M")
    if state["trade"]:
        trade = state["trade"]
        option = "PUT" if trade["side"] == "short" else "CALL"
        return ("HOLD the %s. EXIT if Nifty %s %s (stop) or reaches %s (target), or at %s at the latest."
                % (option, "goes above" if trade["side"] == "short" else "goes below", num(trade["stop"]), num(trade["target"]),
                   cfg.get("square_off_by", "15:15")))
    if clock_now < start:
        return "WAIT. No trades before %s: the opening range (09:15-09:30) is still forming." % start
    if clock_now > end:
        return "NO NEW TRADES after %s. Only manage or exit an open trade." % end
    if len(state["trades"]) >= cfg.get("live_max_trades", 2):
        return "DONE for today: the daily trade limit is reached."
    bias = snap["bias"]
    parts = []
    if bias <= -1:
        zone = min(snap["vwap"], snap["or_low"]) if snap.get("or_low") else snap["vwap"]
        parts.append("trend is DOWN, so only PUTs. BUY PUT when a 5-min candle rises to about %s and CLOSES back below it" % num(zone))
        if snap.get("or_low") and not state["orb_done"]:
            parts[-1] += ", or closes below the opening-range low %s" % num(snap["or_low"])
    elif bias >= 1:
        zone = max(snap["vwap"], snap["or_high"]) if snap.get("or_high") else snap["vwap"]
        parts.append("trend is UP, so only CALLs. BUY CALL when a 5-min candle dips to about %s and CLOSES back above it" % num(zone))
        if snap.get("or_high") and not state["orb_done"]:
            parts[-1] += ", or closes above the opening-range high %s" % num(snap["or_high"])
    else:
        parts.append("trend is MIXED, so no side is favoured. Stay out until VWAP, SuperTrend and the EMAs agree")
    if bias <= -1 and snap.get("pdh"):
        parts.append("a CALL needs the trend to turn up first (a close above %s)" % num(snap["pdh"]))
    if bias >= 1 and snap.get("pdl"):
        parts.append("a PUT needs the trend to turn down first (a close below %s)" % num(snap["pdl"]))
    return "WAIT: " + "; ".join(parts) + ". Entries allowed until %s." % end


def status(state: dict, quote: Optional[dict], now: dt.datetime, cfg: Optional[dict] = None) -> str:
    snap = state.get("last_snap") or {}
    if not snap:
        return "%s %s: waiting for the first closed bars" % (now.strftime("%H:%M"), state["symbol"])
    price = quote["price"] if quote else snap["close"]
    change = (" (%s)" % pct(quote["change_pct"])) if quote and quote.get("change_pct") is not None else ""
    bias = snap["bias"]
    lines = ["%s IST  %s %s%s   bias %s (%+d): %s VWAP %s, SuperTrend %s, EMA9 %s EMA21   RSI %s" % (
        now.strftime("%H:%M"), state["symbol"], num(price), change, bias_text(bias), bias,
        "above" if snap["close"] > snap["vwap"] else "below", num(snap["vwap"]), "UP" if snap["st_dir"] == 1 else "DOWN",
        ">" if (snap["ema9"] or 0) > (snap["ema21"] or 0) else "<", num(snap["rsi"], 0))]
    levels = []
    if snap.get("or_high"):
        levels.append("OR %s-%s%s" % (num(snap["or_low"]), num(snap["or_high"]), (" broke %s" % state["or_break"].upper()) if state["or_break"] else ""))
    if snap.get("pdh"):
        levels.append("PDH %s PDL %s" % (num(snap["pdh"]), num(snap["pdl"])))
    levels += ["day %s-%s" % (num(snap["day_low"]), num(snap["day_high"])), "ATR %s" % num(snap["atr"], 1)]
    lines.append("   levels: " + " | ".join(levels))
    lines.append("   daily trend: %s" % _REGIME_TEXT.get(state.get("regime"), "mixed"))
    trade = state["trade"]
    if trade:
        points = (trade["entry"] - price) if trade["side"] == "short" else (price - trade["entry"])
        line = "   IN TRADE: %s (%s) since %s at %s, stop %s, target %s, now %+.1f pts (%+.2fR)" % (
            trade["side"].upper(), trade["setup"], trade["time"], num(trade["entry"]), num(trade["stop"]), num(trade["target"]),
            points, points / trade["risk"])
        option = trade.get("option")
        if option and not option.get("error"):
            line += "\n   option: %s, entry premium ~%s, premium stop ~%s, target ~%s" % (
                option["tradingsymbol"], num(option["premium_now"]), num(option["premium_stop"]), num(option["premium_target"]))
        lines.append(line)
    else:
        done = len(state["trades"])
        lines.append("   STATUS: no position. %d trade(s) today%s. Watching for: %s" % (
            done, (", net %+.1f pts" % sum(t["points"] for t in state["trades"])) if done else "", watch_text(state, snap)))
    lines.append("   >> DECISION: " + decision_text(state, snap, now, cfg))
    return "\n".join(lines)


def tick(result: Tick, cfg: Optional[dict] = None, bell: bool = False) -> str:
    """One live check as text: the events (``bell`` rings the terminal on an action), then the status block."""
    if not result.is_open:
        market = result.market
        return "%s %s: market %s (%s). Next open %s." % (result.time.strftime("%H:%M"), result.symbol, market["state"], market["reason"],
                                                         market["next_open"][:16].replace("T", " "))
    lines = [("\a" if bell and item["type"] in ("ENTRY", "EXIT") else "") + event(item, result.symbol) for item in result.events]
    return "\n".join(lines + [status(result.state, result.quote, result.time, cfg)])


def event(item: dict, symbol: str) -> str:
    stamp = item["time"].strftime("%H:%M")
    if item["type"] == "ENTRY":
        trade = item["trade"]
        out = (">>> ACTION %s  %s %s (%s): %s\n    Index entry %s | STOP %s (exit on a 5-min close beyond it, or a touch) | TARGET %s | risk %s pts"
               % (stamp, symbol, "BUY PUT (PE) - short" if trade["side"] == "short" else "BUY CALL (CE) - long", trade["setup"], trade["why"],
                  num(trade["entry"]), num(trade.get("init_stop", trade["stop"])), num(trade["target"]), num(trade["risk"])))
        option = trade.get("option")
        if option and not option.get("error"):
            out += "\n    Option: BUY %s (lot %d) LIMIT ~%s (bid %s / ask %s). Premium stop ~%s, target ~%s. Per lot: risk ~%s, reward ~%s" % (
                option["tradingsymbol"], option["lot"], num(option["premium_now"]), num(option["bid"]), num(option["ask"]),
                num(option["premium_stop"]), num(option["premium_target"]), inr(option["risk_per_lot"], 0), inr(option["reward_per_lot"], 0))
        elif option:
            out += "\n    (option lookup failed: %s)" % option["error"]
        return out + "\n    Check the risk first: /in-budget and /in-risk. Square off by 15:15."
    if item["type"] == "EXIT":
        return ">>> ACTION %s  %s %s  -> SELL the option now." % (stamp, symbol, item["text"])
    if item["type"] == "UPDATE":
        return "    %s  %s: %s" % (stamp, symbol, item["text"])
    return "    %s  %s" % (stamp, item["text"])


def replay(symbol: str, day, state: dict, events: List[dict]) -> str:
    lines = ["Replay of %s on %s with the live rules (only closed bars at each step):" % (symbol, day)]
    lines += [event(item, symbol) for item in events]
    if any(t.get("exit_reason") == "end of data" for t in state["trades"]):
        lines.append("    trade still open when the data ended: closed at the last bar")
    lines.append("Day result: %d trade(s), %+.1f points, %+.2fR" % (
        len(state["trades"]), sum(t["points"] for t in state["trades"]), sum(t["r"] for t in state["trades"])))
    return "\n".join(lines)


def backtest(symbol: str, days: List, summary: Optional[dict], trades: List[dict], last: int) -> str:
    lines = ["Backtest of the live rules on %s: %d sessions (%s to %s)" % (symbol, len(days), days[0], days[-1])]
    if not summary:
        return "\n".join(lines + ["No trades."])
    net = "total_net_r" in summary
    lines.append("%d trades, %d winners (%.0f%%), total %+.2fR (%+.1f %s), average %+.3fR per trade, worst drawdown %.2fR%s" % (
        summary["trades"], summary["wins"], summary["win_rate"] * 100, summary["total_r"], summary["total_points"],
        "points, rupees per share" if net else "index points", summary["avg_r"], summary["max_dd_r"], " (before charges)" if net else ""))
    if net:
        lines.append("After charges (equity intraday, each trade sized to max_loss_per_trade at the stop): %d winners, total %+.2fR, "
                     "average %+.3fR, net %s after %s of charges" % (
                         summary["net_wins"], summary["total_net_r"], summary["avg_net_r"],
                         inr(summary["net_rupees"], 0, sign=True), inr(summary["charges"], 0)))
    lines.append("By setup: " + "; ".join("%s: %d trades, avg %+.2fR, total %+.2fR" % (k, v["n"], v["avg_r"], v["total_r"])
                                          for k, v in summary["by_setup"].items()))
    lines.append("Exits: " + ", ".join("%s %d" % pair for pair in summary["exits"].items()))
    rows = [[t["date"][5:], t["time"], t["side"], t["setup"], num(t["entry"]), num(t["exit"]), t["exit_time"], t["exit_reason"],
             "%+.1f" % t["points"], "%+.2f" % t["r"]] for t in trades[-last:]] if last else []
    if rows:
        lines.append(table(rows, ["Date", "In", "Side", "Setup", "Entry", "Exit", "Out", "Why", "Pts", "R"], "llllrrllrr"))
    lines.append(("Points are rupees per share." if net else "Index points, before option theta and charges.") + " Past sessions, not a forecast.")
    return "\n".join(lines)
