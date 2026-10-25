"""Trade planner: the stop, the target and the instrument, set BEFORE entry.

Levels live on the UNDERLYING (Nifty, Bank Nifty or a stock):

* stops: ``or-mid`` (middle of the opening range, the default for orb),
  ``or-opposite``, ``atr:K`` (K x ATR(14) of the session), ``pct:X``,
  ``points:X``, ``price:X``
* targets: ``2R`` (default), ``1R``, ``1.5R`` ... or ``price:X``

Instruments: ``option`` (default for indices; the ATM / ITM / OTM strike from
NSE's chain, with the premium at the planned entry, stop and target from
Black-Scholes at the current IV, ``hold`` minutes later, anchored to the
live premium), ``future`` (points x lot; levels are on spot) or ``equity``
(intraday cash). Stops round away from the entry to the 0.05 tick.

Refused: a stop on the wrong side, a risk under 0.05% of the price, or an
entry that has not triggered. It never places an order.
"""

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Optional, Tuple

from indtrader.core import clock
from indtrader.core.errors import DataError, ValidationError
from indtrader.core.formatting import num, round_tick
from indtrader.models.analytics import blackscholes as bs
from indtrader.models.analytics import indicators as ind
from indtrader.models.analytics.option_chain import OptionChainAnalyzer, OptionChainService, pick_strike
from indtrader.models.data import bars as barlib
from indtrader.models.data.symbols import is_index

log = logging.getLogger(__name__)


def parse_stop(rule: Optional[str]) -> Tuple[str, Optional[float]]:
    rule = (rule or "or-mid").lower()
    if rule in ("or-mid", "or-opposite"):
        return rule, None
    kind, _, value = rule.partition(":")
    if kind in ("atr", "pct", "points", "price") and value:
        try:
            return kind, float(value)
        except ValueError:
            pass
    raise ValidationError("stop rule %r: use or-mid, or-opposite, atr:K, pct:X, points:X or price:X" % rule)


def parse_target(rule: Optional[str]) -> Tuple[str, float]:
    rule = (rule or "2R").upper()
    try:
        if rule.endswith("R"):
            return "r", float(rule[:-1])
        if rule.startswith("PRICE:"):
            return "price", float(rule[6:])
    except ValueError:
        pass
    raise ValidationError("target %r: use 2R, 1.5R ... or price:X" % rule)


def levels(side: str, entry: float, stop_rule: str, target_rule: Optional[str], or_high: Optional[float] = None,
           or_low: Optional[float] = None, atr: Optional[float] = None, tick: float = 0.05) -> dict:
    """Entry, stop and target on the underlying, with risk, reward and R:R."""
    long = side == "long"
    kind, value = parse_stop(stop_rule)
    if kind in ("or-mid", "or-opposite") and or_high is None:
        raise ValidationError("%s needs the opening range (an orb entry, or --or-high / --or-low)" % kind)
    if kind == "or-mid":
        stop = (or_high + or_low) / 2
    elif kind == "or-opposite":
        stop = or_low if long else or_high
    elif kind == "atr":
        if not atr:
            raise DataError("an atr stop needs the session's bars")
        stop = entry - value * atr if long else entry + value * atr
    elif kind == "pct":
        stop = entry * (1 - value / 100) if long else entry * (1 + value / 100)
    elif kind == "points":
        stop = entry - value if long else entry + value
    else:
        stop = value
    stop = round_tick(stop, tick, "down" if long else "up")
    risk = (entry - stop) if long else (stop - entry)
    if risk <= 0:
        raise ValidationError("the stop %s is on the wrong side of the entry %s for a %s" % (num(stop), num(entry), side))
    if risk < entry * 0.0005:
        raise ValidationError("risk %s is under 0.05%% of the price: too tight to survive normal noise" % num(risk))
    target_kind, target_value = parse_target(target_rule)
    if target_kind == "r":
        target = entry + target_value * risk if long else entry - target_value * risk
    else:
        target = target_value
    target = round_tick(target, tick)
    reward = (target - entry) if long else (entry - target)
    if reward <= 0:
        raise ValidationError("the target %s is on the wrong side of the entry %s" % (num(target), num(entry)))
    return {"entry": entry, "stop": stop, "target": target, "risk_points": round(risk, 2),
            "reward_points": round(reward, 2), "rr": round(reward / risk, 2)}


