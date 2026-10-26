"""Option chain analytics from NSE's public option chain.

For one expiry it works out:

* PCR: total put OI / call OI, for the strikes near spot, and of today's change
* max pain: the strike where option buyers together collect the least at expiry
* OI walls: biggest call OI above spot (resistance), biggest put OI below
  (support), and where most OI was written today
* ATM straddle: ATM call + put premium, the market's priced-in move to expiry
* IV and Greeks: NSE's IV when given, else solved from the price; NSE uses
  Black-Scholes on spot with a 10% rate and calendar time from its snapshot
* a positioning score from PCR, OI change and the walls (not a forecast)

OI is in contracts, as NSE reports it. BSE (SENSEX) chains are not covered.
"""

import datetime as dt
import logging
import math
from collections import Counter
from typing import Dict, List, Optional

from indtrader.core import clock, settings
from indtrader.core.errors import DataError, ValidationError
from indtrader.core.formatting import num, round_tick, strike as strike_text
from indtrader.models.analytics import blackscholes as bs
from indtrader.models.data.symbols import BSE_INDICES, NSE_INDICES

log = logging.getLogger(__name__)

STRIKE_DEPTH = {"itm1": 1, "itm2": 2, "otm1": -1, "otm2": -2}


# --- parsing --------------------------------------------------------------------

def _leg(record: Optional[dict]) -> Optional[dict]:
    if not record:
        return None
    return {"ltp": record.get("lastPrice") or 0.0, "chg": record.get("change") or 0.0,
            "oi": record.get("openInterest") or 0, "coi": record.get("changeinOpenInterest") or 0,
            "vol": record.get("totalTradedVolume") or 0, "iv": record.get("impliedVolatility") or 0.0,
            "bid": record.get("buyPrice1") or 0.0, "ask": record.get("sellPrice1") or 0.0}


def parse_chain(payload: dict, expiry: Optional[dt.date] = None) -> dict:
    records = payload.get("records") or {}
    wanted = expiry.strftime("%d-%b-%Y") if expiry else None
    rows = [{"strike": float(r["strikePrice"]), "ce": _leg(r.get("CE")), "pe": _leg(r.get("PE"))}
            for r in records.get("data") or []
            if not (wanted and r.get("expiryDates") and r["expiryDates"] != wanted)]
    rows.sort(key=lambda r: r["strike"])
    spot = records.get("underlyingValue")
    if not rows or not spot:
        raise DataError("the option chain was empty (market data not published yet?)")
    return {"spot": float(spot), "timestamp": records.get("timestamp"), "rows": rows}


def pick_expiry(expiries: List[dt.date], now: dt.datetime, which: Optional[str] = "near") -> dt.date:
    """``near`` = first expiry not yet closed; ``next``; ``monthly``; or a date."""
    live = [e for e in expiries if clock.expiry_close(e) > now]
    if not live:
        raise DataError("no live expiry")
    if which in (None, "near", "weekly"):
        return live[0]
    if which == "next":
        return live[1] if len(live) > 1 else live[0]
    if which == "monthly":
        return next((e for e in live if (e + dt.timedelta(days=7)).month != e.month), live[-1])
    for fmt in ("%Y-%m-%d", "%d-%b-%Y"):
        try:
            chosen = dt.datetime.strptime(which, fmt).date()
            break
        except ValueError:
            continue
    else:
        raise ValidationError("cannot read the expiry %r (YYYY-MM-DD, near, next, monthly)" % which)
    if chosen not in expiries:
        raise ValidationError("%s is not an expiry; live ones: %s" % (chosen, ", ".join(e.isoformat() for e in live[:6])))
    return chosen


def chain_time(chain: dict, now: dt.datetime) -> dt.datetime:
    """When the chain's prices are from: NSE's timestamp, capped at that day's
    close and at ``now``. After the close, time to expiry runs from the close."""
    try:
        stamp = dt.datetime.strptime(chain.get("timestamp") or "", "%d-%b-%Y %H:%M:%S").replace(tzinfo=clock.IST)
    except ValueError:
        return now
    return min(stamp, clock.at(stamp.date(), clock.derivatives_close(stamp.date())), now)


# --- per-strike maths ----------------------------------------------------------------

