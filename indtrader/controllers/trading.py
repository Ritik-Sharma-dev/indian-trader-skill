"""scan, entry, plan, tm, budget, risk, paper and alerts."""

import datetime as dt
import logging
from argparse import Namespace

from indtrader.core import clock, settings
from indtrader.core.context import AppContext
from indtrader.core.errors import IndianTraderError, ValidationError
from indtrader.core.formatting import inr, num, pct, print_json, table
from indtrader.core.storage import read_json, write_json
from indtrader.models.trading.alerts import AlertBook, describe as describe_rule, rules_from_plan
from indtrader.models.trading.charges import charges
from indtrader.models.trading.entry import EntryRequest, EntryTimer
from indtrader.models.trading.paper import PaperJournal, stats as paper_stats
from indtrader.models.trading.planner import PlanRequest, TradePlanner
from indtrader.models.trading.risk import RiskLedger, RiskManager
from indtrader.models.trading.scanner import Scanner, write_watchlist
from indtrader.models.trading.sizing import PositionSizer, order_from
from indtrader.models.trading.timemachine import TimeMachine
from indtrader.views import trading as view

log = logging.getLogger(__name__)


def _load_plan() -> dict:
    plan = read_json(settings.path("plan.json"))
    if not plan:
        raise ValidationError("no plan: run /in-plan first")
    return plan


# --- scanner ----------------------------------------------------------------------

def scan(args: Namespace, ctx: AppContext) -> int:
    scanner = Scanner(ctx.market)
    if args.mode == "universe":
        symbols = scanner.universe(args.list)
        path = settings.path("universe-%s.txt" % args.list.lower())
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(symbols) + "\n")
        print("%d symbols in %s -> %s" % (len(symbols), args.list, path))
        return 0
    symbols = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else scanner.universe(args.list)
    if args.limit:
        symbols = symbols[: args.limit]
    if args.mode == "daily":
        return _scan_daily(args, ctx, scanner, symbols)
    return _scan_orb(args, ctx, scanner, symbols)


def _scan_daily(args: Namespace, ctx: AppContext, scanner: Scanner, symbols) -> int:
    hits, skipped = scanner.daily(symbols, args.min_price, args.min_volume)
    path = write_watchlist("daily", hits, ctx.now, {"universe": args.list, "scanned": len(symbols)})
    if args.json:
        print_json(hits)
        return 0
    print("Daily setups, %d of %d stocks (%s), closes to %s:" % (len(hits), len(symbols), "custom" if args.symbols else args.list, ctx.now.date()))
    rows = [[h["symbol"], num(h["price"]), pct(h["change_pct"]), num(h["rsi"], 1), h["lean"], ", ".join(h["setups"])] for h in hits[: args.top]]
    print(table(rows, ["Symbol", "Close", "Day %", "RSI", "Lean", "Setups"], "lrrrll"))
    if skipped:
        print("(%d had too little data)" % skipped)
    print("Saved %s" % path)
    return 0


