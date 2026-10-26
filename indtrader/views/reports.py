"""Markdown reports for the agents.

Every agent collects findings (a model); the function registered for its
name in :data:`REPORTS` turns them into the Markdown saved as
``workspace/research/<date>/<agent>-data.md``. Signature of every report
function: ``(title, now, findings) -> str``.
"""

import datetime as dt
from typing import Callable, Dict, List

from indtrader.core.formatting import num, pct, strike
from indtrader.models.agents.trading_desk.agent import STAGE_NAMES
from indtrader.views import decisions, live, team
from indtrader.views.market import sector_line

Report = Callable[[str, dt.datetime, dict], str]


def _heading(title: str, now: dt.datetime) -> List[str]:
    return ["# %s, %s IST" % (title, now.strftime("%a %d %b %Y %H:%M")), ""]


def _fenced(title: str, now: dt.datetime, body: str, errors: List[str] = ()) -> str:
    lines = _heading(title, now) + ["```", body, "```"]
    lines += ["- note: " + error for error in errors]
    return "\n".join(lines + [""])


def _data_notes(findings: dict) -> List[str]:
    return ["", "## Data notes"] + ["- " + error for error in findings["errors"]] if findings.get("errors") else []


# --- research ----------------------------------------------------------------------------------

def india_news(title: str, now: dt.datetime, findings: dict) -> str:
    lines = _heading(title, now) + ["## Policy, rules and regulation"]
    for item in findings.get("policy", [])[:20]:
        themes = (" `" + ", ".join(item["themes"]) + "`") if item["themes"] else ""
        lines.append("- %s [%s] [%s](%s)%s" % (item["time"].strftime("%d %b %H:%M"), item["source"], item["title"][:140], item["link"], themes))
    lines += ["", "## Market headlines"]
    for item in findings.get("headlines", [])[:25]:
        tags = (" `" + ", ".join(item["tags"]) + "`") if item["tags"] else ""
        lines.append("- %s [%s](%s) (%s)%s" % (item["time"].strftime("%d %b %H:%M"), item["title"], item["link"], item["source"], tags))
    lines += ["", "## Filings the market is reacting to (F&O stocks)"]
    for row in findings.get("movers", [])[:15]:
        filing = row["filings"][0]
        lines.append("- **%s** %s: %s ([filing](%s))" % (row["symbol"], pct(row["change_pct"]) if row["change_pct"] is not None else "-",
                                                     filing["category"], filing["link"]))
    flows = findings.get("flows", {})
    lines += ["", "## Money flows"]
    fii = flows.get("fiidii")
    if fii:
        lines.append("- FII net %s cr, DII net %s cr (%s)" % (num(fii["FII"]["net"]), num((fii.get("DII") or {}).get("net")), fii.get("date")))
    lines += ["- " + note for note in (flows.get("participants") or {}).get("notes", [])]
    lines += ["", "## Results and board meetings (today / next session)"]
    lines += ["- " + event for event in findings.get("events", [])] or ["- none found"]
    lines += _data_notes(findings)
    lines += ["", "_Free, unofficial data collected by the IndiaNewsAgent. Not investment advice._", ""]
    return "\n".join(lines)


def global_news(title: str, now: dt.datetime, findings: dict) -> str:
    lines = _heading(title, now)
    mood = findings.get("mood")
    if mood:
        lines += ["## Global mood for the Indian open: %s (score %+d)" % (mood["label"].upper(), mood["score"]), ""]
        lines += ["- " + note for note in mood["notes"]]
        if mood.get("adr_avg_pct") is not None:
            lines.append("- Indian ADRs overnight: average %s" % pct(mood["adr_avg_pct"]))
        lines.append("")
    for group in findings.get("snapshot", []):
        lines += ["### %s" % group["group"], "", "| Market | Last | Change | As of (IST) |", "|---|---:|---:|---|"]
        for row in group["rows"]:
            change = pct(row["change_pct"]) + ((" (%+.1f bp)" % row["change_bp"]) if row.get("change_bp") is not None else "")
            lines.append("| %s | %s | %s | %s |" % (row["name"], num(row["last"]), change, row.get("time", "")))
        lines.append("")
    lines.append("## Economic calendar (IST)")
    for event in findings.get("calendar", []):
        lines.append("- %s %s %s (%s): forecast %s, previous %s" % (event["time"].strftime("%a %d %b %H:%M"), event["country"],
                                                                   event["event"], event["impact"], event["forecast"] or "-", event["previous"] or "-"))
    lines += ["", "## Themes and their usual India impact"]
    lines += ["- **%s** (%d stories): %s" % (t["theme"], t["count"], t["india_impact"]) for t in findings.get("themes", [])]
    lines += ["", "## Headlines"]
    for item in findings.get("headlines", [])[:30]:
        lines.append("- %s [%s](%s) `%s`" % (item["time"].strftime("%d %b %H:%M"), item["title"], item["link"], ", ".join(item["themes"])))
    lines += _data_notes(findings)
    lines += ["", "_Free, unofficial data collected by the GlobalNewsAgent. Not investment advice._", ""]
    return "\n".join(lines)


