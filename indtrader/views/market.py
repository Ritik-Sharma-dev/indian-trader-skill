"""Terminal views for market data: the pulse, charts, option chains, history, money flows and the global view."""

import datetime as dt
from typing import List, Optional

from indtrader.core.formatting import num, pct, table
from indtrader.models.analytics.history import BUCKETS


def chart(analysis: dict) -> str:
    a = analysis
    lines = ["%s %s chart, as of %s IST: trend %s" % (a["symbol"], a["interval"], a["as_of"].replace("T", " "), a["trend"].upper())]
    if "day_high" in a:
        lines.append("Last %s   open %s   day range %s - %s   change %s   gap %s" % (
            num(a["last"]), num(a["open"]), num(a["day_low"]), num(a["day_high"]), pct(a.get("change_pct")), pct(a.get("gap_pct"))))
        lines.append("ATR(14) on %s bars: %s" % (a["interval"], num(a["atr"])))
    else:
        lines.append("Last %s   change %s   52w %s - %s" % (num(a["last"]), pct(a.get("change_pct")), num(a["low_52w"]), num(a["high_52w"])))
    lines.append("")
    lines += ["  - " + s for s in a["signals"]]
    levels = a["levels"]
    if a.get("pivots"):
        p = a["pivots"]
        lines += ["", "Pivots: S3 %s  S2 %s  S1 %s  P %s  R1 %s  R2 %s  R3 %s" % tuple(num(p[k]) for k in ("S3", "S2", "S1", "P", "R1", "R2", "R3")),
                  "Previous day: high %s  low %s  close %s" % (num(levels["pdh"]), num(levels["pdl"]), num(levels["pdc"]))]
    if a.get("next_session"):
        nxt = a["next_session"]
        p = nxt["pivots"]
        lines += ["", "Levels for the NEXT session (from this day's high %s, low %s, close %s):" % (num(nxt["high"]), num(nxt["low"]), num(nxt["close"])),
                  "  CPR %s - %s (width %.2f%%)   P %s" % (num(p["BC"]), num(p["TC"]), p["cpr_width_pct"], num(p["P"])),
                  "  S3 %s  S2 %s  S1 %s  |  R1 %s  R2 %s  R3 %s" % tuple(num(p[k]) for k in ("S3", "S2", "S1", "R1", "R2", "R3"))]
    if levels.get("swing"):
        lines += ["", "Swing levels (last 120 bars): " + ", ".join("%s (%dx %s)" % (num(x["level"]), x["touches"], x["kind"]) for x in levels["swing"])]
    lines += ["", "This describes the chart; it does not say what happens next."]
    return "\n".join(lines)


