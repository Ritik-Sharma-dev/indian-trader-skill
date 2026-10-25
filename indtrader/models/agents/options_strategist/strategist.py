"""Which option to buy, and whether options are cheap or dear right now.

* **Volatility regime**: ATM implied volatility against the index's 20-day
  realised volatility (close-to-close, annualised). Implied far above
  realised means the buyer overpays for movement; far below means cheap.
  India VIX against its own one-year range gives the market-wide view.
* **Expected move**: one day of the ATM IV, in index points.
* **Strike choice**, for calls and puts: ATM, ITM1, ITM2 and OTM1, each with
  delta, premium, cost per lot, bid-ask spread, open interest, theta per
  hour, and the index move needed in 30 minutes just to pay for the spread
  and the decay. Scored on: delta 0.45-0.70 (moves with the index without
  paying for a lot of time value), spread under the config limit, open
  interest over the config minimum, the lowest break-even move.

A buyer's checklist, not a recommendation to trade.
"""

import logging
import math
from typing import List, Optional, Sequence

from indtrader.core.errors import IndianTraderError
from indtrader.core.formatting import inr, num
from indtrader.models.analytics.option_chain import OptionChainAnalyzer, OptionChainService, pick_strike

log = logging.getLogger(__name__)

CHOICES: Sequence[str] = ("itm2", "itm1", "atm", "otm1")
TRADING_DAYS = 252
SESSION_HOURS = 6.25


def realised_vol(closes: Sequence[float], days: int = 20) -> Optional[float]:
    """Annualised close-to-close volatility of the last ``days`` daily returns (0.15 = 15 %)."""
    if len(closes) < days + 1:
        return None
    returns = [math.log(closes[i] / closes[i - 1]) for i in range(len(closes) - days, len(closes))]
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return math.sqrt(variance) * math.sqrt(TRADING_DAYS)


def regime(iv: Optional[float], hv: Optional[float]) -> dict:
    if not iv or not hv:
        return {"label": "UNKNOWN", "ratio": None, "advice": "volatility data missing"}
    ratio = iv / hv
    if ratio >= 1.25:
        label, advice = "EXPENSIVE", "implied volatility is well above what the index has been doing: buy ITM (less time value) and take profits quickly"
    elif ratio <= 0.85:
        label, advice = "CHEAP", "implied volatility is below recent movement: ATM options are fair value for a buyer"
    else:
        label, advice = "FAIR", "implied volatility is in line with recent movement"
    return {"label": label, "ratio": round(ratio, 2), "advice": advice}


def percentile(value: float, history: Sequence[float]) -> Optional[float]:
    return round(sum(1 for h in history if h <= value) / len(history) * 100) if history else None


def score_strike(pick: dict, cfg: dict) -> dict:
    """Checks, the break-even move in 30 minutes, and a 0-4 score for one strike."""
    delta = abs(pick.get("delta") or 0)
    theta_hour = abs(pick.get("theta") or 0) / SESSION_HOURS
    spread = (pick["ask"] - pick["bid"]) if pick.get("ask") and pick.get("bid") else None
    friction = (spread or 0) + theta_hour / 2              # cross the spread once, half an hour of decay
    breakeven = friction / delta if delta else None
    checks = {"delta 0.45-0.70": 0.45 <= delta <= 0.70,
              "spread <= %.1f%%" % cfg["max_option_spread_pct"]: pick.get("spread_pct") is not None and pick["spread_pct"] <= cfg["max_option_spread_pct"],
              "OI >= %d" % cfg["min_option_oi"]: (pick.get("oi") or 0) >= cfg["min_option_oi"],
              "delta >= %.2f" % cfg["min_option_delta"]: delta >= cfg["min_option_delta"]}
    return dict(pick, delta_abs=round(delta, 2), theta_hour=round(theta_hour, 2), spread=round(spread, 2) if spread is not None else None,
                breakeven_pts=round(breakeven, 1) if breakeven else None, checks=checks, score=sum(checks.values()))