def _scan_orb(args: Namespace, ctx: AppContext, scanner: Scanner, symbols) -> int:
    day = dt.datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else ctx.now.date()
    if not clock.is_trading_day(day):
        raise ValidationError("%s is not a trading day (%s)" % (day, clock.holiday_name(day)))
    if day == ctx.now.date():
        cut = clock.at(day, clock.parse_hhmm(args.at)) if args.at else ctx.now
    else:
        cut = clock.at(day, clock.parse_hhmm(args.at or "15:30"))
    range_complete = (dt.datetime.combine(day, clock.OPEN) + dt.timedelta(minutes=args.or_minutes + 5)).time()
    if cut.time() < range_complete:
        print("The %d-minute opening range is not complete yet at %s." % (args.or_minutes, cut.strftime("%H:%M")))
        return 1
    hits, scanned, missing = scanner.opening_range(symbols, cut, day, args.or_minutes, args.min_volume_x, args.workers)
    path = write_watchlist("orb", hits, cut, {"date": day.isoformat(), "or_minutes": args.or_minutes, "scanned": scanned})
    if args.json:
        print_json(hits)
        return 0
    longs = sum(1 for h in hits if h["side"] == "long")
    print("Opening-range breakouts %s up to %s IST: %d long, %d short, of %d stocks%s" % (
        day, cut.strftime("%H:%M"), longs, len(hits) - longs, scanned, (" (%d without data)" % missing) if missing else ""))
    rows = [[h["symbol"], h["side"], h["trigger_time"], num(h["trigger_price"]), "%s - %s" % (num(h["or_low"]), num(h["or_high"])),
             pct(h["beyond_pct"]), num(h["vol_x"]) if h.get("vol_x") else "-", num(h["last"])] for h in hits[: args.top]]
    print(table(rows, ["Symbol", "Side", "Trigger", "Close", "Range", "Beyond", "Vol x", "Last"], "llrrrrrr"))
    print("Saved %s. Next: news on these, then /in-entry to time one." % path)
    return 0


# --- entry and plan ---------------------------------------------------------------

def entry(args: Namespace, ctx: AppContext) -> int:
    symbol = args.symbol.upper()
    request = EntryRequest(args.setup, args.side, args.or_minutes, args.level, args.min_volume_x, args.interval)
    timer = EntryTimer(ctx.market, ctx.cfg)
    entry_path = settings.path("entry.json")
    if args.mode == "check":
        result = timer.check(symbol, ctx.now, request)
        if result["status"] == "triggered" and not args.no_write:
            write_json(entry_path, result)
        if args.json:
            print_json(result)
        else:
            print(view.entry(result))
            if result["status"] == "triggered" and not args.no_write:
                print("Saved %s. Next: /in-plan sets the stop, the target and the option strike." % entry_path)
        return 0 if result["status"] == "triggered" else 1
    until = clock.at(ctx.now.date(), clock.parse_hhmm(args.until or ctx.cfg["no_entries_after"]))
    result = timer.watch(symbol, ctx.now, until, request, simulated=bool(args.now or ctx.offline), every=args.every,
                         report=lambda moment, r: print("%s  %s" % (moment.strftime("%H:%M:%S"), view.entry(r)), flush=True))
    if result["status"] == "triggered" and not args.no_write:
        write_json(entry_path, result)
    return 0 if result["status"] == "triggered" else 1


def plan(args: Namespace, ctx: AppContext) -> int:
    path = settings.path("plan.json")
    if args.mode == "show":
        saved = read_json(path)
        if not saved:
            print("No plan yet.")
            return 1
        print_json(saved) if args.json else print(view.plan(saved))
        return 0
    request = PlanRequest(args.symbol, args.side, args.entry, args.or_high, args.or_low, args.stop, args.target,
                          args.instrument, args.strike, args.expiry, args.hold)
    made = TradePlanner(ctx.market, ctx.cfg).build(request, ctx.now, read_json(settings.path("entry.json"), {}) or {})
    write_json(path, made)
    if args.json:
        print_json(made)
    else:
        print(view.plan(made))
        print("Saved %s. Next: /in-timemachine for the odds, then /in-budget to size it." % path)
    return 0


def time_machine(args: Namespace, ctx: AppContext) -> int:
    result = TimeMachine(ctx.market, ctx.cfg).run(_load_plan(), args.replays, args.seed, args.window, args.until)
    path = settings.path("timemachine.json")
    if args.write:
        write_json(path, result)
    if args.json:
        print_json(result)
    else:
        print(view.time_machine(result))
        if args.write:
            print("Saved %s. Next: /in-budget to size it." % path)
    return 0


# --- money -----------------------------------------------------------------------------

