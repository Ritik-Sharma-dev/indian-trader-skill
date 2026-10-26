"""The argument parser. Each sub-command sets ``handler`` to its function.

Command names and flags are a public interface: the skills, the Claude
agents and the live loop call them. Change them only together with those.
"""

import argparse
from argparse import Namespace

from indtrader.models.agents import REGISTRY
from indtrader.models.trading.charges import KINDS
from indtrader.models.trading.screener import PRESETS
from indtrader.controllers import market, news, reports, research, system, trading


def serve_mcp(args: Namespace, ctx) -> int:
    """``it.py mcp``: hand stdin / stdout to the MCP server until the client disconnects."""
    from indtrader.mcp.server import McpServer      # imported on demand: only this command needs the server

    McpServer(offline=args.offline, now=args.now).serve()
    return 0


def _common() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--offline", metavar="DIR", help="read saved responses from DIR instead of the network")
    common.add_argument("--now", metavar="'YYYY-MM-DD HH:MM'", help="pin the IST clock (replays, tests)")
    common.add_argument("--json", action="store_true", help="machine-readable output")
    common.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="file log level (default INFO)")
    return common


def build_parser() -> argparse.ArgumentParser:
    common = _common()
    parser = argparse.ArgumentParser(prog="it.py", description="Indian Trader: NSE/BSE analysis tools. Never places orders.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def command(name: str, handler, help_text: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, parents=[common], help=help_text)
        p.set_defaults(handler=handler)
        return p

    _system(command)
    _market(command)
    _news(command)
    _trading(command)
    _research(command)
    _reports(command)
    return parser


def _system(command) -> None:
    p = command("config", system.config, "show or create workspace/config.json")
    p.add_argument("mode", choices=["show", "init", "path"])
    p.add_argument("--force", action="store_true")
    command("refresh", system.refresh, "refresh NSE holidays and lot sizes")
    command("clock", system.show_clock, "is NSE open? next open, holidays")
    p = command("agent", system.run_agent, "run a data agent and save its report")
    p.add_argument("action", choices=["run"])
    p.add_argument("name", choices=sorted(REGISTRY) + ["all"])
    p.add_argument("--print", action="store_true", help="print the report instead of the path")
    p.add_argument("--no-write", action="store_true")
    command("mcp", serve_mcp, "run the MCP server on stdio (for Claude)")


def _market(command) -> None:
    p = command("pulse", market.pulse, "indices, VIX, sectors, breadth, global cues")
    p.add_argument("--no-global", action="store_true")
    p = command("quote", market.quote, "quotes for symbols")
    p.add_argument("symbols", nargs="+")
    p.add_argument("--write", action="store_true", help="save to workspace/prices.json")
    p = command("chart", market.chart, "indicators, levels and an HTML chart")
    p.add_argument("symbol")
    p.add_argument("--interval", default="5m", help="1m, 5m, 15m, 1h, 1d")
    p.add_argument("--range", help="Yahoo range: 1d, 5d, 1mo, 60d, 1y ...")
    p.add_argument("--date", help="intraday: which session, YYYY-MM-DD")
    p.add_argument("--or-minutes", type=int, default=15)
    p.add_argument("--html", action="store_true", help="write an HTML chart to workspace/charts/")
    p = command("chain", market.chain, "option chain analytics")
    p.add_argument("symbol")
    p.add_argument("--expiry", default="near", help="near, next, monthly or YYYY-MM-DD")
    p.add_argument("--band", type=int, default=10, help="strikes each side of ATM to analyse")
    p.add_argument("--rows", type=int, default=6, help="strikes each side to print")
    p.add_argument("--pick", help="CE:atm, PE:otm1, CE:22700 ...")
    p = command("history", market.history, "how the market moved over the last month: days, gaps, ranges, timing")
    p.add_argument("symbols", nargs="*", default=["NIFTY", "BANKNIFTY"])
    p.add_argument("--sessions", type=int, default=22, help="trading sessions (22 = about a month)")
    p.add_argument("--or-minutes", type=int, default=15)
    p = command("flows", market.flows, "FII/DII, participant OI, bulk/block deals")
    p.add_argument("what", nargs="?", default="all", choices=["all", "fiidii", "participants", "deals"])
    p.add_argument("--symbols", nargs="*")
    p.add_argument("--limit", type=int, default=10)
    p = command("global", market.global_view, "US / global markets, calendar, headlines and India impact")
    p.add_argument("what", nargs="?", default="all", choices=["all", "snapshot", "calendar", "headlines"])
    p.add_argument("--hours", type=int, default=18)
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--all-headlines", action="store_true", help="include headlines with no market theme")


def _news(command) -> None:
    p = command("news", news.news, "new headlines and NSE filings")
    p.add_argument("--tickers", nargs="*")
    p.add_argument("--hours", type=int, default=12)
    p.add_argument("--all", action="store_true", help="include items already seen")
    p.add_argument("--peek", action="store_true", help="do not mark items as seen")
    p.add_argument("--market-only", action="store_true")
    p.add_argument("--stocks-only", action="store_true")
    p.add_argument("--only-mine", action="store_true", help="only items that mention your tickers")
    p.add_argument("--no-nse", action="store_true")
    p.add_argument("--no-moves", action="store_true")
    p.add_argument("--since", help="from this day, YYYY-MM-DD (instead of --hours); shows items already seen")
    p.add_argument("--until", help="to this day, YYYY-MM-DD (with --since)")
    p.add_argument("--limit", type=int, default=40)
    p = command("movers", news.movers, "NSE filings ranked by today's move")
    p.add_argument("--hours", type=int, default=24)
    p.add_argument("--any", action="store_true", help="all companies, not only F&O stocks")
    p.add_argument("--max", type=int, default=30)
    p = command("policy", news.policy, "RBI, SEBI, NSE circulars, economy news")
    p.add_argument("--hours", type=int, default=24)
    p.add_argument("--only", nargs="*", help="themes: rbi-rates rbi-liquidity banking-rules fno-rules ban-surveillance "
                                               "listing-ipo investor-caution trade-policy tax-fiscal macro-data")
    p.add_argument("--limit", type=int, default=40)


def _trading(command) -> None:
    p = command("scan", trading.scan, "universe / daily setups / opening-range breakouts")
    p.add_argument("mode", choices=["universe", "daily", "orb"])
    p.add_argument("--list", default="fo", help="fo, nifty50, nifty100, nifty200, nifty500 or a file")
    p.add_argument("--symbols", help="comma-separated symbols instead of a list")
    p.add_argument("--limit", type=int)
    p.add_argument("--top", type=int, default=30)
    p.add_argument("--min-price", type=float, default=50)
    p.add_argument("--min-volume", type=float, default=200000)
    p.add_argument("--date", help="orb: a past session, YYYY-MM-DD")
    p.add_argument("--at", help="orb: cut the clock at HH:MM")
    p.add_argument("--or-minutes", type=int, default=15)
    p.add_argument("--min-volume-x", type=float, default=0.0)
    p.add_argument("--workers", type=int, default=4)
    p = command("entry", trading.entry, "entry timer")
    p.add_argument("mode", choices=["check", "watch"])
    p.add_argument("symbol")
    p.add_argument("--setup", default="orb", choices=["orb", "level", "vwap"])
    p.add_argument("--side", default="both", choices=["long", "short", "both"])
    p.add_argument("--level", type=float)
    p.add_argument("--or-minutes", type=int, default=15)
    p.add_argument("--interval", default="5m", choices=["1m", "5m"])
    p.add_argument("--min-volume-x", type=float, default=0.0)
    p.add_argument("--every", type=int, default=30, help="watch: re-poll seconds")
    p.add_argument("--until", help="watch: stop at HH:MM")
    p.add_argument("--no-write", action="store_true")
    p = command("plan", trading.plan, "stop, target and instrument")
    p.add_argument("mode", choices=["make", "show"])
    p.add_argument("--symbol")
    p.add_argument("--side", choices=["long", "short"])
    p.add_argument("--entry", type=float)
    p.add_argument("--or-high", type=float)
    p.add_argument("--or-low", type=float)
    p.add_argument("--stop", help="or-mid, or-opposite, atr:K, pct:X, points:X, price:X")
    p.add_argument("--target", default="2R", help="2R, 1.5R, price:X")
    p.add_argument("--instrument", choices=["option", "future", "equity"])
    p.add_argument("--strike", help="atm, itm1, itm2, otm1, otm2 or a strike")
    p.add_argument("--expiry", default="near")
    p.add_argument("--hold", type=int, default=30, help="minutes, for premium estimates")
    p = command("tm", trading.time_machine, "Time Machine: replay the plan")
    p.add_argument("--replays", type=int, default=10000)
    p.add_argument("--seed", type=int, default=19)
    p.add_argument("--window", type=int, default=2)
    p.add_argument("--until", help="HH:MM, default square_off_by")
    p.add_argument("--write", action="store_true")
    p = command("budget", trading.budget, "size the plan / charges calculator / profit goal")
    p.add_argument("mode", choices=["size", "charges", "target"])
    p.add_argument("--profit", type=float, help="target: profit goal in rupees, net of charges")
    p.add_argument("--write", action="store_true")
    p.add_argument("--any-date", action="store_true")
    p.add_argument("--type", default="option", choices=list(KINDS))
    p.add_argument("--buy", type=float)
    p.add_argument("--sell", type=float)
    p.add_argument("--qty", type=int)
    p = command("risk", trading.risk, "PASS / BLOCK the proposed order")
    p.add_argument("--no-write", action="store_true")
    p.add_argument("--no-events", action="store_true")
    p.add_argument("--no-vix", action="store_true")
    p = command("paper", trading.paper, "paper trading journal")
    p.add_argument("mode", choices=["open", "mark", "close", "status", "report"])
    p.add_argument("--index", type=int, default=1)
    p.add_argument("--yes", action="store_true", help="the user said yes to this exact order")
    p.add_argument("--force", action="store_true", help="skip the risk-check requirement")
    p.add_argument("--price", type=float)
    p.add_argument("--id")
    p.add_argument("--reason")
    p.add_argument("--note")
    p.add_argument("--days", type=int)
    p.add_argument("--last", type=int, default=20)
    p = command("alerts", trading.alerts, "price / premium / time alerts")
    p.add_argument("mode", choices=["check", "add", "list", "reset", "clear"])
    p.add_argument("id", nargs="?")
    p.add_argument("--from-plan", action="store_true")
    p.add_argument("--symbol")
    p.add_argument("--above", type=float)
    p.add_argument("--below", type=float)
    p.add_argument("--pct", type=float)
    p.add_argument("--at")
    p.add_argument("--opening-bell", action="store_true")
    p.add_argument("--label")
    p.add_argument("--quiet", action="store_true")


def _research(command) -> None:
    p = command("insiders", research.insiders, "insider (PIT) and takeover-code (SAST) trades: promoters and directors buying or selling")
    p.add_argument("symbols", nargs="*", help="only these NSE symbols (default: every company)")
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--all", action="store_true", help="include ESOP, allotment, gift, inter-se and off-market filings")
    p.add_argument("--min-value", type=float, default=0, help="rupees, insider filings only")
    p.add_argument("--new", action="store_true", help="only filings not shown before")
    p.add_argument("--peek", action="store_true", help="do not mark filings as seen")
    p.add_argument("--limit", type=int, default=25)
    p = command("holdings", research.holdings, "shareholding pattern: promoters, FII, DII, MF, named holders over 1%, quarter changes")
    p.add_argument("symbols", nargs="*")
    p.add_argument("--find", metavar="NAME", help="search the stocks for a holder by name (an investor, fund or company)")
    p.add_argument("--list", default="nifty100", help="--find: fo, nifty50, nifty100, nifty200, nifty500 or a file")
    p.add_argument("--limit", type=int, default=20)
    p = command("screen", research.screen, "screen stocks on your rules: P/E vs sector, delivery %, 52-week range, returns, RSI")
    p.add_argument("--preset", choices=sorted(PRESETS))
    p.add_argument("--rules", help="rules JSON file (default workspace/rules.json)")
    p.add_argument("--list", default="nifty100", help="fo, nifty50, nifty100, nifty200, nifty500 or a file")
    p.add_argument("--symbols", help="comma-separated symbols instead of a list")
    p.add_argument("--limit", type=int, help="screen only the first N symbols")
    p.add_argument("--top", type=int, default=20)
    p.add_argument("--workers", type=int, default=4)
    p = command("tax", research.tax, "Indian tax arithmetic: F&O / intraday turnover and P&L, capital-gain lots, harvesting")
    p.add_argument("mode", choices=["report", "lots", "sell", "harvest"])
    p.add_argument("symbol", nargs="?")
    p.add_argument("--fy", help="report: financial year such as 2026-27 (default: the current one)")
    p.add_argument("--trades", help="report: broker P&L CSV with date, symbol, segment (fno/intraday), pnl, charges")
    p.add_argument("--qty", type=float)
    p.add_argument("--price", type=float)
    p.add_argument("--charges", type=float, help="sell: total charges of the sale, rupees")
    p.add_argument("--date", help="YYYY-MM-DD (default today)")
    p.add_argument("--record", action="store_true", help="sell: the sale has filled; update the lots and log the gain")
    p.add_argument("--min-loss", type=float, default=0, help="harvest: smallest loss to list, rupees")


def _reports(command) -> None:
    p = command("brief", reports.brief, "the daily brief")
    p.add_argument("--chains", nargs="*", default=["NIFTY", "BANKNIFTY"])
    p.add_argument("--hours", type=int, default=14)
    p.add_argument("--headlines", type=int, default=12)
    p = command("decide", reports.decide, "the decision: BUY CALL / BUY PUT / HOLD / EXIT / WAIT / NO TRADE, or the day plan")
    p.add_argument("mode", choices=["now", "plan", "backtest", "journal"])
    p.add_argument("symbol", nargs="?", default="NIFTY")
    p.add_argument("--sessions", type=int, default=58, help="backtest: sessions")
    p = command("live", reports.live, "live monitor: entry and exit signals every few minutes")
    p.add_argument("mode", choices=["tick", "run", "status", "reset", "replay", "backtest"])
    p.add_argument("symbol", nargs="?", default="NIFTY")
    p.add_argument("--every", type=int, default=180, help="run: seconds between checks")
    p.add_argument("--until", default="15:20", help="run: stop at HH:MM")
    p.add_argument("--date", help="replay: YYYY-MM-DD")
    p.add_argument("--sessions", type=int, default=40, help="backtest: sessions")
    p.add_argument("--last", type=int, default=25, help="backtest: trades to list")
