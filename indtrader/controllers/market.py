"""pulse, quote, chart, chain, history, flows and global."""

import datetime as dt
import logging
import os
from argparse import Namespace

from indtrader.core import clock, settings
from indtrader.core.context import AppContext
from indtrader.core.errors import IndianTraderError
from indtrader.core.formatting import inr, num, pct, print_json, strike, table
from indtrader.core.storage import read_json, write_json
from indtrader.models.agents.global_news.desk import GlobalDesk
from indtrader.models.agents.market_analyst.pulse import MarketPulse
from indtrader.models.analytics.charting import ChartAnalyzer
from indtrader.models.analytics.flows import MoneyFlows
from indtrader.models.analytics.history import MarketHistory
from indtrader.models.analytics.option_chain import OptionChainAnalyzer, OptionChainService, pick_strike
from indtrader.models.data.symbols import safe_name
from indtrader.views import market as view
from indtrader.views.chart_page import ChartPage

log = logging.getLogger(__name__)


def pulse(args: Namespace, ctx: AppContext) -> int:
    result = MarketPulse(ctx.market).collect(with_global=not args.no_global)
    status = clock.market_status(ctx.now)
    result["status"] = status
    write_json(settings.path("pulse.json"), result)
    print_json(result) if args.json else print(view.pulse(result, status))
    return 0


def quote(args: Namespace, ctx: AppContext) -> int:
    quotes, rows = {}, []
    for symbol in args.symbols:
        try:
            q = ctx.market.quote(symbol)
        except IndianTraderError as exc:
            rows.append([symbol.upper(), "error: %s" % exc, "", "", "", ""])
            continue
        quotes[symbol.upper()] = dict(q, fetched=ctx.now.isoformat(timespec="seconds"))
        rows.append([symbol.upper(), num(q["price"]), num(q["change"]), pct(q["change_pct"]),
                     "%s - %s" % (num(q["day_low"]), num(q["day_high"])), q["time"] or "-"])
    if args.write:
        path = settings.path("prices.json")
        saved = read_json(path, {}) or {}
        saved.update(quotes)
        write_json(path, saved)
    if args.json:
        print_json(quotes)
    else:
        print(table(rows, ["Symbol", "Price", "Change", "%", "Day range", "As of (IST)"]))
        print("Index quotes are the exchanges' own; stock quotes come from Yahoo and can be delayed. Check your broker before acting.")
    return 0


def chart(args: Namespace, ctx: AppContext) -> int:
    day = dt.datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else None
    analysis = ChartAnalyzer(ctx.market).analyze(args.symbol, args.interval, args.range, day, ctx.now, args.or_minutes)
    summary = {k: v for k, v in analysis.items() if k != "series"}
    write_json(settings.path("chart-%s-%s.json" % (safe_name(args.symbol), args.interval)), summary)
    if args.html:
        path = settings.path("charts", "%s-%s-%s.html" % (safe_name(args.symbol), args.interval, (analysis.get("date") or analysis["as_of"])[:10]))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(ChartPage(analysis).html())
        summary["html"] = path
    if args.json:
        print_json(summary)
    else:
        print(view.chart(analysis))
        if args.html:
            print("\nChart: %s" % os.path.abspath(summary["html"]))
    return 0


def chain(args: Namespace, ctx: AppContext) -> int:
    symbol = args.symbol.upper()
    fetched = OptionChainService(ctx.market).fetch(symbol, ctx.now, args.expiry)
    try:
        lot = ctx.market.lot_size(symbol)
    except IndianTraderError:
        lot = None
    analysis = OptionChainAnalyzer(ctx.cfg).analyze(fetched, ctx.now, lot, band=args.band)
    if args.pick:
        kind, _, choice = args.pick.partition(":")
        analysis["pick"] = pick_strike(analysis, kind, choice or "atm")
    path = settings.path("optionchain-%s.json" % symbol)
    write_json(path, analysis)
    if args.json:
        print_json(analysis)
        return 0
    print(view.chain(analysis, args.rows))
    picked = analysis.get("pick")
    if picked:
        print("\nPicked %s %s %s: premium %s (bid %s / ask %s, spread %s%%), delta %s, IV %s, theta %s/day, OI %s%s" % (
            picked["symbol"], strike(picked["strike"]), picked["kind"], num(picked["premium"]), num(picked["bid"]), num(picked["ask"]),
            num(picked["spread_pct"], 1), num(picked["delta"]), ("%.1f%%" % (picked["iv"] * 100)) if picked["iv"] else "-",
            num(picked["theta"]), picked["oi"], ("; one lot costs " + inr(picked["cost_per_lot"])) if picked.get("cost_per_lot") else ""))
    print("\nSaved %s" % path)
    return 0


def history(args: Namespace, ctx: AppContext) -> int:
    analyzer = MarketHistory(ctx.market, ctx.cfg)
    results = {}
    for symbol in args.symbols:
        summary = analyzer.analyse(symbol, args.sessions, ctx.now, args.or_minutes)
        results[symbol.upper()] = summary
        write_json(settings.path("history-%s.json" % safe_name(symbol)), summary)
        if not args.json:
            print(view.history(summary))
            print()
    if args.json:
        print_json(results)
    else:
        print("Measured from real bars; small samples, so these are tendencies, not rules.")
    return 0


def flows(args: Namespace, ctx: AppContext) -> int:
    result = MoneyFlows(ctx.market).collect(ctx.now, args.what, args.symbols)
    write_json(settings.path("flows.json"), result)
    print_json(result) if args.json else print(view.flows(result, args.limit))
    return 0


def global_view(args: Namespace, ctx: AppContext) -> int:
    result = GlobalDesk(ctx.market).collect(ctx.now, args.what, args.hours, not args.all_headlines)
    write_json(settings.path("global.json"), result)
    print_json(result) if args.json else print(view.global_view(result, ctx.now, args.limit))
    return 0
