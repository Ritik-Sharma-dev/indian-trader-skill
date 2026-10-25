"""brief, decide and live."""

import datetime as dt
from argparse import Namespace

from indtrader.core import clock, settings
from indtrader.core.context import AppContext
from indtrader.core.formatting import print_json
from indtrader.models.agents.decision_maker.decider import Decider
from indtrader.models.agents.decision_maker.journal import DecisionJournal
from indtrader.models.agents.live_monitor.monitor import LiveMonitor, Tick, serialise_events, stats
from indtrader.models.agents.market_analyst.brief import DailyBrief
from indtrader.views import decisions as decision_view
from indtrader.views import live as live_view
from indtrader.views import reports as report_view

ACTIONS_NOW = ("BUY CALL", "BUY PUT", "EXIT")


def brief(args: Namespace, ctx: AppContext) -> int:
    data = DailyBrief(ctx).collect(tuple(s.upper() for s in args.chains), args.hours, args.headlines)
    text = report_view.brief(ctx.now, data)
    path = settings.path("briefs", "brief-%s.md" % ctx.now.strftime("%Y-%m-%d-%H%M"))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    print(text)
    print("\nSaved %s" % path)
    return 0


def decide(args: Namespace, ctx: AppContext) -> int:
    """Exit code 0 when there is something to do now (BUY or EXIT), 1 otherwise, so a loop can tell."""
    if args.mode == "journal":
        summary = DecisionJournal().summary()
        print_json(summary) if args.json else print(decision_view.journal(summary))
        return 0
    decider = Decider(ctx)
    if args.mode == "backtest":
        result = decider.backtest(args.symbol, args.sessions)
        print_json(result) if args.json else print(decision_view.backtest(result))
        return 0
    result = decider.plan(args.symbol) if args.mode == "plan" else decider.decide(args.symbol)
    print_json(result.as_dict()) if args.json else print(decision_view.decision(result))
    return 0 if result.action in ACTIONS_NOW else 1


def _tick_json(result: Tick, cfg: dict) -> dict:
    return {"status": live_view.tick(result, cfg), "events": serialise_events(result.events)}


def live(args: Namespace, ctx: AppContext) -> int:
    symbol = args.symbol.upper()
    monitor = LiveMonitor(ctx)
    if args.mode == "tick":
        result = monitor.tick(symbol)
        print_json(_tick_json(result, ctx.cfg)) if args.json else print(live_view.tick(result, ctx.cfg))
        return 0 if any(e["type"] in ("ENTRY", "EXIT") for e in result.events) else 1
    if args.mode == "run":
        simulated = bool(args.now or ctx.offline)
        print("Live monitor for %s every %d seconds until %s IST. Ctrl+C to stop. It never places orders." % (symbol, args.every, args.until))

        def report(result: Tick) -> None:
            print(live_view.tick(result, ctx.cfg, bell=not simulated), flush=True)
            print("-" * 60, flush=True)

        monitor.run(symbol, args.every, clock.at(ctx.now.date(), clock.parse_hhmm(args.until)), simulated, report)
        return 0
    if args.mode == "status":
        state = monitor.load_state(symbol, ctx.now.date())
        if not state:
            print("No live session for %s today." % symbol)
            return 1
        print(live_view.status(state, None, ctx.now, ctx.cfg))
        for item in state["events"][-12:]:
            print("   %s %s %s" % (item["time"][11:16], item["type"], item["text"]))
        return 0
    if args.mode == "reset":
        monitor.reset(symbol, ctx.now.date())
        print("Live state for %s today cleared." % symbol)
        return 0
    if args.mode == "replay":
        day = dt.date.fromisoformat(args.date) if args.date else ctx.now.date()
        state, events = monitor.replay_day(symbol, day)
        print(live_view.replay(symbol, day, state, events))
        return 0
    days, trades = monitor.backtest(symbol, args.sessions)
    summary = stats(trades)
    if args.json:
        print_json({"days": [d.isoformat() for d in days], "stats": summary, "trades": trades})
    else:
        print(live_view.backtest(symbol, days, summary, trades, args.last))
    return 0