def chain(analysis: dict, rows_each_side: int = 6) -> str:
    a = analysis
    lines = ["%s option chain, expiry %s (%.1f days), as of %s" % (a["symbol"], a["expiry"], a["days_to_expiry"], a.get("timestamp") or "-"),
             "Spot %s   ATM %s   lot %s   step %s" % (num(a["spot"]), num(a["atm"], 0), a.get("lot") or "-", num(a["strike_step"], 0)), ""]
    change_pcr = num(a["pcr_change"]) if a["pcr_change"] is not None else "n/a"
    lines.append("PCR (OI) %s   PCR near ATM %s   PCR of today's change %s (calls %+d, puts %+d contracts)"
                 % (num(a["pcr"]), num(a["pcr_near"]), change_pcr, a["ce_oi_added"], a["pe_oi_added"]))
    lines.append("Max pain %s   ATM IV %s   ATM straddle %s (priced-in move to expiry: +/- %s, %s)" % (
        num(a["max_pain"], 0), ("%.1f%%" % (a["atm_iv"] * 100)) if a["atm_iv"] else "-", num(a["straddle"]),
        num(a["expected_move"], 0), ("%.2f%%" % (a["expected_move"] / a["spot"] * 100)) if a["expected_move"] else "-"))
    lines.append("Resistance (call OI): " + ", ".join("%s (%s)" % (num(x["strike"], 0), x["oi"]) for x in a["resistance"]))
    lines.append("Support (put OI):     " + ", ".join("%s (%s)" % (num(x["strike"], 0), x["oi"]) for x in a["support"]))
    lines.append("Most calls written:   " + ", ".join("%s (%+d)" % (num(x["strike"], 0), x["coi"]) for x in a["ce_writing"]))
    lines.append("Most puts written:    " + ", ".join("%s (%+d)" % (num(x["strike"], 0), x["coi"]) for x in a["pe_writing"]))
    lines += ["", "Positioning: %s (score %+d)" % (a["bias"].upper(), a["bias_score"])]
    lines += ["  - " + reason for reason in a["reasons"]]
    lines.append("")
    atm_index = next(i for i, r in enumerate(a["near"]) if r["strike"] == a["atm"])
    rows = []
    for r in a["near"][max(0, atm_index - rows_each_side): atm_index + rows_each_side + 1]:
        ce, pe = r["ce"] or {}, r["pe"] or {}
        rows.append([num(ce.get("delta")), ce.get("oi", "-"), "%+d" % ce.get("coi", 0), num(ce.get("ltp")),
                     ("%.1f" % (ce["iv_calc"] * 100)) if ce.get("iv_calc") else "-",
                     num(r["strike"], 0) + ("*" if r["strike"] == a["atm"] else ""),
                     ("%.1f" % (pe["iv_calc"] * 100)) if pe.get("iv_calc") else "-",
                     num(pe.get("ltp")), "%+d" % pe.get("coi", 0), pe.get("oi", "-"), num(pe.get("delta"))])
    lines.append(table(rows, ["CE delta", "CE OI", "CE chg", "CE LTP", "CE IV", "STRIKE", "PE IV", "PE LTP", "PE chg",
                              "PE OI", "PE delta"], "rrrrrrrrrrr"))
    lines += ["", "Positioning is a reading of who wrote what, not a forecast."]
    return "\n".join(lines)


def _rate_text(value: Optional[float]) -> str:
    return "%.0f%%" % (value * 100) if value is not None else "-"


def history(s: dict) -> str:
    streak = ("%d up" % s["current_streak"]) if s["current_streak"] > 0 else ("%d down" % -s["current_streak"])
    lines = [
        "%s: last %d sessions (%s to %s)" % (s["symbol"], s["sessions"], s["from"], s["to"]),
        "Net %s (%s pts), worst drawdown %s. Up days %d, down days %d (average up %s, average down %s)." % (
            pct(s["net_change_pct"]), num(s["net_change_pts"], 0), pct(s["max_drawdown_pct"]), s["up_days"], s["down_days"],
            pct(s["avg_up_pct"]), pct(s["avg_down_pct"])),
        "Best day %s %s, worst day %s %s. Longest up streak %d, longest down streak %d, current streak %s." % (
            s["best_day"]["date"], pct(s["best_day"]["change_pct"]), s["worst_day"]["date"], pct(s["worst_day"]["change_pct"]),
            s["longest_up_streak"], s["longest_down_streak"], streak),
        "Average day range %s pts (%s), largest %s pts. Expiry days (%d) range %s vs other days %s." % (
            num(s["avg_range_pts"], 0), pct(s["avg_range_pct"], sign=False), num(s["max_range_pts"], 0), s["expiry_days"],
            pct(s["expiry_avg_range_pct"], sign=False), pct(s["other_avg_range_pct"], sign=False)),
        "Day types: " + ", ".join("%s %d" % kv for kv in sorted(s["day_types"].items(), key=lambda kv: -kv[1])),
        "Gaps of 0.2%%+: %d (%d up, %d down); filled the same day %s of the time; average gap %s." % (
            s["gap_days"], s["gap_up"], s["gap_down"], _rate_text(s["gap_fill_rate"]), pct(s["avg_abs_gap_pct"], sign=False)),
        "Weekday average change: " + ", ".join("%s %s" % (k, pct(v)) for k, v in s["weekday_avg_change"].items()),
    ]
    if s["or_sessions"]:
        lines.append("Opening range (first 15 min): average %s pts (%s). Broke up first %d, down first %d, no break %d. "
                     "After a break, went on 1x the range width %s; came back to the range middle %s." % (
                         num(s["or_avg_width_pts"], 0), pct(s["or_avg_width_pct"], sign=False), s["or_broke_up_first"],
                         s["or_broke_down_first"], s["or_no_break"], _rate_text(s["or_follow_1x_rate"]),
                         _rate_text(s["or_back_to_mid_rate"])))
        lines.append("Day's HIGH made in: " + ", ".join("%s %d" % (b, s["high_time_buckets"].get(b, 0)) for b, _, _ in BUCKETS))
        lines.append("Day's LOW made in:  " + ", ".join("%s %d" % (b, s["low_time_buckets"].get(b, 0)) for b, _, _ in BUCKETS))
        lines.append("Average 5-min bar range by hour: " + ", ".join("%s:00 %s" % (h, num(v, 1)) for h, v in s["hour_avg_bar_range"].items()))
    lines.append("")
    rows = [[d["date"][5:], d["weekday"], num(d["close"]), pct(d["change_pct"]), num(d["range_pts"], 0), pct(d["gap_pct"]),
             d["type"], d.get("or_first", "-"), d.get("high_time", "-"), d.get("low_time", "-")] for d in s["days"]]
    lines.append(table(rows, ["Date", "Day", "Close", "Change", "Range", "Gap", "Type", "OR break", "High at", "Low at"], "llrrrrllll"))
    return "\n".join(lines)


