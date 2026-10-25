"""Terminal views for the agent team: timeframes, options, stock picks, smart money, risk and the performance review."""

from typing import Dict, List

from indtrader.core.formatting import inr, num, pct, table
from indtrader.models.agents.smart_money.tracker import directional_deals


def timeframes(result: dict) -> str:
    lines = []
    for symbol, data in result["symbols"].items():
        a = data["alignment"]
        lines.append("%s %s: %s (up %s%%, down %s%%)" % (symbol, num(data["last"]), a["label"], a["up_pct"], a["down_pct"]))
        rows = [[r["interval"], r["trend"], "%+d" % r["score"], " ".join(("+" if v > 0 else "-" if v < 0 else "0") for v in r["votes"].values()),
                 num(r["rsi"], 0), num(r["atr_pct"]) + "%" if r.get("atr_pct") is not None else "-"] for r in data["rows"]]
        lines.append(table(rows, ["TF", "Trend", "Score", "close/ema/st/macd", "RSI", "ATR%"], "llrlrr"))
        levels = data.get("levels") or {}
        if levels:
            pivots = levels.get("next_pivots") or {}
            lines.append("  daily EMA50 %s, EMA200 %s; next-session pivot %s (R1 %s, S1 %s)" % (
                num(levels.get("ema50_daily")), num(levels.get("ema200_daily")), num(pivots.get("P")), num(pivots.get("R1")), num(pivots.get("S1"))))
        lines.append("")
    lines += ["- " + note for note in result["notes"]]
    lines += ["note: " + error for error in result["errors"]]
    lines.append("Alignment is a reading of trend, not an entry signal. Votes: close vs EMA21, EMA9 vs EMA21, SuperTrend, MACD.")
    return "\n".join(lines)


def options(result: dict) -> str:
    reg = result["regime"]
    vix = result.get("vix") or {}
    lines = ["%s options, expiry %s (%.1f days), spot %s, ATM %s, lot %s" % (
        result["symbol"], result["expiry"], result["days_to_expiry"], num(result["spot"]), num(result["atm"], 0), result["lot"] or "-"),
        "Volatility: ATM IV %s vs 20-day realised %s -> %s (ratio %s): %s" % (
            ("%.1f%%" % (result["atm_iv"] * 100)) if result["atm_iv"] else "-",
            ("%.1f%%" % (result["realised_vol"] * 100)) if result["realised_vol"] else "-", reg["label"], num(reg["ratio"]), reg["advice"])]
    if vix:
        lines.append("India VIX %s: %s percentile of the last year (range %s-%s)" % (
            num(vix["last"]), vix["percentile_1y"], num(vix["low_1y"]), num(vix["high_1y"])))
    lines.append("Expected move: about +/- %s points today, +/- %s to expiry" % (num(result["day_move"], 0), num(result["expected_move_to_expiry"], 0)))
    for key, title in (("calls", "CALLS (buy on a bullish signal)"), ("puts", "PUTS (buy on a bearish signal)")):
        rows = [[c["choice"], num(c["strike"], 0), num(c["premium"]), inr(c.get("cost_per_lot"), 0), num(c["delta_abs"]),
                 num(c.get("spread_pct"), 1) + "%", c.get("oi") or 0, num(c["theta_hour"]), num(c["breakeven_pts"], 1), "%d/4" % c["score"]]
                for c in result[key]]
        lines += ["", title]
        lines.append(table(rows, ["Pick", "Strike", "Premium", "Per lot", "Delta", "Spread", "OI", "Theta/h", "BE pts 30m", "Score"], "llrrrrrrrr"))
    for key, word in (("best_call", "CALL"), ("best_put", "PUT")):
        pick = result.get(key)
        if pick:
            lines.append("Best %s: %s %s %s at about %s (%s a lot), delta %s; the index must move %s points in 30 minutes to cover spread and decay" % (
                word, result["symbol"], num(pick["strike"], 0), pick["kind"], num(pick["premium"]), inr(pick.get("cost_per_lot"), 0),
                num(pick["delta_abs"]), num(pick["breakeven_pts"], 1)))
    lines += ["- " + note for note in result["notes"]]
    lines += ["note: " + error for error in result["errors"]]
    return "\n".join(lines)


def picks(result: dict) -> str:
    lines = ["F&O stock picks: %d of %d stocks read, NIFTY %s over 20 days, %d with an OI buildup reading" % (
        result["scanned"], result["universe"], pct(result["nifty_20d"]), result["buildups"])]
    if result.get("rollover"):
        lines.append("Monthly expiry %s is this week: positions are rolling to next month, so OI buildup is shown but not counted."
                     % result["monthly_expiry"])
    for key, title in (("longs", "LONG watchlist (calls / buy on a bullish setup)"), ("shorts", "SHORT watchlist (puts / sell on a bearish setup)")):
        lines += ["", title]
        if not result[key]:
            lines.append("  none with two or more reasons")
            continue
        side = key[:-1]
        lines.append(table([[r["symbol"], num(r["last"]), pct(r["change_pct"]), pct(r["rs_20d"]), r["buildup"] or "-", "; ".join(r[side])]
                            for r in result[key]], ["Symbol", "Last", "Today", "RS 20d", "Futures OI", "Why"], "lrrrll"))
    lines += ["note: " + error for error in result["errors"]]
    lines.append("A watchlist for `scan orb` and the entry timer, not trades. OI buildup is today's, from NSE's top OI changes only.")
    return "\n".join(lines)