def budget(args: Namespace, ctx: AppContext) -> int:
    if args.mode == "charges":
        return _charges(args, ctx)
    current = _load_plan()
    sizer = PositionSizer(ctx.cfg)
    if args.mode == "target":
        if not args.profit:
            raise ValidationError("budget target needs --profit (rupees, net of charges)")
        targets = sizer.target_table(current, args.profit)
        print_json(targets) if args.json else print(view.profit_target(targets, ctx.cfg["max_loss_per_trade"]))
        return 0
    if current["date"] != ctx.now.date().isoformat() and not args.any_date:
        raise ValidationError("the plan is for %s, not today; make a fresh plan (or --any-date)" % current["date"])
    sized = sizer.size(current)
    order = order_from(current, sized, ctx.now) if not sized.get("refused") else None
    orders_path = settings.path("orders.json")
    if order and args.write:
        write_json(orders_path, {"made": ctx.now.isoformat(timespec="minutes"), "orders": [order]})
    if args.json:
        print_json({"size": sized, "order": order})
    else:
        print(view.sizing(current, sized, order, ctx.cfg["capital"]))
        if order and args.write:
            print("\nSaved %s. Next: /in-risk checks it." % orders_path)
    return 0 if order else 1


def _charges(args: Namespace, ctx: AppContext) -> int:
    if args.buy is None or args.sell is None:
        raise ValidationError("charges needs --buy and --sell (per unit) and --qty")
    quantity = args.qty or 1
    result = charges(args.type, args.buy * quantity, args.sell * quantity, ctx.cfg)
    gross = (args.sell - args.buy) * quantity
    if args.json:
        print_json(dict(result, gross=gross, net=gross - result["total"]))
        return 0
    print("%s: buy %s, sell %s, qty %d -> turnover %s" % (args.type, num(args.buy), num(args.sell), quantity, inr((args.buy + args.sell) * quantity)))
    print(table([[k, inr(v)] for k, v in result.items()], ["Charge", "Rupees"]))
    print("Gross %s, net %s. Points needed to break even: %s" % (inr(gross, sign=True), inr(gross - result["total"], sign=True),
                                                                 num(result["total"] / quantity)))
    return 0


def risk(args: Namespace, ctx: AppContext) -> int:
    document = read_json(settings.path("orders.json"))
    if not document or not document.get("orders"):
        raise ValidationError("no orders: run /in-budget --write first")
    vix = None
    if not args.no_vix:
        try:
            vix = ctx.market.quote("INDIAVIX")["price"]
        except IndianTraderError as exc:
            log.info("India VIX unavailable for the risk check: %s", exc)
    manager = RiskManager(ctx.cfg, ctx.market)
    results = []
    for order in document["orders"]:
        result = manager.check(order, ctx.now, vix, use_events=not args.no_events)
        result["symbol"] = order["symbol"]
        results.append(result)
    if not args.no_write:
        RiskLedger().record(results, ctx.now)
    passed = all(r["verdict"] == "PASS" for r in results)
    if args.json:
        print_json(results)
        return 0 if passed else 1
    for order, result in zip(document["orders"], results):
        print("%s  %s %s x%d @ %s  stop %s  target %s" % (result["verdict"], order["action"], order["symbol"], order["qty"],
                                                       num(order["price"]), num(order["stop_loss"]), num(order["target"])))
        for reason in result["block"]:
            print("   BLOCK " + reason)
        for note in result["warn"]:
            print("   warn  " + note)
        print("   today: %d trades, %s lost or at risk, daily limit %s" % (result["trades_today"], inr(result["daily_used"]),
                                                                          inr(ctx.cfg["max_daily_loss"])))
    if passed:
        print("\nNext: /in-paper opens it in the paper journal (no real order is sent).")
    return 0 if passed else 1


# --- journal and alerts ---------------------------------------------------------------

