"""The MCP tools: name, description, JSON Schema for the arguments, handler.

Handlers receive a fresh :class:`AppContext` (current clock and settings)
and the validated arguments, and return JSON-able data. They never print.
"""

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List

from indtrader.core import clock, settings
from indtrader.core.context import AppContext
from indtrader.core.errors import ValidationError
from indtrader.core.storage import read_json
from indtrader.models.agents import REGISTRY
from indtrader.models.agents.decision_maker.decider import Decider
from indtrader.models.agents.global_news.desk import GlobalDesk
from indtrader.models.agents.india_news.desk import NewsDesk, NewsQuery
from indtrader.models.agents.live_monitor.monitor import LiveMonitor, serialise_events, stats
from indtrader.models.agents.market_analyst.pulse import MarketPulse
from indtrader.models.analytics.charting import ChartAnalyzer
from indtrader.models.analytics.flows import MoneyFlows
from indtrader.models.analytics.history import MarketHistory
from indtrader.models.analytics.insiders import InsiderTracker
from indtrader.models.analytics.option_chain import OptionChainAnalyzer, OptionChainService
from indtrader.models.analytics.shareholding import ShareholdingService
from indtrader.models.trading.charges import KINDS, charges
from indtrader.models.trading.scanner import Scanner
from indtrader.models.trading.screener import PRESETS, RuleSet, StockScreener
from indtrader.models.trading.sizing import PositionSizer
from indtrader.models.trading.tax import (Portfolio, business_income, capital_gains_estimate, financial_year, tax_settings,
                                          trades_from_journal)
from indtrader.views import live as live_view
from indtrader.controllers.agents import run_agent as run_agent_report

log = logging.getLogger(__name__)

Handler = Callable[[AppContext, Dict[str, Any]], Any]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    schema: Dict[str, Any]
    handler: Handler

    def describe(self) -> Dict[str, Any]:
        return {"name": self.name, "description": self.description, "inputSchema": self.schema}


def _schema(properties: Dict[str, Any] = None, required: List[str] = None) -> Dict[str, Any]:
    return {"type": "object", "properties": properties or {}, "required": required or [], "additionalProperties": False}


SYMBOL = {"type": "string", "description": "NSE symbol or index: NIFTY, BANKNIFTY, FINNIFTY, SENSEX, RELIANCE ..."}
HOURS = {"type": "integer", "minimum": 1, "maximum": 168}


# --- handlers ---------------------------------------------------------------------

def market_status(ctx: AppContext, args: Dict[str, Any]) -> Any:
    return clock.market_status(ctx.now)


def market_pulse(ctx: AppContext, args: Dict[str, Any]) -> Any:
    return MarketPulse(ctx.market).collect(with_global=args.get("include_global", True))


def quotes(ctx: AppContext, args: Dict[str, Any]) -> Any:
    return {symbol.upper(): ctx.market.quote(symbol) for symbol in args["symbols"]}


def option_chain(ctx: AppContext, args: Dict[str, Any]) -> Any:
    symbol = args["symbol"].upper()
    chain = OptionChainService(ctx.market).fetch(symbol, ctx.now, args.get("expiry", "near"))
    analysis = OptionChainAnalyzer(ctx.cfg).analyze(chain, ctx.now, ctx.market.lot_size(symbol), band=args.get("band", 5))
    return analysis


def chart_analysis(ctx: AppContext, args: Dict[str, Any]) -> Any:
    day = dt.date.fromisoformat(args["date"]) if args.get("date") else None
    analysis = ChartAnalyzer(ctx.market).analyze(args["symbol"], args.get("interval", "5m"), args.get("range"), day, ctx.now)
    analysis.pop("series", None)
    return analysis


def market_history(ctx: AppContext, args: Dict[str, Any]) -> Any:
    return MarketHistory(ctx.market, ctx.cfg).analyse(args["symbol"], args.get("sessions", 22), ctx.now)


def money_flows(ctx: AppContext, args: Dict[str, Any]) -> Any:
    return MoneyFlows(ctx.market).collect(ctx.now, args.get("what", "all"))


def india_news(ctx: AppContext, args: Dict[str, Any]) -> Any:
    query = NewsQuery(tickers=args.get("tickers"), hours=args.get("hours", 12), show_seen=True, mark_seen=False,
                      market=not args.get("stocks_only", False), stocks=not args.get("market_only", False), limit=args.get("limit", 40))
    return NewsDesk(ctx.market, ctx.cfg).news(query, ctx.now)