def strike_step(rows: List[dict], spot: float) -> float:
    near = [r["strike"] for r in rows if abs(r["strike"] - spot) / spot < 0.05]
    gaps = Counter(round(b - a, 2) for a, b in zip(near, near[1:]) if b > a)
    return gaps.most_common(1)[0][0] if gaps else 50.0


def max_pain(rows: List[dict]) -> float:
    best, best_payout = None, None
    for strike in (r["strike"] for r in rows):
        payout = 0.0
        for r in rows:
            if r["ce"]:
                payout += max(0.0, strike - r["strike"]) * r["ce"]["oi"]
            if r["pe"]:
                payout += max(0.0, r["strike"] - strike) * r["pe"]["oi"]
        if best_payout is None or payout < best_payout:
            best, best_payout = strike, payout
    return best


def premium_of(leg: Optional[dict]) -> Optional[float]:
    """A fair price: the bid/ask midpoint when the last trade is stale, else the LTP."""
    if not leg:
        return None
    bid, ask, last = leg["bid"], leg["ask"], leg["ltp"]
    if bid > 0 and ask > 0 and ask >= bid:
        middle = (ask + bid) / 2
        if last <= 0 or abs(last - middle) / middle > 0.25:
            return middle
    return last or None


def spread_pct(leg: Optional[dict]) -> Optional[float]:
    if not leg or leg["bid"] <= 0 or leg["ask"] <= 0:
        return None
    middle = (leg["bid"] + leg["ask"]) / 2
    return (leg["ask"] - leg["bid"]) / middle * 100 if middle else None


