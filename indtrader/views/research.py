"""Terminal views for investor research: insider filings, shareholding patterns, the screener and the tax tools."""

from typing import Dict, List, Optional, Sequence

from indtrader.core.formatting import inr, num, table


def _who(trade: dict) -> str:
    return "%s (%s)" % ((trade["person"] or "-")[:38], trade["category"])


def insiders(result: dict, limit: int = 25) -> str:
    trades, summary = result["trades"], result["summary"]
    lines = ["Insider and large-holder filings, %s to %s: %d shown of %d filed" % (
        result["from"], result["to"], len(trades), result["total_filings"])]
    lines.append("Open market: %d promoter/director buys, %d sells (all insiders: bought %s, sold %s); "
                 "pledges created %d, enforced by lenders %d; %d takeover-code filings" % (
                     summary["insider_buys"], summary["insider_sells"], inr(summary["buy_value"], 0), inr(summary["sell_value"], 0),
                     summary["pledges_created"], summary["pledges_enforced"], summary["sast"]))
    if result["clusters"]:
        lines += ["", "Clusters (several insiders, same side, same company):"]
        for group in result["clusters"][:10]:
            lines.append("  %-12s %-4s %d people, %s: %s" % (group["symbol"] or group["company"][:12], group["kind"].upper(),
                                                          len(group["people"]), inr(group["value"], 0), ", ".join(p[:24] for p in group["people"][:4])))
    for kind, title in (("buy", "Open-market BUYS"), ("sell", "Open-market SELLS"), ("pledge", "Pledges"),
                        ("trust", "Employee-trust trades (shares for staff stock options, not insiders' own money)")):
        rows = [t for t in trades if t["source"] == "PIT" and t["kind"] == kind]
        if rows:
            rows.sort(key=lambda t: -(t["value"] or 0))
            lines += ["", "%s (insider-trading filings):" % title]
            lines.append(table([[("*" if t["new"] else "") + (t["symbol"] or "BSE:%s" % t["bse_code"]), _who(t), t["mode"],
                                 num(t["qty"], 0), num(t["price"]), inr(t["value"], 0), t["traded_to"] or "-", (t["filed"] or "")[:10]]
                                for t in rows[:limit]],
                               ["Symbol", "Who", "Mode", "Qty", "Avg price", "Value", "Traded", "Filed"], "lllrrrll"))
            for t in rows[:limit]:
                for filing in t.get("linked") or []:
                    lines.append("  ! %s (%s) is also named in a later filing: %s, %s" % (
                        t["person"], t["symbol"], filing["category"], (filing["filed"] or "")[:16]))
    sast = [t for t in trades if t["source"] == "SAST"]
    if sast:
        lines += ["", "Takeover-code filings (crossing 5%, or a 2% change):"]
        lines.append(table([[("*" if t["new"] else "") + (t["symbol"] or "-"), (t["person"] or "-")[:46], t["side"], t["mode"],
                             num(t["pct_change"]) + "%", num(t["pct_after"]) + "%", (t["filed"] or "")[:16]] for t in sast[:limit]],
                           ["Symbol", "Who", "Side", "Mode", "Change", "Holds now", "Filed"], "llllrrl"))
    other = result["total_filings"] - len(trades)
    if other > 0:
        lines.append("\n%d other filings hidden (ESOP, allotment, gift, inter-se transfer, off-market): add --all to see them." % other)
    lines += ["note: " + error for error in result["errors"]]
    lines.append("* = new since the last run. Insider buying is context, not a trade signal; the filing comes up to two days after the trade.")
    return "\n".join(lines)


def _change(value: Optional[float]) -> str:
    return "-" if value is None else "%+.2f" % value