def news_movers(ctx: AppContext, args: Dict[str, Any]) -> Any:
    return NewsDesk(ctx.market, ctx.cfg).movers(ctx.now, args.get("hours", 24), args.get("any_company", False), args.get("limit", 30))


def policy_updates(ctx: AppContext, args: Dict[str, Any]) -> Any:
    return NewsDesk(ctx.market, ctx.cfg).policy(ctx.now, args.get("hours", 24), args.get("themes"), args.get("limit", 40))


def global_view(ctx: AppContext, args: Dict[str, Any]) -> Any:
    return GlobalDesk(ctx.market).collect(ctx.now, args.get("what", "all"), args.get("hours", 18), not args.get("all_headlines", False))


def scan_daily(ctx: AppContext, args: Dict[str, Any]) -> Any:
    scanner = Scanner(ctx.market)
    symbols = [s.upper() for s in args["symbols"]] if args.get("symbols") else scanner.universe(args.get("list", "fo"))
    hits, skipped = scanner.daily(symbols)
    return {"hits": hits[: args.get("top", 30)], "scanned": len(symbols), "skipped": skipped}


def scan_orb(ctx: AppContext, args: Dict[str, Any]) -> Any:
    scanner = Scanner(ctx.market)
    symbols = [s.upper() for s in args["symbols"]] if args.get("symbols") else scanner.universe(args.get("list", "fo"))
    hits, scanned, missing = scanner.opening_range(symbols, ctx.now, ctx.now.date(), args.get("or_minutes", 15))
    return {"hits": hits, "scanned": scanned, "missing": missing}


def live_tick(ctx: AppContext, args: Dict[str, Any]) -> Any:
    result = LiveMonitor(ctx).tick(args.get("symbol", "NIFTY").upper())
    return {"status": live_view.tick(result, ctx.cfg), "events": serialise_events(result.events)}


def trade_decision(ctx: AppContext, args: Dict[str, Any]) -> Any:
    decider = Decider(ctx)
    mode, symbol = args.get("mode", "now"), args.get("symbol", "NIFTY")
    if mode == "backtest":
        return decider.backtest(symbol, args.get("sessions", 58))
    return (decider.plan(symbol) if mode == "plan" else decider.decide(symbol)).as_dict()


def live_backtest(ctx: AppContext, args: Dict[str, Any]) -> Any:
    days, trades = LiveMonitor(ctx).backtest(args.get("symbol", "NIFTY").upper(), args.get("sessions", 40))
    return {"sessions": len(days), "from": days[0].isoformat() if days else None, "to": days[-1].isoformat() if days else None,
            "stats": stats(trades)}


def run_agent(ctx: AppContext, args: Dict[str, Any]) -> Any:
    name = args["name"]
    if name not in REGISTRY:
        raise ValidationError("unknown agent %r (%s)" % (name, ", ".join(sorted(REGISTRY))))
    report = run_agent_report(ctx, name, write=True)
    return {"agent": report.agent, "path": report.path, "seconds": report.seconds, "errors": report.errors, "markdown": report.markdown}


def insider_trades(ctx: AppContext, args: Dict[str, Any]) -> Any:
    return InsiderTracker(ctx.market).collect(ctx.now, args.get("days", 7), args.get("symbols"), args.get("include_other", False),
                                              args.get("min_value", 0), only_new=False, mark_seen=False)


def shareholding(ctx: AppContext, args: Dict[str, Any]) -> Any:
    service = ShareholdingService(ctx.market)
    if args.get("find"):
        symbols = [s.upper() for s in args["symbols"]] if args.get("symbols") else Scanner(ctx.market).universe(args.get("list", "nifty50"))
        return service.find(args["find"], symbols)
    if not args.get("symbols"):
        raise ValidationError("give symbols, or find with an investor name")
    return {symbol.upper(): service.pattern(symbol) for symbol in args["symbols"]}


def screen_stocks(ctx: AppContext, args: Dict[str, Any]) -> Any:
    rules = RuleSet.from_dict(args["rules"]) if args.get("rules") else RuleSet.load(args.get("preset", "momentum"))
    symbols = [s.upper() for s in args["symbols"]] if args.get("symbols") else Scanner(ctx.market).universe(args.get("list", "nifty50"))
    return StockScreener(ctx.market).run(rules, symbols, args.get("top", 20))


