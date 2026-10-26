"""Entry timer: watches one underlying bar by bar and says when to get in.

Setups
  orb    opening-range breakout: the first COMPLETED bar after the range
         (15 minutes = the 09:15, 09:20 and 09:25 bars) that CLOSES above
         its high (long: buy CE / future) or below its low (short: buy PE /
         sell future); ``side`` long, short or both
  level  the first completed bar closing above (long) or below (short) a level
  vwap   a close back across VWAP after the opening range

A trigger's time is the bar's CLOSE (the 09:30 bar closes at 09:35) and its
price is that close. Bars count only once closed. Entries only between
``no_entries_before`` and ``no_entries_after``.

Statuses: triggered, waiting, expired, no-data. It never places an order.
"""

import datetime as dt
import logging
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

from indtrader.core import clock
from indtrader.core.errors import ValidationError
from indtrader.core.formatting import num
from indtrader.models.analytics import indicators as ind
from indtrader.models.data import bars as barlib

log = logging.getLogger(__name__)


@dataclass
class EntryRequest:
    setup: str = "orb"
    side: str = "both"
    or_minutes: int = 15
    level: Optional[float] = None
    min_volume_x: float = 0.0
    interval: str = "5m"

    def validate(self) -> None:
        if self.setup not in ("orb", "level", "vwap"):
            raise ValidationError("unknown setup %r (orb, level, vwap)" % self.setup)
        if self.setup == "level" and self.level is None:
            raise ValidationError("the level setup needs --level")
        if self.setup == "level" and self.side == "both":
            raise ValidationError("the level setup needs --side long or --side short")