def best(candidates: List[dict]) -> Optional[dict]:
    """Highest score, then the smallest break-even move."""
    usable = [c for c in candidates if c.get("breakeven_pts") is not None]
    return min(usable, key=lambda c: (-c["score"], c["breakeven_pts"])) if usable else None


class OptionsStrategist:
    def __init__(self, ctx) -> None:
        self.ctx = ctx
        self.market = ctx.market

    def analyze(self, symbol: str = "NIFTY") -> dict:
        symbol = symbol.upper()
        now, cfg = self.ctx.now, self.ctx.cfg
        chain = OptionChainService(self.market).fetch(symbol, now, "near")
        analysis = OptionChainAnalyzer(cfg).analyze(chain, now, self.market.lot_size(symbol))
        result: dict = {"symbol": symbol, "expiry": str(chain["expiry"]), "days_to_expiry": analysis["days_to_expiry"],
                        "spot": analysis["spot"], "atm": analysis["atm"], "lot": analysis.get("lot"), "atm_iv": analysis.get("atm_iv"),
                        "errors": [], "calls": [], "puts": []}
        iv = analysis.get("atm_iv")
        try:
            _, daily = self.market.candles(symbol, "1d", "3mo")
            closes = [b["c"] for b in self.market.fill_daily_holes(symbol, [b for b in daily if b["t"].date() <= now.date()], now)]
            result["realised_vol"] = realised_vol(closes)
        except IndianTraderError as exc:
            result["errors"].append("daily bars: %s" % exc)
            result["realised_vol"] = None
        result["regime"] = regime(iv, result["realised_vol"])
        result["day_move"] = round(analysis["spot"] * iv / math.sqrt(TRADING_DAYS), 1) if iv else None
        result["expected_move_to_expiry"] = analysis.get("expected_move")
        try:
            _, vix_bars = self.market.candles("INDIAVIX", "1d", "1y")
            vix_closes = [b["c"] for b in vix_bars if b["t"].date() <= now.date()]
            result["vix"] = {"last": vix_closes[-1], "percentile_1y": percentile(vix_closes[-1], vix_closes),
                             "low_1y": min(vix_closes), "high_1y": max(vix_closes)}
        except (IndianTraderError, IndexError, ValueError) as exc:
            result["errors"].append("India VIX history: %s" % exc)
        for kind, key in (("CE", "calls"), ("PE", "puts")):
            for choice in CHOICES:
                try:
                    result[key].append(dict(score_strike(pick_strike(analysis, kind, choice), cfg), choice=choice.upper()))
                except IndianTraderError as exc:
                    log.info("%s %s %s skipped: %s", symbol, kind, choice, exc)
        result["best_call"], result["best_put"] = best(result["calls"]), best(result["puts"])
        result["notes"] = self._notes(result)
        return result

    def _notes(self, result: dict) -> List[str]:
        notes = []
        if result["days_to_expiry"] < 1:
            notes.append("expiry day: time value collapses through the afternoon; buy ITM and be out by %s"
                         % self.ctx.cfg["expiry_day_no_entries_after"])
        elif result["days_to_expiry"] < 2:
            notes.append("one day to expiry: decay is fast; prefer ITM1 over ATM")
        vix = result.get("vix") or {}
        if vix.get("percentile_1y") is not None and vix["percentile_1y"] >= 80:
            notes.append("India VIX is in the top 20%% of its year (%s): premiums are rich and swings wide" % num(vix["last"]))
        lot_cost = (result.get("best_call") or {}).get("cost_per_lot")
        if lot_cost and lot_cost > self.ctx.cfg["capital"] * self.ctx.cfg["max_capital_per_trade_pct"] / 100:
            notes.append("one lot (%s) is more than %s%% of your capital" % (inr(lot_cost, 0), self.ctx.cfg["max_capital_per_trade_pct"]))
        return notes
