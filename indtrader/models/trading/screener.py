"""Stock screener: your own rules over NSE quote data and daily technicals.

Metrics per stock (``None`` when the source has no value):

* NSE quote: price, change_pct, pe, sector_pe, pe_vs_sector (P/E / sector P/E),
  delivery_pct (delivered / traded quantity), pct_from_high / pct_from_low
  (52-week), volatility (NSE annualised %), mcap_cr, traded_value_cr,
  margin_pct (applicable margin), sector, industry, fo (in F&O)
* daily closes (one year, Yahoo): rsi, ret_5d, ret_20d, ret_60d,
  vs_ema50 / vs_ema200 (% above or below the average)

A rule file (or a built-in preset) says which stocks pass and how to rank them::

    {"name": "...",
     "rules": [{"metric": "pe_vs_sector", "op": "<", "value": 1}, ...],
     "rank":  [{"metric": "ret_20d", "order": "desc", "weight": 2}, ...],
     "missing": "fail"}

Ops: > >= < <= == != between ([low, high]) in / not in (a list). Every
pass and fail is explained with the number and the threshold. A screen is
a filter, not a recommendation.
"""

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from indtrader.core.errors import ConfigError, IndianTraderError, ValidationError
from indtrader.core.formatting import num
from indtrader.core.storage import read_json
from indtrader.models.analytics import indicators

log = logging.getLogger(__name__)

OPS = (">", ">=", "<", "<=", "==", "!=", "between", "in", "not in")

PRESETS: Dict[str, dict] = {
    "momentum": {
        "name": "Momentum: above both averages, strong month, not overbought",
        "rules": [{"metric": "vs_ema50", "op": ">", "value": 0}, {"metric": "vs_ema200", "op": ">", "value": 0},
                  {"metric": "ret_20d", "op": ">", "value": 3}, {"metric": "rsi", "op": "between", "value": [50, 75]}],
        "rank": [{"metric": "ret_20d", "order": "desc", "weight": 2}, {"metric": "delivery_pct", "order": "desc", "weight": 1}],
    },
    "value": {
        "name": "Value: cheaper than its sector, profitable, off the lows",
        "rules": [{"metric": "pe", "op": "between", "value": [0.1, 25]}, {"metric": "pe_vs_sector", "op": "<", "value": 0.8},
                  {"metric": "pct_from_low", "op": ">", "value": 5}],
        "rank": [{"metric": "pe_vs_sector", "order": "asc", "weight": 2}, {"metric": "ret_60d", "order": "desc", "weight": 1}],
    },
    "delivery": {
        "name": "Delivery buying: high delivery share on an up day, liquid",
        "rules": [{"metric": "delivery_pct", "op": ">=", "value": 55}, {"metric": "change_pct", "op": ">", "value": 0},
                  {"metric": "traded_value_cr", "op": ">=", "value": 50}],
        "rank": [{"metric": "delivery_pct", "order": "desc", "weight": 2}, {"metric": "change_pct", "order": "desc", "weight": 1}],
    },
    "near-high": {
        "name": "Near the 52-week high with the trend up",
        "rules": [{"metric": "pct_from_high", "op": ">=", "value": -3}, {"metric": "vs_ema50", "op": ">", "value": 0}],
        "rank": [{"metric": "pct_from_high", "order": "desc", "weight": 1}, {"metric": "ret_20d", "order": "desc", "weight": 1}],
    },
}


def _float(value: Any) -> Optional[float]:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _crore(value: Any, decimals: int) -> Optional[float]:
    rupees = _float(value)
    return round(rupees / 1e7, decimals) if rupees else None


def _ratio_pct(a: Optional[float], b: Optional[float]) -> Optional[float]:
    return round((a / b - 1) * 100, 2) if a is not None and b else None


# --- rules -------------------------------------------------------------------------------

