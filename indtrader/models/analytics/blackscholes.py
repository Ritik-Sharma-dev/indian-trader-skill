"""Black-Scholes for European options.

NSE index and stock options are European and cash-settled. No dividends.
Time in years, rate and volatility as decimals (10% -> 0.10).

Greeks: delta per point, gamma per point, theta per CALENDAR day (rupees
per unit per day), vega per volatility point (1%).
"""

import math
from typing import Dict, Optional


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _d1_d2(spot: float, strike: float, years: float, rate: float, sigma: float):
    width = sigma * math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate + 0.5 * sigma * sigma) * years) / width
    return d1, d1 - width


def price(kind: str, spot: float, strike: float, years: float, rate: float, sigma: float) -> float:
    """Option value; ``kind`` is 'CE' (call) or 'PE' (put)."""
    call = kind.upper() == "CE"
    if years <= 0 or sigma <= 0:
        return max(0.0, spot - strike) if call else max(0.0, strike - spot)
    d1, d2 = _d1_d2(spot, strike, years, rate, sigma)
    discount = math.exp(-rate * years)
    if call:
        return spot * norm_cdf(d1) - strike * discount * norm_cdf(d2)
    return strike * discount * norm_cdf(-d2) - spot * norm_cdf(-d1)


def greeks(kind: str, spot: float, strike: float, years: float, rate: float, sigma: float) -> Dict[str, float]:
    call = kind.upper() == "CE"
    if years <= 0 or sigma <= 0:
        in_the_money = spot > strike if call else spot < strike
        return {"delta": (1.0 if in_the_money else 0.0) * (1 if call else -1), "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    d1, d2 = _d1_d2(spot, strike, years, rate, sigma)
    root = math.sqrt(years)
    discount = math.exp(-rate * years)
    gamma = norm_pdf(d1) / (spot * sigma * root)
    vega = spot * norm_pdf(d1) * root / 100.0
    decay = -spot * norm_pdf(d1) * sigma / (2 * root)
    if call:
        delta = norm_cdf(d1)
        theta = decay - rate * strike * discount * norm_cdf(d2)
    else:
        delta = norm_cdf(d1) - 1.0
        theta = decay + rate * strike * discount * norm_cdf(-d2)
    return {"delta": delta, "gamma": gamma, "theta": theta / 365.0, "vega": vega}


def implied_vol(kind: str, premium: Optional[float], spot: float, strike: float, years: float, rate: float,
                low: float = 0.005, high: float = 5.0, tolerance: float = 1e-5) -> Optional[float]:
    """Volatility that reproduces ``premium`` (bisection); ``None`` when the
    premium is zero, below intrinsic value, or beyond any sane volatility."""
    if premium is None or premium <= 0 or years <= 0:
        return None
    if premium < price(kind, spot, strike, years, rate, low) - 1e-6:
        return None
    if premium > price(kind, spot, strike, years, rate, high):
        return None
    for _ in range(100):
        middle = (low + high) / 2
        if price(kind, spot, strike, years, rate, middle) > premium:
            high = middle
        else:
            low = middle
        if high - low < tolerance:
            break
    return (low + high) / 2


def expected_move(spot: float, sigma: float, years: float) -> float:
    """One standard deviation move by ``years``: spot x sigma x sqrt(years)."""
    return spot * sigma * math.sqrt(years)