def option_levels(pick: dict, underlying: dict, now: dt.datetime, hold_min: int, cfg: dict, expiry: dt.date) -> dict:
    """Premium at the planned entry, at the underlying stop and at the target.

    The model is anchored to the market premium at the CURRENT spot (which
    corrects for the futures basis and skew); the planned entry level is then
    priced, so an entry away from spot gets its own premium. Stop and target
    are priced ``hold_min`` minutes later, so time decay is included.
    """
    rate = cfg["risk_free_rate_pct"] / 100
    iv = pick.get("iv")
    if not iv:
        raise DataError("no IV for %s %s; cannot estimate premium levels" % (num(pick["strike"], 0), pick["kind"]))
    strike, kind, tick = pick["strike"], pick["kind"], cfg["tick"]
    expiry_at = clock.expiry_close(expiry)
    years_now = clock.years_to(expiry_at, now)
    years_later = clock.years_to(expiry_at, min(now + dt.timedelta(minutes=hold_min), expiry_at - dt.timedelta(minutes=1)))
    spot = pick.get("spot") or underlying["entry"]
    anchor = pick["premium"] - bs.price(kind, spot, strike, years_now, rate, iv)
    entry = round_tick(max(0.05, bs.price(kind, underlying["entry"], strike, years_now, rate, iv) + anchor), tick)
    stop = round_tick(max(0.05, bs.price(kind, underlying["stop"], strike, years_later, rate, iv) + anchor), tick, "down")
    target = round_tick(max(0.05, bs.price(kind, underlying["target"], strike, years_later, rate, iv) + anchor), tick)
    note = "Black-Scholes at IV %.1f%%, %d minutes after entry" % (iv * 100, hold_min)
    if abs(underlying["entry"] - spot) > spot * 0.0005:
        note += "; entry premium estimated at the planned level %.2f (market now %.2f at spot %.2f)" % (
            underlying["entry"], pick["premium"], spot)
    return {"entry": entry, "stop": stop, "target": target, "market_premium": pick["premium"],
            "risk": round(entry - stop, 2), "reward": round(target - entry, 2), "model_note": note}


@dataclass
class PlanRequest:
    symbol: Optional[str] = None
    side: Optional[str] = None
    entry: Optional[float] = None
    or_high: Optional[float] = None
    or_low: Optional[float] = None
    stop: Optional[str] = None
    target: Optional[str] = "2R"
    instrument: Optional[str] = None
    strike: Optional[str] = None
    expiry: Optional[str] = "near"
    hold: int = 30