@dataclass(frozen=True)
class Rule:
    metric: str
    op: str
    value: Any

    @classmethod
    def from_dict(cls, raw: dict) -> "Rule":
        if not isinstance(raw, dict) or not raw.get("metric") or raw.get("op") not in OPS or "value" not in raw:
            raise ValidationError("bad rule %r: needs metric, op (one of %s) and value" % (raw, " ".join(OPS)))
        if raw["op"] == "between" and not (isinstance(raw["value"], list) and len(raw["value"]) == 2):
            raise ValidationError("rule on %s: 'between' needs [low, high]" % raw["metric"])
        if raw["op"] in ("in", "not in") and not isinstance(raw["value"], list):
            raise ValidationError("rule on %s: '%s' needs a list" % (raw["metric"], raw["op"]))
        return cls(raw["metric"], raw["op"], raw["value"])

    def check(self, actual: Any) -> bool:
        op, want = self.op, self.value
        if op in ("in", "not in"):
            inside = str(actual).upper() in {str(v).upper() for v in want}
            return inside if op == "in" else not inside
        if op == "between":
            return want[0] <= actual <= want[1]
        if op in ("==", "!="):
            same = str(actual).upper() == str(want).upper() if isinstance(actual, str) or isinstance(want, str) else actual == want
            return same if op == "==" else not same
        return {">": actual > want, ">=": actual >= want, "<": actual < want, "<=": actual <= want}[op]

    def threshold(self) -> str:
        if self.op == "between":
            return "between %s and %s" % tuple(self.value)
        if isinstance(self.value, list):
            return "%s %s" % (self.op, ",".join(map(str, self.value)))
        return "%s %s" % (self.op, self.value)

    def describe(self) -> str:
        return "%s %s" % (self.metric, self.threshold())


@dataclass
class RuleSet:
    name: str
    rules: List[Rule]
    rank: List[dict]
    missing: str = "fail"

    @classmethod
    def from_dict(cls, raw: dict) -> "RuleSet":
        if not isinstance(raw, dict) or not raw.get("rules"):
            raise ValidationError("a rule set needs a non-empty 'rules' list")
        rank = raw.get("rank") or []
        for item in rank:
            if not item.get("metric") or item.get("order", "desc") not in ("asc", "desc"):
                raise ValidationError("bad rank item %r: needs metric and order asc/desc" % item)
        missing = raw.get("missing", "fail")
        if missing not in ("fail", "skip"):
            raise ValidationError("'missing' must be fail or skip")
        return cls(raw.get("name") or "My screen", [Rule.from_dict(r) for r in raw["rules"]], rank, missing)

    @classmethod
    def load(cls, preset: Optional[str] = None, path: Optional[str] = None) -> "RuleSet":
        if preset:
            if preset not in PRESETS:
                raise ValidationError("unknown preset %r (%s)" % (preset, ", ".join(sorted(PRESETS))))
            return cls.from_dict(PRESETS[preset])
        if not path or not os.path.exists(path):
            raise ConfigError("no rules: pass --preset (%s) or --rules FILE" % ", ".join(sorted(PRESETS)))
        return cls.from_dict(read_json(path))

    def evaluate(self, metrics: dict) -> Tuple[bool, List[str], List[str]]:
        """(passed, failures, skipped rules) for one stock."""
        failures, skipped = [], []
        for rule in self.rules:
            actual = metrics.get(rule.metric)
            if actual is None:
                (skipped if self.missing == "skip" else failures).append("%s is missing" % rule.metric)
                continue
            try:
                ok = rule.check(actual)
            except TypeError:
                ok = False
            if not ok:
                shown = num(actual) if isinstance(actual, float) else actual
                failures.append("%s %s, needs %s" % (rule.metric, shown, rule.threshold()))
        return not failures, failures, skipped

    def score(self, passed: List[dict]) -> None:
        """Weighted 0-1 score per stock over the rank metrics (min-max among the stocks that passed)."""
        for item in passed:
            item["score"] = 0.0
        if not self.rank or not passed:
            return
        totals = {id(p): [0.0, 0.0] for p in passed}
        for spec in self.rank:
            metric, weight, desc = spec["metric"], float(spec.get("weight", 1)), spec.get("order", "desc") == "desc"
            values = [p["metrics"].get(metric) for p in passed if isinstance(p["metrics"].get(metric), (int, float))]
            if not values:
                continue
            low, high = min(values), max(values)
            for p in passed:
                value = p["metrics"].get(metric)
                if not isinstance(value, (int, float)):
                    continue
                share = 1.0 if high == low else (value - low) / (high - low)
                totals[id(p)][0] += weight * (share if desc else 1 - share)
                totals[id(p)][1] += weight
        for p in passed:
            got, weights = totals[id(p)]
            p["score"] = round(got / weights, 3) if weights else 0.0