def flows(result: dict, limit: int = 10) -> str:
    lines: List[str] = []
    fii = result.get("fiidii")
    if fii:
        lines.append("FII / DII cash market, %s (rupees crore):" % fii.get("date"))
        lines.append(table([[k, num(fii[k]["buy"]), num(fii[k]["sell"]), num(fii[k]["net"])] for k in ("FII", "DII") if fii.get(k)],
                           ["Who", "Buy", "Sell", "Net"]))
        history = sorted(fii.get("history", {}).items(), key=lambda kv: dt.datetime.strptime(kv[0], "%d-%b-%Y"))[-5:]
        if len(history) > 1:
            lines.append("Last %d days FII net: %s" % (len(history), ", ".join("%s %s" % (d[:6], num(v["FII"]["net"], 0)) for d, v in history)))
        lines.append("")
    participants = result.get("participants")
    if participants:
        lines.append("Participant open interest, index derivatives, %s (contracts):" % participants["date"])
        rows = [[who, int(v["fut_long"]), int(v["fut_short"]), num(v["fut_long_pct"], 0) + "%", "%+d" % v["net_calls"], "%+d" % v["net_puts"]]
                for who, v in participants["view"].items()]
        lines.append(table(rows, ["Who", "Fut long", "Fut short", "Long %", "Net calls", "Net puts"]))
        lines += ["  - " + note for note in participants["notes"]]
        lines.append("")
    deals = result.get("deals")
    if deals:
        for label in ("block", "bulk"):
            rows = deals.get(label) or []
            lines.append("%s deals %s: %d" % (label.capitalize(), deals.get("date"), len(rows)))
            for r in rows[:limit]:
                lines.append("  %-12s %-4s %s @ %s  (%s cr)  %s" % (r["symbol"], r["side"] or "", int(r["qty"] or 0), num(r["price"]),
                                                                num(r["value_cr"]), (r["client"] or "")[:40]))
        lines.append("")
    lines += ["note: " + error for error in result.get("errors", [])]
    lines.append("Flows show positioning; they lag and do not time trades on their own.")
    return "\n".join(lines)


def sector_line(sectors: List[dict], strongest: bool, count: int) -> str:
    chosen = sectors[:count] if strongest else list(reversed(sectors[-count:]))
    return ", ".join("%s %s" % (s["name"].replace("NIFTY ", ""), pct(s["change_pct"])) for s in chosen)