def tax_report(ctx: AppContext, args: Dict[str, Any]) -> Any:
    rules = tax_settings(ctx.cfg)
    fy = args.get("fy") or financial_year(ctx.now.date())
    journal = (read_json(settings.path("paper.json"), {"trades": []}) or {"trades": []})["trades"]
    realised = Portfolio(rules).realised(fy)
    return {"fy": fy, "business": business_income(trades_from_journal(journal), fy, rules),
            "capital_gains": dict(realised, **capital_gains_estimate(realised, rules)),
            "note": "Not tax advice. Business income is taxed at the slab rate; no tax figure is given for it."}


def trade_charges(ctx: AppContext, args: Dict[str, Any]) -> Any:
    quantity = args.get("qty", 1)
    result = charges(args["type"], args["buy"] * quantity, args["sell"] * quantity, ctx.cfg)
    gross = (args["sell"] - args["buy"]) * quantity
    return dict(result, gross=round(gross, 2), net=round(gross - result["total"], 2))


def profit_target(ctx: AppContext, args: Dict[str, Any]) -> Any:
    plan = read_json(settings.path("plan.json"))
    if not plan:
        raise ValidationError("no plan: make one with it.py plan make first")
    return PositionSizer(ctx.cfg).target_table(plan, args["profit"])