# --- metrics ----------------------------------------------------------------------------------

def quote_metrics(info: dict, fo: bool) -> dict:
    meta, trade, price_info, sec = (info.get(k) or {} for k in ("metaData", "tradeInfo", "priceInfo", "secInfo"))
    price = _float(trade.get("lastPrice")) or _float((info.get("orderBook") or {}).get("lastPrice"))
    pe, sector_pe = _float(sec.get("pdSymbolPe")), _float(sec.get("pdSectorPe"))
    high, low = _float(price_info.get("yearHigh")), _float(price_info.get("yearLow"))
    return {
        "price": price, "change_pct": _float(meta.get("pChange")), "pe": pe, "sector_pe": sector_pe,
        "pe_vs_sector": round(pe / sector_pe, 2) if pe and sector_pe and pe > 0 else None,
        "delivery_pct": _float(trade.get("deliveryToTradedQuantity") or sec.get("deliveryTotradedQuantity")),
        "pct_from_high": _ratio_pct(price, high), "pct_from_low": _ratio_pct(price, low),
        "volatility": _float(price_info.get("cmAnnualVolatility")),
        "mcap_cr": _crore(trade.get("totalMarketCap"), 0), "traded_value_cr": _crore(trade.get("totalTradedValue"), 2),
        "margin_pct": _float(trade.get("applicableMargin") or sec.get("applicableMargin")),
        "sector": (sec.get("sector") or "").strip() or None, "industry": (sec.get("basicIndustry") or "").strip() or None,
        "fo": fo,
    }


def close_metrics(closes: Sequence[float]) -> dict:
    if len(closes) < 21:
        return {}
    last = closes[-1]

    def ret(days: int) -> Optional[float]:
        return _ratio_pct(last, closes[-1 - days]) if len(closes) > days else None

    rsi = indicators.last(indicators.rsi(closes, 14))
    return {"rsi": round(rsi, 1) if rsi is not None else None, "ret_5d": ret(5), "ret_20d": ret(20),
            "ret_60d": ret(60), "vs_ema50": _ratio_pct(last, indicators.last(indicators.ema(closes, 50))) if len(closes) >= 50 else None,
            "vs_ema200": _ratio_pct(last, indicators.last(indicators.ema(closes, 200))) if len(closes) >= 200 else None}


class StockScreener:
    def __init__(self, market, workers: int = 4) -> None:
        self.market = market
        self.workers = max(1, workers)

    def metrics(self, symbols: List[str]) -> Tuple[Dict[str, dict], List[str]]:
        """``{symbol: metrics}`` and the symbols that could not be read."""
        fo = set(self.market.fo_stocks())
        closes = self.market.spark(symbols, rng="1y", interval="1d", name_prefix="screen-spark")

        def one(symbol: str) -> Tuple[str, Optional[dict]]:
            try:
                values = quote_metrics(self.market.nse.stock_info(symbol), symbol in fo)
            except IndianTraderError as exc:
                log.info("screen: %s has no NSE quote (%s)", symbol, exc)
                return symbol, None
            values.update(close_metrics((closes.get(symbol) or {}).get("closes") or []))
            return symbol, values

        with ThreadPoolExecutor(self.workers) as pool:
            results = list(pool.map(one, symbols))
        found = {symbol: values for symbol, values in results if values}
        return found, [symbol for symbol, values in results if not values]

    def run(self, rules: RuleSet, symbols: List[str], top: int = 20) -> dict:
        found, unreadable = self.metrics(symbols)
        passed, failed = [], []
        for symbol, values in found.items():
            ok, failures, skipped = rules.evaluate(values)
            row = {"symbol": symbol, "metrics": values, "failures": failures, "skipped": skipped}
            (passed if ok else failed).append(row)
        rules.score(passed)
        passed.sort(key=lambda r: -r["score"])
        failed.sort(key=lambda r: len(r["failures"]))
        return {"name": rules.name, "rules": [r.describe() for r in rules.rules], "screened": len(found), "unreadable": unreadable,
                "passed": passed[:top], "passed_count": len(passed), "closest_misses": failed[:5]}