def implied_spot(rows: List[dict], atm_index: int, years: float, rate: float, depth: int = 3) -> Optional[float]:
    """The underlying price the options are trading on, from put-call parity at the strikes nearest ATM."""
    values = []
    for row in rows[max(0, atm_index - depth): atm_index + depth + 1]:
        call, put = premium_of(row["ce"]), premium_of(row["pe"])
        if call and put and (row["ce"] or {}).get("vol") and (row["pe"] or {}).get("vol"):
            values.append(call - put + row["strike"] * math.exp(-rate * years))
    if not values:
        return None
    values.sort()
    return values[len(values) // 2]


def leg_metrics(kind: str, leg: Optional[dict], strike: float, spot: float, years: float, rate: float,
                use_nse_iv: bool = True) -> Optional[dict]:
    """IV (NSE's, else solved) and Greeks for one option."""
    if not leg:
        return None
    premium = premium_of(leg)
    iv = leg["iv"] / 100.0 if (leg["iv"] and use_nse_iv) else bs.implied_vol(kind, premium, spot, strike, years, rate)
    return {"premium": premium, "iv": iv, "spread_pct": spread_pct(leg),
            "greeks": bs.greeks(kind, spot, strike, years, rate, iv) if iv else None}


# --- service and analyzer ---------------------------------------------------------------

class OptionChainService:
    """Fetches NSE option chains through MarketData."""

    def __init__(self, market) -> None:
        self.market = market

    @staticmethod
    def chain_kind(symbol: str) -> str:
        return "Indices" if symbol.upper() in NSE_INDICES else "Equity"

    def expiries(self, symbol: str) -> List[dt.date]:
        upper = symbol.upper()
        if upper in BSE_INDICES:
            raise ValidationError("%s options trade on BSE; NSE's chain does not cover them" % upper)
        return self.market.nse.option_expiries(upper)

    def fetch(self, symbol: str, now: dt.datetime, expiry: Optional[str] = "near") -> dict:
        upper = symbol.upper()
        expiries = self.expiries(upper)
        chosen = pick_expiry(expiries, now, expiry)
        chain = parse_chain(self.market.nse.option_chain(upper, chosen, self.chain_kind(upper)), chosen)
        chain.update(symbol=upper, expiry=chosen, expiries=[e for e in expiries if clock.expiry_close(e) > now])
        log.debug("%s chain %s: %d strikes, spot %.2f", upper, chosen, len(chain["rows"]), chain["spot"])
        return chain


class OptionChainAnalyzer:
    def __init__(self, cfg: Optional[settings.Settings] = None) -> None:
        self.cfg = cfg if cfg is not None else settings.load()

    def analyze(self, chain: dict, now: dt.datetime, lot: Optional[int] = None, band: int = 10) -> dict:
        rate = self.cfg["risk_free_rate_pct"] / 100.0
        rows, spot = chain["rows"], chain["spot"]
        expiry_at = clock.expiry_close(chain["expiry"])
        as_of = chain_time(chain, now)
        years = clock.years_to(expiry_at, as_of)
        atm = min(rows, key=lambda r: abs(r["strike"] - spot))["strike"]
        atm_index = next(i for i, r in enumerate(rows) if r["strike"] == atm)
        parity = implied_spot(rows, atm_index, years, rate)
        parity_gap = (parity / spot - 1) * 100 if parity else None
        mismatch = parity_gap is not None and abs(parity_gap) > self.cfg["max_spot_parity_gap_pct"]
        if mismatch:
            spot = parity
            atm = min(rows, key=lambda r: abs(r["strike"] - spot))["strike"]
            atm_index = next(i for i, r in enumerate(rows) if r["strike"] == atm)
        use_nse_iv = not mismatch
        near = rows[max(0, atm_index - band): atm_index + band + 1]

        def total(subset: List[dict], side: str, key: str) -> float:
            return sum((r[side] or {}).get(key, 0) or 0 for r in subset)

        ce_oi, pe_oi = total(rows, "ce", "oi"), total(rows, "pe", "oi")
        ce_added, pe_added = total(rows, "ce", "coi"), total(rows, "pe", "coi")
        near_ce, near_pe = total(near, "ce", "oi"), total(near, "pe", "oi")
        pcr = pe_oi / ce_oi if ce_oi else None
        resistance = sorted((r for r in rows if r["strike"] >= spot and r["ce"]), key=lambda r: -r["ce"]["oi"])[:3]
        support = sorted((r for r in rows if r["strike"] <= spot and r["pe"]), key=lambda r: -r["pe"]["oi"])[:3]
        call_writing = sorted((r for r in rows if r["ce"]), key=lambda r: -r["ce"]["coi"])[:3]
        put_writing = sorted((r for r in rows if r["pe"]), key=lambda r: -r["pe"]["coi"])[:3]

        atm_row = rows[atm_index]
        ce_metrics = leg_metrics("CE", atm_row["ce"], atm, spot, years, rate, use_nse_iv)
        pe_metrics = leg_metrics("PE", atm_row["pe"], atm, spot, years, rate, use_nse_iv)
        straddle = ((ce_metrics or {}).get("premium") or 0) + ((pe_metrics or {}).get("premium") or 0)
        ivs = [m["iv"] for m in (ce_metrics, pe_metrics) if m and m["iv"]]
        atm_iv = sum(ivs) / len(ivs) if ivs else None
        score, reasons = self._positioning(pcr, ce_added, pe_added, resistance, support, spot)

        return {
            "symbol": chain["symbol"], "expiry": chain["expiry"].isoformat(), "timestamp": chain.get("timestamp"),
            "spot": chain["spot"], "pricing_spot": spot, "parity_spot": parity, "parity_gap_pct": parity_gap,
            "spot_mismatch": mismatch, "lot": lot, "days_to_expiry": round((expiry_at - as_of).total_seconds() / 86400, 2),
            "strike_step": strike_step(rows, spot), "atm": atm,
            "pcr": pcr, "pcr_near": near_pe / near_ce if near_ce else None,
            "pcr_change": pe_added / ce_added if ce_added > 0 else None,
            "total_ce_oi": ce_oi, "total_pe_oi": pe_oi, "ce_oi_added": ce_added, "pe_oi_added": pe_added,
            "max_pain": max_pain(rows),
            "resistance": [{"strike": r["strike"], "oi": r["ce"]["oi"], "coi": r["ce"]["coi"]} for r in resistance],
            "support": [{"strike": r["strike"], "oi": r["pe"]["oi"], "coi": r["pe"]["coi"]} for r in support],
            "ce_writing": [{"strike": r["strike"], "coi": r["ce"]["coi"]} for r in call_writing],
            "pe_writing": [{"strike": r["strike"], "coi": r["pe"]["coi"]} for r in put_writing],
            "atm_iv": atm_iv, "straddle": straddle or None,
            "expected_move": straddle or (bs.expected_move(spot, atm_iv, years) if atm_iv else None),
            "bias": self._bias_label(score), "bias_score": score, "reasons": reasons,
            "near": [self._strike_row(r, spot, years, rate, use_nse_iv) for r in near],
        }

    @staticmethod
    def _positioning(pcr, ce_added, pe_added, resistance, support, spot):
        score, reasons = 0, []
        if pcr is not None:
            if pcr >= 1.2:
                score += 1
                reasons.append("PCR %.2f: put writers dominate (support below)" % pcr)
            elif pcr <= 0.8:
                score -= 1
                reasons.append("PCR %.2f: call writers dominate (supply above)" % pcr)
            else:
                reasons.append("PCR %.2f: balanced" % pcr)
        if pe_added > ce_added * 1.2 and pe_added > 0:
            score += 1
            reasons.append("more puts written today than calls (%s vs %s)" % (pe_added, ce_added))
        elif ce_added > pe_added * 1.2 and ce_added > 0:
            score -= 1
            reasons.append("more calls written today than puts (%s vs %s)" % (ce_added, pe_added))
        if resistance and support:
            wall_up, wall_down = resistance[0]["strike"], support[0]["strike"]
            room_up, room_down = wall_up - spot, spot - wall_down
            if room_up < room_down * 0.5:
                score -= 1
                reasons.append("spot is close to the call wall %s (room up %.0f, down %.0f)" % (num(wall_up, 0), room_up, room_down))
            elif room_down < room_up * 0.5:
                score += 1
                reasons.append("spot is close to the put wall %s (room down %.0f, up %.0f)" % (num(wall_down, 0), room_down, room_up))
        return score, reasons

    @staticmethod
    def _bias_label(score: int) -> str:
        if score >= 2:
            return "bullish"
        if score == 1:
            return "mildly bullish"
        if score <= -2:
            return "bearish"
        return "mildly bearish" if score == -1 else "neutral"

    @staticmethod
    def _strike_row(row: dict, spot: float, years: float, rate: float, use_nse_iv: bool = True) -> dict:
        out: Dict[str, object] = {"strike": row["strike"]}
        for kind, key in (("CE", "ce"), ("PE", "pe")):
            metrics = leg_metrics(kind, row[key], row["strike"], spot, years, rate, use_nse_iv)
            leg = dict(row[key] or {})
            if metrics:
                leg.update(premium=metrics["premium"], iv_calc=metrics["iv"], spread_pct=metrics["spread_pct"],
                           **(metrics["greeks"] or {}))
            out[key] = leg
        return out


def pick_strike(analysis: dict, kind: str, choice: Optional[str] = "atm") -> dict:
    """``kind`` CE / PE; ``choice`` atm, itm1, itm2, otm1, otm2 or a strike."""
    kind = kind.upper()
    near = analysis["near"]
    if choice in (None, "atm"):
        target = analysis["atm"]
    else:
        try:
            target = float(choice)
        except ValueError:
            depth = STRIKE_DEPTH.get(choice)
            if depth is None:
                raise ValidationError("strike choice %r: use atm, itm1, itm2, otm1, otm2 or a number" % choice) from None
            step = analysis["strike_step"]
            target = analysis["atm"] - depth * step if kind == "CE" else analysis["atm"] + depth * step
    row = next((r for r in near if abs(r["strike"] - target) < 1e-6), None)
    if row is None:
        raise ValidationError("strike %s is not in the chain near spot (%s ... %s)"
                              % (strike_text(target), strike_text(near[0]["strike"]), strike_text(near[-1]["strike"])))
    leg = row[kind.lower()]
    if not leg or not leg.get("premium"):
        raise DataError("%s %s %s has no price" % (analysis["symbol"], strike_text(target), kind))
    picked = {"symbol": analysis["symbol"], "expiry": analysis["expiry"], "strike": row["strike"], "kind": kind,
              "premium": round_tick(leg["premium"]), "ltp": leg.get("ltp"), "bid": leg.get("bid"), "ask": leg.get("ask"),
              "iv": leg.get("iv_calc"), "delta": leg.get("delta"), "gamma": leg.get("gamma"), "theta": leg.get("theta"),
              "vega": leg.get("vega"), "oi": leg.get("oi"), "volume": leg.get("vol"), "spread_pct": leg.get("spread_pct"),
              "spot": analysis.get("pricing_spot") or analysis["spot"], "lot": analysis.get("lot")}
    if analysis.get("lot"):
        picked["cost_per_lot"] = round(picked["premium"] * analysis["lot"], 2)
    return picked
