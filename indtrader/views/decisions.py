"""Terminal views for the decision maker: decisions, the rules' backtest and the decision journal."""

from typing import Optional

from indtrader.core.formatting import num
from indtrader.models.agents.decision_maker.decider import Decision


_MARK = {"BUY CALL": ">>>", "BUY PUT": ">>>", "EXIT": ">>>", "HOLD": "==", "WAIT": "..", "NO TRADE": "xx", "DONE": "--"}


def decision(item: Decision) -> str:
    stamp = item.time[11:16] if len(item.time) > 11 else item.time
    head = "%s %s IST  %s%s  DECISION: %s%s" % (
        _MARK.get(item.action, ""), stamp, item.symbol, (" %s" % num(item.price)) if item.price else "", item.action,
        (" (%s confidence)" % item.confidence) if item.confidence else "")
    lines = [head, "    " + item.headline]
    if item.do:
        lines.append("    DO:")
        lines += ["      - " + line for line in item.do]
    if item.triggers:
        lines.append("    TRIGGERS:")
        lines += ["      - " + line for line in item.triggers]
    if item.why:
        lines.append("    WHY:")
        lines += ["      - " + line for line in item.why]
    context = item.context or {}
    if context.get("errors"):
        lines.append("    (not available: %s)" % "; ".join(e.split(":")[0] for e in context["errors"]))
    if item.action in ("BUY CALL", "BUY PUT"):
        lines.append("    Confirm the candle close in your broker app, LIMIT order, 1 lot, square off by 15:15. Decision support, not advice.")
    return "\n".join(lines)


def _row(label: str, record: Optional[dict]) -> str:
    if not record:
        return "  %-34s no trades" % label
    return "  %-34s %3d trades, %3.0f%% won, total %+6.2fR, average %+.2fR, worst run %+.2fR" % (
        label, record["trades"], record["win_rate"] * 100, record["total_r"], record["avg_r"], record["max_dd_r"])


def backtest(result: dict) -> str:
    lines = ["Decision rules on %s, %d sessions %s to %s (index points, before option decay and charges):" % (
        result["symbol"], result["sessions"], result["from"], result["to"]),
        _row("every live-engine signal", result["all"]), _row("TAKEN by the decision rules", result["taken"])]
    for reason, record in sorted(result["skipped"].items()):
        lines.append(_row("skipped: " + reason, record))
    chosen = result.get("rules_chosen_through")
    if chosen:
        lines += ["", "Out of sample (sessions after %s, when the rules were chosen): %d sessions" % (chosen, result["sessions_after"]),
                  _row("TAKEN since then", result["taken_after"])]
    lines += ["", "Sessions up to %s are the ones the rules were chosen on (in-sample), so expect the future to be worse." % (chosen or "today"),
              "Re-run this every few weeks: if 'TAKEN' stops beating 'every signal', the rules have stopped working."]
    return "\n".join(lines)


def journal(summary: dict) -> str:
    if not summary["days"]:
        return ("The decision journal is empty. It fills itself from live `decide now` runs during market hours "
                "(replays and tests are never recorded).")
    lines = ["Decision journal (live decisions only), %s to %s: %d days, %d trades finished, %d no-trade days" % (
        summary["first"], summary["last"], summary["days"], summary["trades"], summary["no_trade_days"])]
    if summary["trades"]:
        lines.append("Record: %d wins of %d, total %+.2fR, average %+.2fR (index points, before option decay and charges)" % (
            summary["wins"], summary["trades"], summary["total_r"], summary["avg_r"]))
        for level, record in summary["by_confidence"].items():
            lines.append("  %-6s confidence: %d trades, %d wins, %+.2fR" % (level, record["trades"], record["wins"], record["total_r"]))
    lines.append("")
    for entry in summary["recent"]:
        outcome = entry.get("outcome") or {}
        if outcome.get("taken"):
            result = "%s %s at %s -> %s %s" % ("PUT" if outcome["side"] == "short" else "CALL", outcome["confidence"] or "",
                                               outcome["entry_time"], outcome.get("exit_reason") or "open",
                                               ("%+.2fR" % outcome["r"]) if outcome.get("r") is not None else "")
        else:
            result = outcome.get("reason", "no decision recorded")[:90]
        lines.append("  %s %-6s gap %s  %s" % (entry["date"], entry["symbol"],
                                               ("%+.2f%%" % entry["gap_pct"]) if entry.get("gap_pct") is not None else "  -  ", result))
    lines.append("Judge the rules on 20+ trades, not a handful.")
    return "\n".join(lines)
