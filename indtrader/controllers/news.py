"""news, movers and policy."""

import datetime as dt
from argparse import Namespace
from typing import Optional

from indtrader.core.context import AppContext
from indtrader.core.errors import ValidationError
from indtrader.core.formatting import print_json
from indtrader.models.agents.india_news.desk import NewsDesk, NewsQuery
from indtrader.views import news as view


def _date(text: Optional[str]) -> Optional[dt.date]:
    if not text:
        return None
    try:
        return dt.datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise ValidationError("cannot read the date %r (use YYYY-MM-DD)" % text) from None


def news(args: Namespace, ctx: AppContext) -> int:
    since, until = _date(args.since), _date(args.until)
    if until and not since:
        raise ValidationError("--until needs --since")
    if since and until and until < since:
        raise ValidationError("--until %s is before --since %s" % (until, since))
    query = NewsQuery(tickers=args.tickers, hours=args.hours, show_seen=args.all, mark_seen=not args.peek,
                      market=not args.stocks_only, stocks=not args.market_only, filings=not args.no_nse,
                      only_mine=args.only_mine, limit=args.limit, with_moves=not args.no_moves, since=since, until=until)
    result = NewsDesk(ctx.market, ctx.cfg).news(query, ctx.now)
    print_json(result) if args.json else print(view.news(result, ctx.now))
    return 0


def movers(args: Namespace, ctx: AppContext) -> int:
    ranked = NewsDesk(ctx.market, ctx.cfg).movers(ctx.now, args.hours, args.any, args.max)
    print_json(ranked) if args.json else print(view.movers(ranked, args.hours, args.any))
    return 0


def policy(args: Namespace, ctx: AppContext) -> int:
    result = NewsDesk(ctx.market, ctx.cfg).policy(ctx.now, args.hours, args.only, args.limit)
    print_json(result) if args.json else print(view.policy(result))
    return 0
