"""Terminal views for the trade chain: entry timer, plan, Time Machine, sizing, paper journal and alerts."""

from typing import List, Optional

from indtrader.core.formatting import inr, num, table
from indtrader.models.trading.alerts import AlertBook, describe
from indtrader.models.trading.paper import stats
from indtrader.models.trading.sizing import UNLIMITED


def entry(result: dict) -> str:
    text = "%s %s: %s" % (result["symbol"], result.get("setup", ""), result["status"].upper())
    if result["status"] == "triggered":
        text += " %s at %s IST, close %s" % (result["side"].upper(), result["trigger_time"], num(result["trigger_price"]))
        if result.get("or_high"):
            text += " (range %s - %s)" % (num(result["or_low"]), num(result["or_high"]))
        if result.get("vol_x"):
            text += ", volume %.1fx the range bars" % result["vol_x"]
        text += ". Instrument: %s." % ("buy CE or buy future" if result["side"] == "long" else "buy PE or sell future")
    elif result.get("why"):
        text += ": " + result["why"]
    return text


def plan(plan: dict) -> str:
    u, i = plan["underlying"], plan["instrument"]
    lines = ["Plan %s %s (%s), made %s IST" % (plan["symbol"], plan["side"].upper(), plan["setup"], plan["made"][11:16]),
             "Underlying: entry %s  stop %s  target %s   risk %s pts, reward %s pts, R:R %s" % (
                 num(u["entry"]), num(u["stop"]), num(u["target"]), num(u["risk_points"]), num(u["reward_points"]), num(u["rr"]))]
    if i["type"] == "option":
        p = i["premium"]
        lines += ["Option: BUY %s  (lot %d)" % (i["tradingsymbol"], i["lot"]),
                  "  premium %s  -> stop %s / target %s  (risk %s, reward %s per unit)" % (
                      num(p["entry"]), num(p["stop"]), num(p["target"]), num(p["risk"]), num(p["reward"])),
                  "  per lot: cost %s, risk %s, reward %s (before charges)" % (inr(i["cost_per_lot"]), inr(i["risk_per_lot"]), inr(i["reward_per_lot"])),
                  "  delta %s  IV %s  theta %s/day  spread %s%%  OI %s" % (
                      num(i["delta"]), ("%.1f%%" % (i["iv"] * 100)) if i["iv"] else "-", num(i["theta"]), num(i["spread_pct"], 1), i["oi"]),
                  "  (%s)" % p["model_note"]]
        view = plan.get("chain_view")
        if view:
            lines.append("Chain: PCR %s, max pain %s, support %s, resistance %s, positioning %s" % (
                num(view["pcr"]), num(view["max_pain"], 0), "/".join(num(x, 0) for x in view["support"]),
                "/".join(num(x, 0) for x in view["resistance"]), view["bias"]))
    elif i["type"] == "future":
        lines.append("Future: %s %s, lot %d: risk %s, reward %s per lot; margin about %s per lot (estimate)" % (
            "BUY" if plan["side"] == "long" else "SELL", plan["symbol"], i["lot"], inr(i["risk_per_lot"]), inr(i["reward_per_lot"]),
            inr(i["margin_per_lot_est"])))
        lines.append("  " + i["note"])
    else:
        lines.append("Equity intraday (MIS): %s %s, risk %s per share" % (
            "BUY" if plan["side"] == "long" else "SELL", plan["symbol"], num(i["risk_per_share"])))
    lines.append("Exit by %s IST, win or lose. A stop is a plan, not a guarantee: fast markets fill past it." % plan["square_off_by"])
    return "\n".join(lines)


def time_machine(result: dict) -> str:
    r = result
    lines = ["Time Machine: %s %s from %s to %s IST, %d replays (seed %d) built from %d sessions (%s to %s)" % (
        r["symbol"], r["side"].upper(), r["entry_time"], r["until"], r["replays"], r["seed"], r["sessions_used"],
        r["first_session"], r["last_session"]), ""]
    lines.append("Target first %.1f%%   Stop first %.1f%%   Neither (closed at %s) %.1f%%" % (
        r["p_target"] * 100, r["p_stop"] * 100, r["until"], r["p_neither"] * 100))
    lines.append("Finished green %.1f%%   Average %+.2fR" % (r["p_green"] * 100, r["avg_r"]))
    lines.append("P&L %s: median %s, 5th pct %s, 95th pct %s, mean %s; charges ~%s round trip" % (
        r["unit"], inr(r["pnl_median"], sign=True), inr(r["pnl_p5"], sign=True), inr(r["pnl_p95"], sign=True),
        inr(r["pnl_mean"], sign=True), inr(r["charges_round_trip"])))
    if r["close_median"]:
        lines.append("Underlying at %s when no level hit: median %s (5%%-95%%: %s - %s)" % (
            r["until"], num(r["close_median"]), num(r["close_p5"]), num(r["close_p95"])))
    if r["fan"]:
        lines.append("Path of the underlying (10th / 50th / 90th pct): " + "  ".join(
            "%s %s/%s/%s" % (f["time"], num(f["p10"], 0), num(f["p50"], 0), num(f["p90"], 0)) for f in r["fan"][::2]))
    lines += ["", "Verdict: %s." % r["verdict"].upper()]
    lines += ["  - " + note for note in r["notes"]]
    lines += ["", "A replay of the last 60 days, not a forecast. Event days (results, RBI, budget, expiry) behave differently."]
    return "\n".join(lines)