class TradePlanner:
    def __init__(self, market, cfg) -> None:
        self.market = market
        self.cfg = cfg
        self.chains = OptionChainService(market)
        self.analyzer = OptionChainAnalyzer(cfg)

    def build(self, request: PlanRequest, now: dt.datetime, entry_doc: Optional[dict] = None) -> dict:
        entry_doc = entry_doc or {}
        symbol = (request.symbol or entry_doc.get("symbol") or "").upper()
        if not symbol:
            raise ValidationError("no symbol: run /in-entry first or give --symbol")
        from_entry = entry_doc.get("symbol") == symbol and request.entry is None
        if from_entry and entry_doc.get("status") != "triggered":
            raise ValidationError("entry.json has not triggered (status %s); give --entry to plan anyway" % entry_doc.get("status"))
        side = request.side or (entry_doc.get("side") if from_entry else None)
        if side not in ("long", "short"):
            raise ValidationError("give --side long or --side short")
        price = request.entry if request.entry is not None else entry_doc.get("trigger_price")
        if price is None:
            raise ValidationError("no entry price: give --entry")
        or_high = request.or_high if request.or_high is not None else (entry_doc.get("or_high") if from_entry else None)
        or_low = request.or_low if request.or_low is not None else (entry_doc.get("or_low") if from_entry else None)
        stop_rule = request.stop or ("or-mid" if or_high is not None else None)
        if not stop_rule:
            raise ValidationError("give a stop: --stop pct:0.5, points:40, atr:1.5 or price:X")
        atr = self._session_atr(symbol, now) if stop_rule.startswith("atr") else None
        underlying = levels(side, float(price), stop_rule, request.target, or_high, or_low, atr, self.cfg["tick"])
        instrument = request.instrument or ("option" if is_index(symbol) else "equity")
        plan = {"symbol": symbol, "date": now.date().isoformat(), "made": now.isoformat(timespec="minutes"), "side": side,
                "setup": entry_doc.get("setup") if from_entry else "manual",
                "entry_time": entry_doc.get("trigger_time") if from_entry else now.strftime("%H:%M"),
                "underlying": underlying, "or_high": or_high, "or_low": or_low,
                "rule": {"stop": stop_rule, "target": request.target or "2R", "or_minutes": entry_doc.get("or_minutes", 15)},
                "square_off_by": self.cfg["square_off_by"], "instrument": {"type": instrument}}
        if instrument == "option":
            self._add_option(plan, symbol, side, underlying, now, request)
        elif instrument == "future":
            self._add_future(plan, symbol, underlying)
        else:
            if is_index(symbol):
                raise ValidationError("an index cannot be bought as equity; use --instrument option or future")
            plan["instrument"].update({"lot": 1, "risk_per_share": underlying["risk_points"], "product": "MIS (intraday)"})
        log.info("plan %s %s %s: entry %.2f stop %.2f target %.2f", symbol, side, instrument,
                 underlying["entry"], underlying["stop"], underlying["target"])
        return plan

    def _session_atr(self, symbol: str, now: dt.datetime) -> Optional[float]:
        _, bars = self.market.candles(symbol, "5m", "5d")
        session = [b for b in barlib.closed(bars, now, "5m") if b["t"].date() == now.date()]
        series = ind.atr(session) if len(session) >= 14 else ind.atr(session, max(2, len(session)))
        return ind.last(series)

    def _add_option(self, plan: dict, symbol: str, side: str, underlying: dict, now: dt.datetime, request: PlanRequest) -> None:
        chain = self.chains.fetch(symbol, now, request.expiry)
        lot = self.market.lot_size(symbol)
        analysis = self.analyzer.analyze(chain, now, lot)
        kind = "CE" if side == "long" else "PE"
        pick = pick_strike(analysis, kind, request.strike or "atm")
        premium = option_levels(pick, underlying, now, request.hold, self.cfg, chain["expiry"])
        plan["instrument"].update({
            "kind": kind, "strike": pick["strike"], "expiry": chain["expiry"].isoformat(), "lot": lot,
            "tradingsymbol": "%s %s %s %s" % (symbol, chain["expiry"].strftime("%d%b%y").upper(), num(pick["strike"], 0), kind),
            "premium": premium, "iv": pick["iv"], "delta": pick["delta"], "theta": pick["theta"],
            "spread_pct": pick["spread_pct"], "oi": pick["oi"], "volume": pick["volume"], "bid": pick["bid"], "ask": pick["ask"],
            "spot_at_pick": analysis["spot"], "risk_per_lot": round(premium["risk"] * lot, 2),
            "reward_per_lot": round(premium["reward"] * lot, 2), "cost_per_lot": round(premium["entry"] * lot, 2)})
        plan["chain_view"] = {"pcr": analysis["pcr"], "max_pain": analysis["max_pain"], "bias": analysis["bias"],
                              "support": [x["strike"] for x in analysis["support"]],
                              "resistance": [x["strike"] for x in analysis["resistance"]]}

    def _add_future(self, plan: dict, symbol: str, underlying: dict) -> None:
        if not self.cfg.get("allow_futures", True):
            raise ValidationError("futures are switched off in your config (allow_futures)")
        lot = self.market.lot_size(symbol)
        margin_pct = self.cfg["futures_margin_pct"] if is_index(symbol) else self.cfg["stock_futures_margin_pct"]
        plan["instrument"].update({"lot": lot, "risk_per_lot": round(underlying["risk_points"] * lot, 2),
                                   "reward_per_lot": round(underlying["reward_points"] * lot, 2),
                                   "margin_per_lot_est": round(underlying["entry"] * lot * margin_pct / 100, 2),
                                   "note": "levels are on spot; shift them by the futures premium"})