class EntryTimer:
    def __init__(self, market, cfg) -> None:
        self.market = market
        self.cfg = cfg

    def evaluate(self, session: List[dict], now: dt.datetime, request: EntryRequest) -> dict:
        """Look for the setup in one session of closed bars."""
        request.validate()
        interval_min = barlib.interval_minutes(request.interval) or 5
        start_time = clock.parse_hhmm(self.cfg["no_entries_before"])
        end_time = clock.parse_hhmm(self.cfg["no_entries_after"])
        out = {"setup": request.setup, "side_wanted": request.side, "or_minutes": request.or_minutes,
               "interval": request.interval}
        if not session:
            return dict(out, status="no-data", why="no closed bars yet")
        step = dt.timedelta(minutes=interval_min)
        opening = ind.opening_range(session, request.or_minutes, interval_min)
        if opening:
            out["or_high"], out["or_low"] = opening[0], opening[1]
        elif request.setup in ("orb", "vwap"):
            return dict(out, last=session[-1]["c"], **self._no_range(session, request, interval_min))
        count = opening[2] if opening else 0
        average_volume = sum(b["v"] for b in session[:count]) / count if count else 0
        vwap, _ = ind.vwap(session)
        for i in range(count, len(session)):
            bar = session[i]
            close_time = bar["t"] + step
            if close_time.time() < start_time:
                continue
            if close_time.time() > end_time:
                break
            side = self._trigger(request, session, i, opening, vwap)
            if side and request.min_volume_x and average_volume and bar["v"] < request.min_volume_x * average_volume:
                side = None
            if side:
                log.info("entry %s %s triggered %s at %s, close %.2f", request.setup, side, session[0]["t"].date(),
                         close_time.strftime("%H:%M"), bar["c"])
                return dict(out, status="triggered", side=side, trigger_time=close_time.strftime("%H:%M"),
                            trigger_price=round(bar["c"], 2), trigger_bar=bar["t"].strftime("%H:%M"),
                            vwap=round(vwap[i], 2), last=session[-1]["c"],
                            vol_x=round(bar["v"] / average_volume, 2) if average_volume else None)
        return dict(out, last=session[-1]["c"], **self._not_yet(session, now, request, opening, vwap, step, end_time, start_time))

    @staticmethod
    def _no_range(session: List[dict], request: EntryRequest, interval_min: int) -> dict:
        first = session[0]["t"]
        if (first.hour, first.minute) != (9, 15) or len(session) >= max(1, request.or_minutes // interval_min) + 2:
            return {"status": "no-data",
                    "why": "the data is missing opening-range bars (first bar %s): no valid range today" % first.strftime("%H:%M")}
        return {"status": "waiting", "why": "the %d-minute opening range is still forming" % request.or_minutes}

    @staticmethod
    def _trigger(request: EntryRequest, session: List[dict], i: int, opening, vwap: List[float]) -> Optional[str]:
        close = session[i]["c"]
        if request.setup == "orb":
            if request.side in ("long", "both") and close > opening[0]:
                return "long"
            if request.side in ("short", "both") and close < opening[1]:
                return "short"
        elif request.setup == "level":
            if request.side == "long" and close > request.level:
                return "long"
            if request.side == "short" and close < request.level:
                return "short"
        elif request.setup == "vwap" and i > 0:
            prev_close, prev_vwap = session[i - 1]["c"], vwap[i - 1]
            if request.side in ("long", "both") and prev_close <= prev_vwap and close > vwap[i]:
                return "long"
            if request.side in ("short", "both") and prev_close >= prev_vwap and close < vwap[i]:
                return "short"
        return None

    def _not_yet(self, session, now, request, opening, vwap, step, end_time, start_time) -> dict:
        last = session[-1]
        if now >= clock.at(session[0]["t"].date(), end_time) or (last["t"] + step).time() > end_time:
            return {"status": "expired", "why": "no trigger by %s" % self.cfg["no_entries_after"]}
        if request.setup == "orb":
            why = "inside the range %s - %s (%.2f%% to the high, %.2f%% to the low)" % (
                num(opening[1]), num(opening[0]), (opening[0] / last["c"] - 1) * 100, (1 - opening[1] / last["c"]) * 100)
        elif request.setup == "level":
            why = "no close %s %s yet (last %s)" % ("above" if request.side == "long" else "below", num(request.level), num(last["c"]))
        else:
            why = "no VWAP cross yet (VWAP %s, last %s)" % (num(vwap[-1]), num(last["c"]))
        if (last["t"] + step).time() < start_time:
            why += "; entries open at %s" % self.cfg["no_entries_before"]
        return {"status": "waiting", "why": why}

    def check(self, symbol: str, now: dt.datetime, request: EntryRequest) -> dict:
        day = now.date()
        if not clock.is_trading_day(day):
            return {"symbol": symbol.upper(), "status": "no-data", "date": day.isoformat(),
                    "why": "market closed today (%s)" % clock.holiday_name(day)}
        if request.interval == "1m":
            rng = "7d"
        else:   # today's live session needs one day; a replay or offline run needs the 60-day file
            rng = "1d" if (day == clock.now_ist().date() and not self.market.offline) else "60d"
        _, bars = self.market.candles(symbol, request.interval, rng)
        session = [b for b in barlib.closed(bars, now, request.interval) if b["t"].date() == day]
        result = self.evaluate(session, now, request)
        result.update(symbol=symbol.upper(), date=day.isoformat(), checked=now.isoformat(timespec="minutes"),
                      fo=self.market.has_derivatives(symbol))
        if request.level is not None:
            result["level"] = request.level
        return result

    def watch(self, symbol: str, start: dt.datetime, until: dt.datetime, request: EntryRequest, simulated: bool,
              every: int, report: Callable[[dt.datetime, dict], None]) -> dict:
        """Check after every bar close until triggered, expired or ``until``."""
        step = dt.timedelta(minutes=barlib.interval_minutes(request.interval) or 5)
        moment, last_seen = start, None
        while True:
            result = self.check(symbol, moment, request)
            seen = (result["status"], result.get("why"), result.get("trigger_time"))
            if seen != last_seen:                   # report changes only
                report(moment, result)
                last_seen = seen
            if result["status"] in ("triggered", "expired", "no-data") or moment >= until:
                return result
            elapsed = (moment - clock.at(moment.date(), clock.OPEN)).total_seconds() / 60
            closed_bars = max(0, int(elapsed // (step.total_seconds() / 60)))
            next_check = clock.at(moment.date(), clock.OPEN) + step * (closed_bars + 1) + dt.timedelta(seconds=5)
            if simulated:
                moment = next_check
            else:
                time.sleep(max((next_check - clock.now_ist()).total_seconds(), every))
                moment = clock.now_ist()
