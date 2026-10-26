"""Terminal views for Indian news: headlines, filings ranked by move, and policy updates."""

import datetime as dt
from typing import List

from indtrader.core.formatting import pct


def news(result: dict, now: dt.datetime) -> str:
    if result.get("dated"):
        window = "from %s to %s" % (result["since"].strftime("%d %b %Y"), result["until"].strftime("%d %b %Y"))
    else:
        window = "for the last %d hours" % result["hours"]
    lines = ["News %s, as of %s IST. Watching: %s" % (window, now.strftime("%d %b %H:%M"), ", ".join(result["tickers"]) or "market only")]
    if result.get("terms"):
        lines.append("Searched as: " + "; ".join("%s = %s" % (t, " / ".join(names)) for t, names in result["terms"].items()))
    if result["moves"]:
        lines.append("Today: " + "   ".join("%s %s (%s)" % (t, "%.2f" % q["price"] if q["price"] else "-", pct(q["change_pct"]))
                                          for t, q in result["moves"].items()))
    lines.append("")
    if not result["items"]:
        if result.get("found"):
            lines.append("Nothing new (%d items in the window were already shown; --all shows them)." % result["found"])
        else:
            lines.append("No items found in the window.")
    for item in result["items"]:
        mood = "+" if item["sentiment"] > 0.2 else "-" if item["sentiment"] < -0.2 else " "
        tickers = (" [" + ",".join(item["tickers"]) + "]") if item["tickers"] else ""
        tags = (" {" + ",".join(item["tags"]) + "}") if item["tags"] else ""
        similar = (" (+%d similar)" % item["similar"]) if item.get("similar") else ""
        lines.append("%s %s %s%s%s%s" % (item["time"].strftime("%d %b %H:%M"), mood, item["title"], tickers, tags, similar))
        lines.append("      %s  %s" % (item["source"], item["link"][:110]))
    lines += ["note: " + error for error in result["errors"]]
    lines += ["", "+/- is a word-list mood score, not a verdict. Headlines are leads: open the story before acting."]
    return "\n".join(lines)


def movers(ranked: List[dict], hours: int, any_company: bool) -> str:
    lines = ["NSE filings in the last %d hours, %s, ranked by today's move:" % (hours, "all companies" if any_company else "F&O stocks")]
    if not ranked:
        lines.append("None.")
    for row in ranked:
        lines.append("\n%s  %s  %s  {%s}" % (row["symbol"], pct(row["change_pct"]) if row["change_pct"] is not None else "-",
                                            ("%.2f" % row["price"]) if row["price"] else "", ",".join(row["tags"])))
        for filing in row["filings"][:3]:
            lines.append("   %s  %s: %s" % (filing["time"].strftime("%d %b %H:%M"), filing["category"], filing["text"][:150]))
            lines.append("      %s" % filing["link"])
    lines.append("\nA filing plus a big move is a lead. Read the filing before trading it.")
    return "\n".join(lines)


def policy(result: dict) -> str:
    lines = ["Policy, regulation and economy: RBI, SEBI, NSE circulars, ET / BS economy, since %s IST"
             % result["since"].strftime("%d %b %H:%M")]
    if not result["items"]:
        lines.append("Nothing in the window.")
    for item in result["items"]:
        themes = (" {" + ",".join(item["themes"]) + "}") if item["themes"] else ""
        lines.append("%s  [%s] %s%s" % (item["time"].strftime("%d %b %H:%M"), item["source"], item["title"][:150], themes))
        lines.append("      %s" % item["link"][:110])
    lines += ["note: " + error for error in result["errors"]]
    lines.append("\nOpen the circular or press release before acting: headlines and themes are pointers.")
    return "\n".join(lines)