def smart_money(title: str, now: dt.datetime, findings: dict) -> str:
    return _fenced(title, now, team.smart_money(findings))


# --- analysis ----------------------------------------------------------------------------------

def market_analyst(title: str, now: dt.datetime, findings: dict) -> str:
    status = findings["status"]
    lines = _heading(title, now) + ["Market %s (%s); next open %s." % (status["state"], status["reason"],
                                                                       status["next_open"][:16].replace("T", " ")), ""]
    pulse = findings["pulse"]
    lines += ["## Snapshot", "", "| Index | Last | Change |", "|---|---:|---:|"]
    lines += ["| %s | %s | %s |" % (i["name"], num(i["last"]), pct(i["change_pct"])) for i in pulse["indices"]]
    if pulse.get("vix_note"):
        lines.append("\nIndia VIX: %s; typical Nifty day about %.2f%%." % (pulse["vix_note"], pulse["nifty_expected_daily_move_pct"]))
    if pulse["sectors"]:
        lines += ["Strongest sectors: " + sector_line(pulse["sectors"], True, 4), "Weakest sectors: " + sector_line(pulse["sectors"], False, 4)]
    for symbol, entry in findings["symbols"].items():
        lines += ["", "## %s" % symbol]
        for key in ("intraday", "daily"):
            chart = entry.get(key)
            if chart:
                lines.append("- %s trend **%s**: %s" % ("Intraday (5m)" if key == "intraday" else "Daily", chart["trend"], "; ".join(chart["signals"])))
        chain = entry.get("chain")
        if chain:
            lines.append("- Options %s: PCR %s, max pain %s, call wall %s, put wall %s, ATM IV %s, priced-in move +/- %s, positioning %s" % (
                chain["expiry"], num(chain["pcr"]), strike(chain["max_pain"]), strike(chain["resistance"][0]["strike"]),
                strike(chain["support"][0]["strike"]), ("%.1f%%" % (chain["atm_iv"] * 100)) if chain["atm_iv"] else "-",
                num(chain["expected_move"], 0), chain["bias"]))
        past = entry.get("history")
        if past:
            lines.append("- Last %d sessions: %s, %d up / %d down, average range %s pts, gaps filled %s, opening-range follow-through %s" % (
                past["sessions"], pct(past["net_change_pct"]), past["up_days"], past["down_days"], num(past["avg_range_pts"], 0),
                ("%.0f%%" % (past["gap_fill_rate"] * 100)) if past["gap_fill_rate"] is not None else "-",
                ("%.0f%%" % (past["or_follow_1x_rate"] * 100)) if past["or_follow_1x_rate"] is not None else "-"))
        if entry.get("levels"):
            lines += ["", "| Level | Source |", "|---:|---|"] + ["| %s | %s |" % (num(v), label) for v, label in entry["levels"]]
        if entry.get("scenarios"):
            lines += ["", "Scenarios:"] + ["- " + s for s in entry["scenarios"]]
    flows = findings.get("flows")
    if flows:
        lines += ["", "## Positioning (participant OI, %s)" % flows["date"]] + ["- " + note for note in flows["notes"]]
    lines += _data_notes(findings)
    lines += ["", "_Scenarios are conditional on the trigger; they are not forecasts. Not investment advice._", ""]
    return "\n".join(lines)


def chart_analyst(title: str, now: dt.datetime, findings: dict) -> str:
    return _fenced(title, now, team.timeframes(findings))


def options_strategist(title: str, now: dt.datetime, findings: dict) -> str:
    lines = _heading(title, now)
    for result in findings["symbols"].values():
        lines += ["```", team.options(result), "```", ""]
    lines += ["- " + error for error in findings["errors"]]
    return "\n".join(lines)


def stock_picker(title: str, now: dt.datetime, findings: dict) -> str:
    return _fenced(title, now, team.picks(findings))


def live_monitor(title: str, now: dt.datetime, findings: dict) -> str:
    lines = _heading(title, now)
    for symbol, result in findings["ticks"].items():
        lines += ["## %s" % symbol, "", "```", live.tick(result, findings.get("rules")), "```", ""]
    return "\n".join(lines)


# --- risk, decision, review ---------------------------------------------------------------------

def risk_manager(title: str, now: dt.datetime, findings: dict) -> str:
    return _fenced(title, now, team.risk(findings), findings.get("errors", []))


def decision_maker(title: str, now: dt.datetime, findings: dict) -> str:
    return _fenced(title, now, decisions.decision(findings["decision"]))