def paper(args: Namespace, ctx: AppContext) -> int:
    journal = PaperJournal(ctx.market, ctx.cfg)
    if args.mode == "open":
        document = read_json(settings.path("orders.json"))
        if not document or not document.get("orders"):
            raise ValidationError("no orders: run /in-budget --write, then /in-risk")
        if not 1 <= args.index <= len(document["orders"]):
            raise ValidationError("there is no order %d" % args.index)
        order = document["orders"][args.index - 1]
        setup = (read_json(settings.path("plan.json"), {}) or {}).get("setup")
        trade, slippage = journal.open(order, ctx.now, confirmed=args.yes, force=args.force, price=args.price, note=args.note, setup=setup)
        print("PAPER %s %s x%d filled at %s (planned %s, slippage %+.2f). Stop %s, target %s, exit by %s. id %s" % (
            trade["action"], trade["symbol"], trade["qty"], num(trade["entry"]), num(order["price"]), slippage,
            num(trade["stop_loss"]), num(trade["target"]), trade["square_off_by"], trade["id"]))
        print("No real order was sent. Run `paper mark` to update it, or set alerts with /in-alerts.")
        return 0
    if args.mode == "mark":
        print(view.paper_mark(journal.mark(ctx.now, args.price)))
        return 0
    if args.mode == "close":
        trade = journal.close(args.id, ctx.now, args.price, args.reason)
        print("CLOSED %s %s at %s: gross %s, charges %s, net %s (%+.2fR)" % (
            trade["id"], trade["symbol"], num(trade["exit"]), inr(trade["gross"], sign=True), inr(trade["charges"]),
            inr(trade["net"], sign=True), trade["r"] or 0))
        return 0
    if args.mode == "status":
        rows = [[t["id"], t["symbol"], t["qty"], num(t["entry"]), num(t.get("last")), num(t["stop_loss"]), num(t["target"]), t["opened"][11:16]]
                for t in journal.trades if t["status"] == "open"]
        if not rows:
            print("No open paper trades.")
        else:
            print(table(rows, ["Id", "Symbol", "Qty", "Entry", "Last", "Stop", "Target", "Opened"], "llrrrrrr"))
            print("Run `paper mark` for live prices.")
        return 0
    since = (ctx.now.date() - dt.timedelta(days=args.days)).isoformat() if args.days else ""
    trades = [t for t in journal.trades if t["opened"][:10] >= since]
    if args.json:
        print_json({"stats": paper_stats(trades), "trades": trades})
    else:
        print(view.paper_report(trades, args.days, args.last))
    return 0


def alerts(args: Namespace, ctx: AppContext) -> int:
    book = AlertBook(ctx.market)
    if args.mode == "check":
        messages, notes = book.check(ctx.now)
        for note in notes:
            print("note: %s" % note)
        for message in messages:
            print("ALERT %s  %s" % (ctx.now.strftime("%H:%M"), message))
        if not messages and not args.quiet:
            print("%s  nothing rang (%d rules)" % (ctx.now.strftime("%H:%M"), len(book.rules)))
        return 0 if messages else 1
    if args.mode == "list":
        print(view.alerts(book))
        return 0
    if args.mode == "reset":
        if not args.id:
            raise ValidationError("alerts reset needs the alert id")
        book.reset(args.id)
        print("reset %s" % args.id)
        return 0
    if args.mode == "clear":
        book.clear()
        print("all alerts removed")
        return 0
    if args.from_plan:
        plan_doc = read_json(settings.path("plan.json"))
        if not plan_doc:
            raise ValidationError("no plan to take alerts from")
        added = book.add(rules_from_plan(plan_doc), replace_same_id=True)
    elif args.opening_bell:
        added = book.add([{"id": book.unique_id("opening-bell"), "type": "opening_bell", "label": "NSE open"}])
    elif args.at:
        clock.parse_hhmm(args.at)
        added = book.add([{"id": book.unique_id("time-" + args.at.replace(":", "")), "type": "time", "at": args.at, "label": args.label or "time"}])
    else:
        if not args.symbol:
            raise ValidationError("give --symbol with --above, --below or --pct")
        added = book.add(book.level_rules(args.symbol, args.above, args.below, args.pct, args.label))
    for rule in added:
        print("added %s: %s" % (rule["id"], describe_rule(rule)))
    return 0