TOOLS: List[Tool] = [
    Tool("market_status", "Is NSE open? The IST clock, the reason and the next open.", _schema(), market_status),
    Tool("market_pulse", "Indian indices (Nifty, Sensex, Bank Nifty ...), India VIX, sector ranking, breadth and global cues.",
         _schema({"include_global": {"type": "boolean"}}), market_pulse),
    Tool("quote", "Last price and change for NSE/BSE symbols and indices (official NSE/BSE data for indices).",
         _schema({"symbols": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 20}}, ["symbols"]), quotes),
    Tool("option_chain", "NSE option chain analytics: PCR, max pain, OI walls, OI written today, ATM IV, priced-in move, Greeks near the money.",
         _schema({"symbol": SYMBOL, "expiry": {"type": "string", "description": "near, next, monthly or YYYY-MM-DD"},
                  "band": {"type": "integer", "minimum": 1, "maximum": 20}}, ["symbol"]), option_chain),
    Tool("chart_analysis", "Technical analysis: VWAP, EMAs, SuperTrend, RSI, MACD, ATR, opening range, pivots/CPR (and next-session levels after the close).",
         _schema({"symbol": SYMBOL, "interval": {"type": "string", "enum": ["1m", "5m", "15m", "1h", "1d"]},
                  "range": {"type": "string"}, "date": {"type": "string", "description": "YYYY-MM-DD (intraday session)"}}, ["symbol"]),
         chart_analysis),
    Tool("market_history", "How the market moved over the last N sessions: up/down days, ranges, gaps, day types, "
                           "opening-range behaviour, timing of highs and lows.",
         _schema({"symbol": SYMBOL, "sessions": {"type": "integer", "minimum": 5, "maximum": 55}}, ["symbol"]), market_history),
    Tool("money_flows", "FII/DII cash flows, participant open interest (FII long/short in index futures) and bulk/block deals.",
         _schema({"what": {"type": "string", "enum": ["all", "fiidii", "participants", "deals"]}}), money_flows),
    Tool("india_news", "Indian market headlines and company filings, tagged and matched to tickers (does not mark items as seen).",
         _schema({"tickers": {"type": "array", "items": {"type": "string"}}, "hours": HOURS, "market_only": {"type": "boolean"},
                  "stocks_only": {"type": "boolean"}, "limit": {"type": "integer", "minimum": 1, "maximum": 200}}), india_news),
    Tool("news_movers", "Today's NSE filings ranked by each stock's move (F&O stocks unless any_company).",
         _schema({"hours": HOURS, "any_company": {"type": "boolean"}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}), news_movers),
    Tool("policy_updates", "RBI, SEBI and NSE circulars and economy news, tagged by theme (rates, liquidity, F&O rules, bans, tax, trade).",
         _schema({"hours": HOURS, "themes": {"type": "array", "items": {"type": "string"}},
                  "limit": {"type": "integer", "minimum": 1, "maximum": 200}}), policy_updates),
    Tool("global_view", "US/global overnight snapshot with a mood score for the Indian open, the economic calendar (IST) "
                        "and themed headlines with India impact.",
         _schema({"what": {"type": "string", "enum": ["all", "snapshot", "calendar", "headlines"]}, "hours": HOURS,
                  "all_headlines": {"type": "boolean"}}), global_view),
    Tool("scan_daily", "Daily setups across F&O stocks or an index list: 20-day breakouts/breakdowns, flags, 20-day average crosses, RSI extremes.",
         _schema({"list": {"type": "string"}, "symbols": {"type": "array", "items": {"type": "string"}},
                  "top": {"type": "integer", "minimum": 1, "maximum": 200}}), scan_daily),
    Tool("scan_orb", "Opening-range breakouts so far today on 5-minute bars, both directions.",
         _schema({"list": {"type": "string"}, "symbols": {"type": "array", "items": {"type": "string"}},
                  "or_minutes": {"type": "integer", "enum": [5, 10, 15, 30]}}), scan_orb),
    Tool("live_tick", "One live-monitor check: processes new closed candles and reports ENTRY / EXIT signals with the ATM option.",
         _schema({"symbol": SYMBOL}), live_tick),
    Tool("trade_decision", "THE intraday decision for NIFTY: BUY CALL / BUY PUT (with the option, limit, stop, target), HOLD, EXIT, "
                           "WAIT (with the exact triggers), NO TRADE or DONE, with confidence from global markets, option chain, "
                           "FII positioning, trend and the open. mode 'plan' gives the day plan; 'backtest' the rules' record.",
         _schema({"mode": {"type": "string", "enum": ["now", "plan", "backtest"]}, "symbol": SYMBOL,
                  "sessions": {"type": "integer", "minimum": 10, "maximum": 58}}), trade_decision),
    Tool("live_backtest", "The live rules' record on recent sessions (index points and R, before option decay and charges).",
         _schema({"symbol": SYMBOL, "sessions": {"type": "integer", "minimum": 5, "maximum": 58}}), live_backtest),
    Tool("run_agent", "Run one agent and save its report (trading-desk runs the whole team).",
         _schema({"name": {"type": "string", "enum": sorted(REGISTRY)}}, ["name"]), run_agent),
    Tool("insider_trades", "Insider (SEBI PIT) and takeover-code (SAST) filings: promoters and directors buying or selling in the open "
                           "market, clusters, pledges created or enforced, holders crossing 5%. Personal data is never returned.",
         _schema({"days": {"type": "integer", "minimum": 1, "maximum": 30}, "symbols": {"type": "array", "items": {"type": "string"}},
                  "include_other": {"type": "boolean", "description": "also ESOP, allotment, gift, inter-se, off-market"},
                  "min_value": {"type": "number", "minimum": 0}}), insider_trades),
    Tool("shareholding", "Shareholding pattern per stock (promoters, FII, DII, mutual funds, retail; named holders over 1%; "
                         "change vs last quarter), or find an investor's name across a list of stocks.",
         _schema({"symbols": {"type": "array", "items": {"type": "string"}, "maxItems": 200},
                  "find": {"type": "string", "minLength": 3}, "list": {"type": "string"}}), shareholding),
    Tool("screen_stocks", "Screen stocks on rules over NSE data (P/E, P/E vs sector, delivery %, 52-week range, volatility) and daily "
                          "technicals (returns, RSI, EMA distance). Presets: " + ", ".join(sorted(PRESETS)) + ".",
         _schema({"preset": {"type": "string", "enum": sorted(PRESETS)}, "rules": {"type": "object"},
                  "list": {"type": "string"}, "symbols": {"type": "array", "items": {"type": "string"}},
                  "top": {"type": "integer", "minimum": 1, "maximum": 100}}), screen_stocks),
    Tool("tax_report", "Indian tax arithmetic for a financial year: F&O and intraday turnover and P&L from the paper journal, "
                       "realised capital gains and the long-term exemption used. Not tax advice.",
         _schema({"fy": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}$"}}), tax_report),
    Tool("charges", "Full Indian trading costs (brokerage, STT, exchange, SEBI, stamp, GST) for a round trip.",
         _schema({"type": {"type": "string", "enum": list(KINDS)}, "buy": {"type": "number", "exclusiveMinimum": 0},
                  "sell": {"type": "number", "exclusiveMinimum": 0}, "qty": {"type": "integer", "minimum": 1}}, ["type", "buy", "sell"]),
         trade_charges),
    Tool("profit_target", "For the current plan: the move needed and the loss at the stop for a profit goal with 1-40 lots.",
         _schema({"profit": {"type": "number", "exclusiveMinimum": 0}}, ["profit"]), profit_target),
]

BY_NAME: Dict[str, Tool] = {tool.name: tool for tool in TOOLS}