def sizing(plan: dict, sized: dict, order: dict, capital: float) -> str:
    equity = plan["instrument"]["type"] == "equity"
    lines = ["Sizing %s (%s) against capital %s:" % (plan["symbol"], plan["instrument"]["type"], inr(capital)),
             table([[k, v if v < UNLIMITED else "-"] for k, v in sized["limits"].items()], ["Limit", "Shares" if equity else "Lots"])]
    if sized.get("refused"):
        lines += ["", "NO TRADE: " + sized["refused"] + ".",
                  "Options: a closer stop, a cheaper strike, or a bigger max_loss_per_trade (only if you mean it)."]
        return "\n".join(lines)
    lines += ["Decided by: %s" % sized["binding"], ""]
    lots = ("%d lot%s = %d qty" % (order["lots"], "s" if order["lots"] > 1 else "", order["qty"])) if order.get("lots") else "%d shares" % order["qty"]
    lines.append("Proposed: %s %s, %s, LIMIT %s, stop %s, target %s, exit by %s" % (
        order["action"], order["symbol"], lots, num(order["price"]), num(order["stop_loss"]), num(order["target"]), order["square_off_by"]))
    lines.append("Capital used %s.  At the stop: %s net (gross %s).  At the target: %s net (gross %s).  R:R after charges %s" % (
        inr(order["capital_used"]), inr(sized["net_at_stop"], sign=True), inr(sized["gross_at_stop"], sign=True),
        inr(sized["net_at_target"], sign=True), inr(sized["gross_at_target"], sign=True), num(order["rr_net"])))
    c = sized["charges_at_target"]
    lines.append("Charges at target: %s (brokerage %s, STT %s, exchange %s, GST %s, stamp %s, SEBI %s). Breakeven exit %s" % (
        inr(c["total"]), inr(c["brokerage"]), inr(c["stt"]), inr(c["exchange"]), inr(c["gst"]), inr(c["stamp"]), inr(c["sebi"]),
        num(order["breakeven"])))
    return "\n".join(lines)


def profit_target(table_data: dict, max_loss: float) -> str:
    t = table_data
    lines = ["Profit goal %s net of charges. Entry %s, plan stop %s, plan target %s (%s points):" % (
        inr(t["profit_goal"]), num(t["entry"]), num(t["stop"]), num(t["target"]), t["unit"])]
    rows = [[r["lots"], r["qty"], num(r["move_needed"]), "%.2f%%" % r["move_pct"], "yes" if r["within_plan_target"] else "no",
             inr(r["capital"], 0), inr(-r["loss_at_stop"], 0), "%sx" % r["loss_vs_goal"],
             "" if r["loss_at_stop"] <= max_loss else "over max loss"] for r in t["rows"]]
    lines.append(table(rows, ["Lots", "Qty", "Move needed", "%", "In plan?", "Capital", "Loss at stop", "Loss/goal", ""], "rrrrlrrrl"))
    lines.append("More lots make the goal a smaller move, but the loss at the stop grows just as fast. "
                 "A move inside the bid-ask spread is not a plan; neither is a stop loss many times the goal.")
    return "\n".join(lines)


def paper_mark(events: List[dict]) -> str:
    if not events:
        return "No open paper trades."
    lines = []
    for event in events:
        trade = event["trade"]
        if event.get("error"):
            lines.append("%s: no price (%s)" % (trade["id"], event["error"]))
        elif event.get("closed"):
            lines.append("CLOSED %s %s at %s (%s): net %s (%+.2fR)" % (
                trade["id"], trade["symbol"], num(event["price"]), event["closed"], inr(trade["net"], sign=True), trade["r"] or 0))
        else:
            lines.append("open   %s %s last %s, P&L %s (stop %s, target %s)" % (
                trade["id"], trade["symbol"], num(event["price"]), inr(event["mtm"], sign=True), num(trade["stop_loss"]), num(trade["target"])))
    return "\n".join(lines)


def paper_report(trades: List[dict], days: Optional[int], last: int) -> str:
    summary = stats(trades)
    if not summary:
        return "No closed paper trades%s yet." % (" in the last %d days" % days if days else "")
    lines = ["Paper results%s: %d trades, %d wins (%.0f%%), average %+.2fR" % (
                 " (last %d days)" % days if days else "", summary["trades"], summary["wins"], summary["win_rate"] * 100, summary["avg_r"] or 0),
             "Gross %s - charges %s = net %s.  Average win %s, average loss %s, worst drawdown %s" % (
                 inr(summary["gross"], sign=True), inr(summary["charges"]), inr(summary["net"], sign=True), inr(summary["avg_win"]),
                 inr(summary["avg_loss"]), inr(summary["max_drawdown"]))]
    by_setup = {}
    for trade in trades:
        if trade["status"] == "closed":
            by_setup.setdefault(trade.get("setup") or "-", []).append(trade)
    if len(by_setup) > 1:
        lines.append(table([[name, len(group), "%.0f%%" % (sum(1 for t in group if t["net"] > 0) / len(group) * 100),
                             inr(sum(t["net"] for t in group), sign=True)] for name, group in by_setup.items()],
                           ["Setup", "Trades", "Win", "Net"]))
    lines.append("")
    rows = [[t["id"], t["symbol"], t["opened"][5:16].replace("T", " "), num(t["entry"]), num(t.get("exit")), t.get("reason", t["status"]),
             inr(t.get("net"), sign=True) if t["status"] == "closed" else "open"] for t in trades[-last:]]
    lines.append(table(rows, ["Id", "Symbol", "Opened", "Entry", "Exit", "Why", "Net"], "lllrrlr"))
    return "\n".join(lines)


def alerts(book: AlertBook) -> str:
    if not book.rules:
        return "No alerts."
    return table([[r["id"], describe(r), r.get("date", "any day"), book.rang.get(r["id"], "-")] for r in book.rules],
                 ["Id", "Rule", "Day", "Rang"], "llll")
