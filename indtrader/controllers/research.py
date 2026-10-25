"""insiders, holdings, screen and tax: the investor-side research tools."""

import datetime as dt
from argparse import Namespace
from typing import Dict

from indtrader.core import settings
from indtrader.core.context import AppContext
from indtrader.core.errors import IndianTraderError, ValidationError
from indtrader.core.formatting import print_json
from indtrader.core.storage import read_json, write_json
from indtrader.models.analytics.insiders import InsiderTracker
from indtrader.models.analytics.shareholding import ShareholdingService
from indtrader.models.data.symbols import safe_name
from indtrader.models.trading import tax as tax_model
from indtrader.models.trading.scanner import Scanner
from indtrader.models.trading.screener import RuleSet, StockScreener
from indtrader.views import research as view


def insiders(args: Namespace, ctx: AppContext) -> int:
    result = InsiderTracker(ctx.market).collect(ctx.now, args.days, args.symbols, args.all, args.min_value, args.new, not args.peek)
    write_json(settings.path("insiders.json"), result)
    print_json(result) if args.json else print(view.insiders(result, args.limit))
    return 0


def holdings(args: Namespace, ctx: AppContext) -> int:
    service = ShareholdingService(ctx.market)
    if args.find:
        symbols = [s.upper() for s in args.symbols] if args.symbols else Scanner(ctx.market).universe(args.list)
        result = service.find(args.find, symbols)
        write_json(settings.path("holdings-find.json"), result)
        print_json(result) if args.json else print(view.holdings_search(result))
        return 0 if result["hits"] else 1
    if not args.symbols:
        raise ValidationError("name a stock (holdings RELIANCE) or search an investor (holdings --find NAME)")
    results = {}
    for symbol in args.symbols:
        result = service.pattern(symbol)
        results[result["symbol"]] = result
        write_json(settings.path("holdings-%s.json" % safe_name(symbol)), result)
        if not args.json:
            print(view.holdings(result, args.limit))
            print()
    if args.json:
        print_json(results)
    return 0


def screen(args: Namespace, ctx: AppContext) -> int:
    rules = RuleSet.load(args.preset, args.rules or settings.path("rules.json"))
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] if args.symbols else Scanner(ctx.market).universe(args.list)
    if args.limit:
        symbols = symbols[: args.limit]
    result = StockScreener(ctx.market, args.workers).run(rules, symbols, args.top)
    result["as_of"] = ctx.now.isoformat(timespec="minutes")
    write_json(settings.path("shortlist.json"), result)
    print_json(result) if args.json else print(view.screen(result))
    return 0 if result["passed_count"] else 1


def _prices(ctx: AppContext, symbols, given: Dict[str, float]) -> Dict[str, float]:
    prices = dict(given)
    for symbol in symbols:
        if symbol not in prices:
            try:
                prices[symbol] = ctx.market.quote(symbol)["price"]
            except IndianTraderError:
                pass
    return prices


def tax(args: Namespace, ctx: AppContext) -> int:
    rules = tax_model.tax_settings(ctx.cfg)
    today = dt.date.fromisoformat(args.date) if args.date else ctx.now.date()
    portfolio = tax_model.Portfolio(rules)
    if args.mode == "report":
        fy = args.fy or tax_model.financial_year(today)
        if args.trades:
            trades, source = tax_model.trades_from_csv(args.trades), args.trades
        else:
            journal = (read_json(settings.path("paper.json"), {"trades": []}) or {"trades": []})["trades"]
            trades, source = tax_model.trades_from_journal(journal), "paper journal"
        income = tax_model.business_income(trades, fy, rules)
        realised = portfolio.realised(fy)
        gains = tax_model.capital_gains_estimate(realised, rules)
        result = {"fy": fy, "source": source, "business": income, "capital_gains": dict(realised, **gains)}
        print_json(result) if args.json else print(view.tax_report(fy, income, realised, gains, rules, source))
        return 0
    if args.mode == "lots":
        symbols = [args.symbol.upper()] if args.symbol else portfolio.symbols()
        prices = _prices(ctx, symbols, {args.symbol.upper(): args.price} if args.symbol and args.price else {})
        rows = [dict(portfolio.lot_view(lot, prices.get(symbol), today), symbol=symbol) for symbol in symbols for lot in portfolio.lots(symbol)]
        print_json(rows) if args.json else print(view.tax_lots(rows))
        return 0
    if args.mode == "sell":
        if not (args.symbol and args.qty and args.price):
            raise ValidationError("tax sell needs SYMBOL --qty N --price P")
        preview = portfolio.sell_preview(args.symbol, args.qty, args.price, today, args.charges or 0.0)
        if args.record:
            portfolio.record_sale(preview)
        print_json(preview) if args.json else print(view.tax_sale(preview, args.record))
        return 0
    prices = _prices(ctx, portfolio.symbols(), {})
    result = tax_model.harvest(portfolio, prices, today, args.min_loss)
    print_json(result) if args.json else print(view.tax_harvest(result))
    return 0