def pulse(pulse: dict, status: dict) -> str:
    lines = ["Market: %s (%s). Next open %s" % (status["state"].upper(), status["reason"], status["next_open"][:16].replace("T", " "))]
    if pulse.get("breadth"):
        b = pulse["breadth"]
        lines.append("Breadth (summed over NSE indices, stocks repeat): %d up / %d down / %d unchanged, as of %s" % (
            b["advances"], b["declines"], b["unchanged"], b["timestamp"]))
    lines.append("")
    rows = [[i["name"], num(i["last"]), num(i["change"]), pct(i["change_pct"]), num(i.get("low")), num(i.get("high")),
             pct(i.get("month_change_pct")) if i.get("month_change_pct") is not None else "-"] for i in pulse["indices"]]
    lines.append(table(rows, ["Index", "Last", "Change", "%", "Low", "High", "30d %"]))
    if pulse.get("vix_note"):
        lines.append("India VIX: %s; Nifty's typical one-day move ~ %.2f%%" % (pulse["vix_note"], pulse["nifty_expected_daily_move_pct"]))
    if pulse["sectors"]:
        lines += ["", "Strongest sectors: " + sector_line(pulse["sectors"], True, 5), "Weakest sectors:   " + sector_line(pulse["sectors"], False, 5)]
    if pulse["global"]:
        lines += ["", "Global cues: " + ", ".join("%s %s" % (g["name"], pct(g["change_pct"])) for g in pulse["global"])]
    lines += ["note: " + error for error in pulse["errors"]]
    return "\n".join(lines)


def global_view(result: dict, now: dt.datetime, limit: int = 30) -> str:
    lines = ["Global view for the Indian market, %s IST" % now.strftime("%a %d %b %Y %H:%M"), ""]
    if result.get("snapshot"):
        for group in result["snapshot"]:
            rows = [[r["name"], num(r["last"]), pct(r["change_pct"]) + ((" (%+.1f bp)" % r["change_bp"]) if r.get("change_bp") is not None else ""),
                     r.get("time", "")] for r in group["rows"]]
            lines += [group["group"], table(rows, ["", "Last", "Change", "As of (IST)"], "lrrl"), ""]
        m = result["mood"]
        reasons = (": " + "; ".join(m["notes"])) if m["notes"] else ""
        lines.append("Global mood for the Indian open: %s (score %+d)%s" % (m["label"].upper(), m["score"], reasons))
        if m.get("adr_avg_pct") is not None:
            lines.append("Indian ADRs overnight: average %s (an early read on INFY, WIPRO, HDFCBANK, ICICIBANK, DRREDDY)" % pct(m["adr_avg_pct"]))
        lines.append("")
    if result.get("calendar") is not None:
        lines.append("Economic calendar (High/Medium impact, IST):")
        if not result["calendar"]:
            lines.append("  nothing in the window")
        for event in result["calendar"]:
            lines.append("  %s  %-4s %-6s %-40s forecast %s, previous %s%s" % (
                event["time"].strftime("%a %d %b %H:%M"), event["country"], event["impact"], event["event"][:40],
                event["forecast"] or "-", event["previous"] or "-", "  <- %s" % event["when"] if event["when"] in ("today", "tomorrow") else ""))
        lines.append("")
    if result.get("headlines") is not None:
        lines.append("US and global market headlines (last %d hours; --all-headlines shows untagged ones too):" % result["hours"])
        for item in result["headlines"][:limit]:
            themes = (" {" + ",".join(item["themes"]) + "}") if item["themes"] else ""
            lines.append("%s  %s%s" % (item["time"].strftime("%d %b %H:%M"), item["title"], themes))
            lines.append("      %s  %s" % (item["source"], item["link"][:100]))
        lines.append("")
        if result.get("themes"):
            lines.append("What the themes usually mean for India (rule of thumb, not a forecast):")
            lines += ["  - %s (%d stories): %s" % (t["theme"], t["count"], t["india_impact"]) for t in result["themes"][:8]]
            lines.append("")
    lines += ["note: " + error for error in result.get("errors", [])]
    lines.append("Free, unofficial data. Markets often price news before it is printed.")
    return "\n".join(lines)