def smart_money(result: dict, limit: int = 6) -> str:
    lines = ["Smart money:"] + (["  - " + line for line in result["verdict"]] or ["  (no readings)"])
    flows = result["flows"]
    deals = flows.get("deals") or {}
    every = (deals.get("block") or []) + (deals.get("bulk") or [])
    directional = directional_deals(every)
    big = sorted(directional, key=lambda d: -(d["value_cr"] or 0))[:limit]
    if big:
        lines += ["", "Biggest one-sided block / bulk deals %s (%d round trips by the same client left out):" % (
            deals.get("date") or "", len(every) - len(directional))]
        lines.append(table([[d["symbol"], d["side"] or "-", num(d["value_cr"]), num(d["price"]), (d["client"] or "")[:40]] for d in big],
                           ["Symbol", "Side", "Crore", "Price", "Client"], "llrrl"))
    insiders = result.get("insiders") or {}
    trades = [t for t in insiders.get("trades", []) if t["source"] == "PIT" and t["kind"] in ("buy", "sell")]
    if trades:
        lines += ["", "Insider open-market trades (last %s to %s):" % (insiders.get("from"), insiders.get("to"))]
        lines.append(table([[t["symbol"] or "BSE:%s" % t["bse_code"], t["kind"].upper(), (t["person"] or "")[:30], t["category"], inr(t["value"], 0)]
                            for t in sorted(trades, key=lambda t: -(t["value"] or 0))[:limit]], ["Symbol", "Side", "Who", "Category", "Value"], "lllll"))
    sast = [t for t in insiders.get("trades", []) if t["source"] == "SAST"]
    if sast:
        lines.append("Takeover-code filings: %d (largest holders now: %s)" % (len(sast), ", ".join(
            "%s %s%%" % (t["symbol"], num(t["pct_after"])) for t in sorted(sast, key=lambda t: -(t["pct_after"] or 0))[:4])))
    lines += ["note: " + error for error in result["errors"]]
    lines.append("Flows and filings lag prices: context for the day, never an entry signal.")
    return "\n".join(lines)


def risk(result: dict) -> str:
    limits, pnl = result["limits"], result["pnl"]
    lines = ["RISK: %s" % result["level"]]
    lines += ["  - " + r for r in result["reasons"]]
    lines += ["  ! " + w for w in result["warnings"]]
    lines.append("Today: %d trades (%d open), realised %s, open risk %s; loss budget left %s of %s" % (
        pnl["trades"], pnl["open"], inr(pnl["realised"], 0, True), inr(pnl["open_risk"], 0), inr(result["loss_budget"], 0), inr(limits["max_daily_loss"], 0)))
    option = result.get("option") or {}
    if result["risk_per_lot"]:
        lines.append("Typical NIFTY trade: stop about %s index points; one lot of %s %s risks about %s (charges included)" % (
            num(result["typical_risk_points"], 0), num(option.get("strike"), 0), option.get("kind", ""), inr(result["risk_per_lot"], 0)))
        lines.append("Lots allowed now: %s (max loss per trade %s, max lots %d, at most %s%% of %s capital in one trade)" % (
            result["lots_allowed"], inr(limits["max_loss_per_trade"], 0), limits["max_lots_per_trade"], limits["max_capital_per_trade_pct"],
            inr(limits["capital"], 0)))
    if result["level"] == "BLOCKED":
        lines.append("To trade 1 lot, set max_loss_per_trade in Indian Trader Skill/workspace/config.json to at least %s "
                     "(only an amount you can afford to lose)." % inr(result["risk_per_lot"], 0))
    return "\n".join(lines)


def _fmt(value: float, unit: str) -> str:
    return inr(value, 0, True) if unit == "rupees" else "%+.2fR" % value


def _table(groups: Dict[str, dict], title: str, unit: str) -> List[str]:
    rows = [[k, s["trades"], "%.0f%%" % (s["win_rate"] * 100), _fmt(s["expectancy"], unit), _fmt(s["total"], unit)] for k, s in groups.items() if s]
    return ["", title, table(rows, ["", "Trades", "Won", "Average", "Total"], "lrrrr")] if rows else []


def coach(result: dict) -> str:
    overall, unit = result.get("overall"), result.get("unit")
    if not overall:
        return "No trades to review yet: the paper journal and the decision journal are empty."
    lines = ["Performance review from the %s (%d paper trades, %d live decisions on record)" % (
        result["source"], result["paper_trades"], result["decision_trades"]),
        "%d trades, %.0f%% won, average win %s, average loss %s, expectancy %s a trade, total %s" % (
            overall["trades"], overall["win_rate"] * 100, _fmt(overall["avg_win"], unit), _fmt(overall["avg_loss"], unit),
            _fmt(overall["expectancy"], unit), _fmt(overall["total"], unit)),
        "Profit factor %s, worst drawdown %s, worst losing streak %d" % (
            num(overall["profit_factor"]), _fmt(overall["max_drawdown"], unit), overall["worst_losing_streak"])]
    lines += _table(result["by_hour"], "By entry hour", unit) + _table(result["by_weekday"], "By weekday", unit)
    lines += _table(result["by_setup"], "By setup", unit) + _table(result["by_confidence"], "By decision confidence", unit)
    baseline = (result.get("baseline") or {}).get("taken")
    if baseline and "backtest" not in (result["source"] or ""):
        lines.append("\nBaseline (decision rules, backtest %s to %s, in-sample): %d trades, %.0f%% won, %+.2fR a trade" % (
            result["baseline"]["from"], result["baseline"]["to"], baseline["trades"], baseline["win_rate"] * 100, baseline["expectancy"]))
    if result["mistakes"]:
        lines += ["", "Mistakes:"] + ["  - " + m for m in result["mistakes"]]
    lines += ["", "Advice:"] + ["  - " + a for a in result["advice"]]
    if result.get("watch"):
        lines += ["Watch:"] + ["  - " + w for w in result["watch"]]
    lines += ["note: " + e for e in result["errors"]]
    return "\n".join(lines)