def performance_coach(title: str, now: dt.datetime, findings: dict) -> str:
    return _fenced(title, now, team.coach(findings))


# --- the whole team ------------------------------------------------------------------------------

def trading_desk(title: str, now: dt.datetime, findings: dict) -> str:
    lines = _heading(title, now) + ["| Stage | Agent | Time | Result |", "|---|---|---|---|"]
    for stage in findings["stages"]:
        result = "FAILED: %s" % stage["failed"] if stage.get("failed") else "%s-data.md" % stage["agent"]
        lines.append("| %s | %s | %.0fs | %s |" % (STAGE_NAMES.get(stage["agent"], "4 decision"), stage["agent"], stage["seconds"], result))
    reports = findings["reports"]
    lines += ["", "## 1. Research"] + _desk_research(reports)
    lines += ["", "## 2. Analysis"] + _desk_analysis(reports)
    lines += ["", "## 3. Risk", ""]
    lines += ["```", team.risk(reports["risk-manager"]), "```"] if reports.get("risk-manager") else ["risk check unavailable"]
    lines += ["", "## 4. Decision", ""]
    lines += ["```", decisions.decision(findings["decision"]), "```"] if findings.get("decision") else ["No decision: see the notes."]
    if findings["errors"]:
        lines += ["", "## Notes"] + ["- " + error for error in findings["errors"]]
    lines += ["", "Decision support, not advice. Confirm prices in the broker app; nothing here places an order."]
    return "\n".join(lines)


def _desk_research(reports: dict) -> List[str]:
    out: List[str] = []
    global_findings = reports.get("global-news") or {}
    mood = global_findings.get("mood")
    if mood:
        out.append("- Global mood for the open: **%s** (%+d)%s" % (mood["label"], mood["score"],
                                                                 (": " + "; ".join(mood["notes"][:4])) if mood["notes"] else ""))
    events = [e for e in global_findings.get("calendar") or [] if e.get("when") in ("today", "tomorrow") and e["impact"] == "High"]
    out += ["- High-impact event %s IST: %s %s" % (e["time"].strftime("%a %H:%M"), e["country"], e["event"]) for e in events[:4]]
    india = reports.get("india-news") or {}
    out += ["- %s (%s)" % (item["title"][:120], item.get("source", "")) for item in (india.get("headlines") or [])[:5]]
    if india.get("policy"):
        out.append("- %d policy / regulator items (RBI, SEBI, NSE): see india-news-data.md" % len(india["policy"]))
    out += ["- Company event: %s" % event for event in (india.get("events") or [])[:5]]
    out += ["- Smart money: %s" % line for line in ((reports.get("smart-money") or {}).get("verdict") or [])[:5]]
    return out or ["- research reports unavailable"]


def _desk_analysis(reports: dict) -> List[str]:
    out: List[str] = []
    for symbol, entry in ((reports.get("market-analyst") or {}).get("symbols") or {}).items():
        chain, intraday = entry.get("chain") or {}, entry.get("intraday") or {}
        out.append("- **%s** last %s; PCR %s, max pain %s" % (symbol, intraday.get("last", "-"),
                                                             "%.2f" % chain["pcr"] if chain.get("pcr") else "-", chain.get("max_pain", "-")))
        out += ["  - " + s for s in (entry.get("scenarios") or [])[:3]]
    charts = reports.get("chart-analyst") or {}
    for symbol, data in (charts.get("symbols") or {}).items():
        trends = ", ".join("%s %s" % (r["interval"], r["trend"]) for r in data["rows"])
        out.append("- Timeframes %s: **%s** (%s)" % (symbol, data["alignment"]["label"], trends))
    out += ["- %s" % note for note in charts.get("notes") or []]
    for symbol, result in ((reports.get("options-strategist") or {}).get("symbols") or {}).items():
        call, put = result.get("best_call") or {}, result.get("best_put") or {}
        out.append("- Options %s: volatility %s; expected move +/- %s today; best CALL %s CE, best PUT %s PE" % (
            symbol, result["regime"]["label"], result.get("day_move") or "-", call.get("strike", "-"), put.get("strike", "-")))
    picks = reports.get("stock-picker") or {}
    for key, word in (("longs", "long"), ("shorts", "short")):
        names = [r["symbol"] for r in (picks.get(key) or [])[:5]]
        if names:
            out.append("- F&O %s watchlist: %s" % (word, ", ".join(names)))
    return out or ["- analysis unavailable"]


# --- the daily brief -----------------------------------------------------------------------------