def holdings(result: dict, limit: int = 20) -> str:
    lines = ["%s (%s): shareholding at %s, filed %s" % (result["company"], result["symbol"], result["quarter"], result["filed"] or "-")]
    previous = result["previous_quarter"]
    lines.append(table([[r["label"], num(r["pct"]) + "%", (num(r["before"]) + "%") if r["before"] is not None else "-", _change(r["change"])]
                        for r in result["categories"]],
                       ["Category", "Now", previous or "Before", "Change (pts)"], "lrrr"))
    trend = [t for t in result["promoter_trend"] if t["promoters"] is not None]
    if len(trend) > 1:
        months = [t["quarter"][:7] for t in trend]
        lines.append("Promoter holding by quarter: " + ", ".join(
            "%s %s%%" % (t["quarter"] if months.count(t["quarter"][:7]) > 1 else t["quarter"][:7], num(t["promoters"])) for t in trend))
    public = [h for h in result["holders"] if not h["promoter"]]
    if public:
        lines += ["", "Named public holders over 1%:"]
        lines.append(table([[h["name"][:48], h["category"][:30], num(h["pct"]) + "%" if h["pct"] is not None else "-",
                             _change(h["change"]), h["status"]] for h in public[:limit]],
                           ["Holder", "Category", "Now", "Change", "Status"], "llrrl"))
    promoters = [h for h in result["holders"] if h["promoter"] and (h["change"] or h["status"] != "held")]
    if promoters:
        lines += ["", "Promoter entities that changed:"]
        lines += ["  %-48s %s -> %s" % (h["name"][:48], num(h["before"]), num(h["pct"])) for h in promoters[:limit]]
    lines.append("Holdings at the quarter end, filed up to 21 days later. A rising FII / MF share is context, not a signal.")
    return "\n".join(lines)


def holdings_search(result: dict) -> str:
    if not result["hits"]:
        lines = ["No holder matching %r over 1%% in %d stocks searched." % (result["name"], result["searched"])]
    else:
        lines = ["Holders matching %r (over 1%%), %d stocks searched:" % (result["name"], result["searched"])]
        lines.append(table([[h["symbol"], h["name"][:48], h["category"][:30], num(h["pct"]) + "%", h["quarter"]] for h in result["hits"]],
                           ["Symbol", "Holder", "Category", "Holds", "Quarter"], "lllrl"))
    if result["errors"]:
        lines.append("%d stocks could not be read (first: %s)" % (len(result["errors"]), result["errors"][0]))
    lines.append("Only holdings over 1% are named in the filings; smaller stakes are invisible.")
    return "\n".join(lines)


