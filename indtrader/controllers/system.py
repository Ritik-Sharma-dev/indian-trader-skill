"""config, refresh, clock, agent and mcp."""

import logging
from argparse import Namespace

from indtrader.core import clock, settings
from indtrader.core.context import AppContext
from indtrader.core.errors import ValidationError
from indtrader.core.formatting import print_json
from indtrader.models.agents import REGISTRY
from indtrader.controllers.agents import run_agent as run_agent_report

log = logging.getLogger(__name__)


def config(args: Namespace, ctx: AppContext) -> int:
    if args.mode == "path":
        print(settings.path("config.json"))
    elif args.mode == "init":
        path, created = settings.init(args.force)
        print(("Created %s. Edit capital, max_loss_per_trade and max_daily_loss first." if created
               else "%s already exists (use --force to overwrite).") % path)
    else:
        print_json(ctx.cfg)
    return 0


def refresh(args: Namespace, ctx: AppContext) -> int:
    holidays = ctx.market.refresh_holidays()
    print("Holidays: %d dates cached (%s ... %s)" % (len(holidays), min(holidays), max(holidays)))
    lots = ctx.market.lot_sizes()
    print("Lot sizes: %d underlyings (NIFTY %s, BANKNIFTY %s, FINNIFTY %s)" % (
        len(lots), lots.get("NIFTY", {}).get("lot"), lots.get("BANKNIFTY", {}).get("lot"), lots.get("FINNIFTY", {}).get("lot")))
    return 0


def show_clock(args: Namespace, ctx: AppContext) -> int:
    status = clock.market_status(ctx.now)
    if args.json:
        print_json(status)
        return 0
    print("IST now: %s" % ctx.now.strftime("%a %d %b %Y %H:%M"))
    print("NSE: %s (%s)" % (status["state"].upper(), status["reason"]))
    if "minutes_to_close" in status:
        print("Closes at 15:30 IST, in %d minutes. Square off intraday by %s." % (status["minutes_to_close"], ctx.cfg["square_off_by"]))
    print("Next open: %s" % status["next_open"].replace("T", " "))
    upcoming = sorted((d, n) for d, n in clock.holidays().items() if d >= ctx.now.date().isoformat())[:3]
    if upcoming:
        print("Next holidays: " + "; ".join("%s %s" % pair for pair in upcoming))
    return 0


def run_agent(args: Namespace, ctx: AppContext) -> int:
    names = ["trading-desk"] if args.name == "all" else [args.name]      # the desk runs every other stage itself
    for name in names:
        if name not in REGISTRY:
            raise ValidationError("unknown agent %r (%s, all)" % (name, ", ".join(sorted(REGISTRY))))
        report = run_agent_report(ctx, name, write=not args.no_write)
        if args.json:
            print_json({"agent": report.agent, "path": report.path, "seconds": report.seconds, "errors": report.errors})
        elif args.print:
            print(report.markdown)
        else:
            print("%s: report written to %s in %.1fs%s" % (report.agent, report.path, report.seconds,
                                                        (" (%d data note(s))" % len(report.errors)) if report.errors else ""))
    return 0