def brief(now: dt.datetime, data: dict) -> str:
    status = data["status"]
    lines = ["# Daily brief %s IST\n" % now.strftime("%a %d %b %Y, %H:%M"),
             "**Market:** %s (%s). Next open %s.\n" % (status["state"], status["reason"], status["next_open"][:16].replace("T", " "))]
    pulse = data["pulse"]
    lines += ["## Indices\n", "| Index | Last | Change | 30d |\n|---|---:|---:|---:|"]
    lines += ["| %s | %s | %s | %s |" % (i["name"], num(i["last"]), pct(i["change_pct"]),
                                        pct(i.get("month_change_pct")) if i.get("month_change_pct") is not None else "-") for i in pulse["indices"]]
    if pulse.get("vix_note"):
        lines.append("\nIndia VIX: %s. Nifty's typical one-day move about %.2f%%." % (pulse["vix_note"], pulse["nifty_expected_daily_move_pct"]))
    if pulse.get("breadth"):
        lines.append("Breadth (summed over NSE indices): %d advancing, %d declining." % (pulse["breadth"]["advances"], pulse["breadth"]["declines"]))
    if pulse["sectors"]:
        lines += ["\nStrongest: " + sector_line(pulse["sectors"], True, 4), "Weakest: " + sector_line(pulse["sectors"], False, 4)]
    if pulse["global"]:
        lines += ["\n## Global cues\n", ", ".join("%s %s" % (g["name"], pct(g["change_pct"])) for g in pulse["global"])]
    lines += ["\n_note: %s_" % error for error in pulse["errors"]]

    flows = data["flows"]
    lines.append("\n## Money flows\n")
    fii = flows.get("fiidii")
    if fii:
        lines.append("FII net %s cr, DII net %s cr (%s)." % (num(fii["FII"]["net"]), num((fii.get("DII") or {}).get("net")), fii.get("date")))
    lines += ["- " + note for note in (flows.get("participants") or {}).get("notes", [])]
    deals = flows.get("deals")
    if deals and deals.get("block"):
        lines.append("- Block deals: " + "; ".join("%s %s %s cr" % (d["symbol"], d["side"], num(d["value_cr"])) for d in deals["block"][:5]))
    lines += ["_note: %s_" % error for error in flows.get("errors", [])]

    lines.append("\n## Option chains\n")
    for entry in data["chains"]:
        if entry.get("error"):
            lines.append("_%s chain: %s_" % (entry["symbol"], entry["error"]))
            continue
        a = entry["analysis"]
        lines.append("**%s** spot %s, expiry %s (%.1f days): PCR %s, max pain %s, support %s, resistance %s, ATM IV %s, "
                     "priced-in move +/- %s. Positioning: %s." % (
                         entry["symbol"], num(a["spot"]), a["expiry"], a["days_to_expiry"], num(a["pcr"]), strike(a["max_pain"]),
                         "/".join(strike(x["strike"]) for x in a["support"][:2]), "/".join(strike(x["strike"]) for x in a["resistance"][:2]),
                         ("%.1f%%" % (a["atm_iv"] * 100)) if a["atm_iv"] else "-", num(a["expected_move"], 0), a["bias"]))

    events = data["events"]
    lines.append("\n## Results and board meetings (today / next session)\n")
    if events.get("error"):
        lines.append("_event calendar: %s_" % events["error"])
    else:
        lines.append(", ".join("%s %s (%s)" % (e["symbol"], e["purpose"], e["date"].strftime("%d %b")) for e in events["items"][:40])
                     or "No F&O stock events found.")

    headlines = data["headlines"]
    lines.append("\n## Headlines (last %d hours)\n" % data["hours"])
    lines += ["- %s %s [%s] %s" % (item["time"].strftime("%d %b %H:%M"), item["title"], item["source"],
                                   ("{" + ",".join(item["tags"]) + "}") if item["tags"] else "") for item in headlines["items"]]
    lines += ["_note: %s_" % error for error in headlines["errors"]]

    watchlist = data.get("watchlist")
    if watchlist and watchlist.get("hits"):
        lines.append("\n## Last scan (%s, %s)\n" % (watchlist.get("scan"), watchlist.get("time", "")[:16].replace("T", " ")))
        lines += ["- %s %s" % (hit["symbol"], ", ".join(hit.get("setups", [])) or "%s at %s" % (hit.get("side"), hit.get("trigger_time")))
                  for hit in watchlist["hits"][:12]]
    lines.append("\n_Free, unofficial data. Positioning and headlines are context, not signals. Not investment advice._")
    return "\n".join(lines)


REPORTS: Dict[str, Report] = {
    "india-news": india_news, "global-news": global_news, "smart-money": smart_money,
    "market-analyst": market_analyst, "chart-analyst": chart_analyst, "options-strategist": options_strategist,
    "stock-picker": stock_picker, "live-monitor": live_monitor, "risk-manager": risk_manager,
    "decision-maker": decision_maker, "performance-coach": performance_coach, "trading-desk": trading_desk,
}