def _cell(value) -> str:
    return num(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else str(value or "-")


def screen(result: dict, columns: Sequence[str] = ("price", "change_pct", "pe", "pe_vs_sector", "delivery_pct", "ret_20d", "rsi")) -> str:
    lines = ["%s: %d of %d stocks pass" % (result["name"], result["passed_count"], result["screened"]),
             "Rules: " + "; ".join(result["rules"])]
    if result["passed"]:
        rows = [[i, r["symbol"], num(r["score"], 2)] + [_cell(r["metrics"].get(c)) for c in columns] + [(r["metrics"].get("sector") or "-")[:22]]
                for i, r in enumerate(result["passed"], 1)]
        lines.append(table(rows, ["#", "Symbol", "Score"] + list(columns) + ["Sector"], "rlr" + "r" * len(columns) + "l"))
    else:
        lines.append("Nothing passed. Closest misses:")
    for miss in result["closest_misses"] if not result["passed"] else result["closest_misses"][:3]:
        lines.append("  FAIL %-12s %s" % (miss["symbol"], "; ".join(miss["failures"])))
    if result["unreadable"]:
        lines.append("%d symbols had no NSE data: %s" % (len(result["unreadable"]), ", ".join(result["unreadable"][:10])))
    lines.append("A screen filters numbers; it is not a buy list. NSE P/E is trailing and the delivery share is today's.")
    return "\n".join(lines)


NOT_ADVICE = "Not tax advice: the numbers a CA asks for, not what you owe. Check rates and rules with a tax professional."


def tax_report(fy: str, income: Dict[str, dict], realised: dict, gains: dict, tax: dict, source: str) -> str:
    fno, intraday = income["fno"], income["intraday"]
    lines = ["Tax summary, FY %s (%s)" % (fy, source), ""]
    def row(label: str, seg: dict) -> list:
        return [label, seg["trades"], inr(seg["turnover"], 0), inr(seg["gross"], 0, True), inr(seg["charges"], 0), inr(seg["net"], 0, True)]

    lines.append(table([row("F&O (non-speculative business)", fno), row("Intraday equity (speculative)", intraday)],
                       ["Segment", "Trades", "Turnover", "Gross", "Charges", "Net"], "lrrrrr"))
    lines.append("Turnover = sum of each trade's absolute profit or loss (ICAI Guidance Note). Charges, STT included, are business expenses.")
    if fno["audit_likely"]:
        lines.append("F&O turnover is over %s: a tax audit (s.44AB) applies. Talk to a CA before the filing season." % inr(tax["audit_turnover_digital"], 0))
    elif fno["trades"] and fno["net"] < 0:
        lines.append("F&O loss: it offsets other income except salary this year, and carries forward 8 years if the ITR is filed on time. "
                     "With a loss, an audit can still apply in some cases (s.44AD/44AB): ask a CA.")
    if intraday["trades"] and intraday["net"] < 0:
        lines.append("Speculative (intraday) loss: offsets only speculative income, carried forward 4 years.")
    lines += ["", "Delivery capital gains realised (logged with `tax sell --record`): %d sales" % realised["sales"]]
    lines.append("  short-term %s, long-term %s; exemption used %s of %s; taxable long-term %s" % (
        inr(gains["net_short_term"], 0, True), inr(gains["net_long_term"], 0, True), inr(gains["exemption_used"], 0),
        inr(tax["ltcg_exemption"], 0), inr(gains["taxable_long_term"], 0)))
    lines.append("  at %s%% STCG / %s%% LTCG that is about %s before surcharge and 4%% cess" % (
        num(tax["stcg_pct"], 1), num(tax["ltcg_pct"], 1), inr(gains["tax_at_listed_rates"], 0)))
    if gains["carry_forward_loss"]:
        lines.append("  capital loss to carry forward: %s (8 years, ITR filed on time; long-term losses offset only long-term gains)"
                     % inr(gains["carry_forward_loss"], 0))
    lines.append("Business income is taxed at your slab rate with your other income, so no figure is given for it.")
    lines.append(NOT_ADVICE)
    return "\n".join(lines)


def tax_lots(rows: List[dict]) -> str:
    if not rows:
        return "No delivery lots in portfolio.json."
    out = table([[r["symbol"], r["id"] or "-", r["date"], num(r["qty"], 0), inr(r["cost"], 0), inr(r["value"], 0) if r["value"] is not None else "-",
                  inr(r["gain"], 0, True) if r["gain"] is not None else "-", r["term"], r["long_term_from"]] for r in rows],
                ["Symbol", "Lot", "Bought", "Qty", "Cost", "Value", "Gain", "Term", "Long-term from"], "lllrrrrll")
    return out + "\n" + NOT_ADVICE


def tax_sale(preview: dict, recorded: bool) -> str:
    lines = ["Selling %s %s at %s on %s (FIFO):" % (num(preview["qty"], 0), preview["symbol"], num(preview["price"]), preview["date"])]
    lines.append(table([[p["lot"] or "-", p["date"], num(p["qty"], 0), inr(p["cost"], 0), inr(p["proceeds"], 0), inr(p["gain"], 0, True), p["term"]]
                        for p in preview["parts"]], ["Lot", "Bought", "Qty", "Cost", "Proceeds", "Gain", "Term"], "llrrrrl"))
    lines.append("Realises short-term %s and long-term %s in FY %s." % (inr(preview["short_term"], 0, True), inr(preview["long_term"], 0, True), preview["fy"]))
    lines.append("Recorded: lots updated and the gain logged." if recorded else "Preview only. After the sale fills, run again with --record.")
    lines.append(NOT_ADVICE)
    return "\n".join(lines)


def tax_harvest(result: dict) -> str:
    lines = ["Tax harvesting, FY %s" % result["fy"]]
    if result["losses"]:
        lines.append("Lots at a loss (selling books the loss against this year's gains):")
        lines += ["  %-12s %s bought %s, %s, %s" % (v["symbol"], v["id"] or "-", v["date"], inr(v["gain"], 0, True), v["term"] + "-term")
                  for v in result["losses"]]
    else:
        lines.append("No lots at a loss above the threshold.")
    lines.append("Long-term exemption left this year: %s." % inr(result["exemption_room"], 0))
    if result["exempt_gains"]:
        lines.append("Long-term gains that fit inside it (sell and buy back to reset the cost, tax-free):")
        lines += ["  %-12s %s bought %s, gain %s" % (v["symbol"], v["id"] or "-", v["date"], inr(v["gain"], 0)) for v in result["exempt_gains"]]
        lines.append("  total %s. Buy back on the next trading day: a same-day sell and buy can be netted as intraday." % inr(result["exempt_total"], 0))
    lines.append("India has no wash-sale rule, but a sale must be a real sale. " + NOT_ADVICE)
    return "\n".join(lines)
