"""MarketAnalystAgent: the data map of the day for Nifty and Bank Nifty.

Pulse, intraday and daily charts, option-chain positioning, money flows and
last month's behaviour, merged into one table of key levels and three
conditional scenarios. Writes ``market-analyst-data.md`` for the Claude agent
``market-data-analyst``. It describes; it does not predict.
"""

from typing import List, Tuple

from indtrader.core import clock
from indtrader.core.errors import IndianTraderError
from indtrader.core.formatting import num
from indtrader.models.agents.base import Agent
from indtrader.models.agents.market_analyst.pulse import MarketPulse
from indtrader.models.analytics.charting import ChartAnalyzer
from indtrader.models.analytics.flows import MoneyFlows
from indtrader.models.analytics.history import MarketHistory
from indtrader.models.analytics.option_chain import OptionChainAnalyzer, OptionChainService

SYMBOLS = ("NIFTY", "BANKNIFTY")


def key_levels(intraday: dict, chain: dict) -> List[Tuple[float, str]]:
    """Levels from the chart and the chain, highest first; the next-session
    pivots once the day is complete, the current session's otherwise."""
    found: List[Tuple[float, str]] = []
    session = intraday.get("next_session")
    pivots = session["pivots"] if session else intraday.get("pivots")
    if session:
        found += [(session["high"], "day high"), (session["low"], "day low"), (session["close"], "close")]
    else:
        levels = intraday.get("levels", {})
        found += [(levels[k], label) for k, label in (("pdh", "previous high"), ("pdl", "previous low"),
                                                      ("or_high", "opening-range high"), ("or_low", "opening-range low")) if levels.get(k)]
    if pivots:
        found += [(pivots[k], k) for k in ("R2", "R1", "TC", "BC", "S1", "S2")]
    if chain:
        found += [(chain["resistance"][0]["strike"], "call wall"), (chain["support"][0]["strike"], "put wall"),
                  (chain["max_pain"], "max pain")]
    return sorted(found, key=lambda x: -x[0])


def scenarios(price: float, levels: List[Tuple[float, str]]) -> List[str]:
    above = sorted((lv for lv in levels if lv[0] > price), key=lambda x: x[0])
    below = sorted((lv for lv in levels if lv[0] < price), key=lambda x: -x[0])
    out = []
    if len(above) >= 2:
        out.append("Bullish if a 5-minute candle closes above %s (%s): first target %s (%s), invalid back below %s."
                   % (num(above[0][0]), above[0][1], num(above[1][0]), above[1][1], num(price)))
    if len(below) >= 2:
        out.append("Bearish if a 5-minute candle closes below %s (%s): first target %s (%s), invalid back above %s."
                   % (num(below[0][0]), below[0][1], num(below[1][0]), below[1][1], num(price)))
    if above and below:
        out.append("Range between %s and %s: no trade inside it." % (num(below[0][0]), num(above[0][0])))
    return out


class MarketAnalystAgent(Agent):
    name = "market-analyst"
    title = "Market analytics (data)"

    def collect(self) -> dict:
        ctx = self.ctx
        findings: dict = {"errors": [], "symbols": {}}
        findings["pulse"] = MarketPulse(ctx.market).collect()
        findings["errors"] += findings["pulse"]["errors"]
        charts, history = ChartAnalyzer(ctx.market), MarketHistory(ctx.market, ctx.cfg)
        chains, analyzer = OptionChainService(ctx.market), OptionChainAnalyzer(ctx.cfg)
        for symbol in SYMBOLS:
            entry: dict = {}
            for key, job in (("intraday", lambda: charts.analyze(symbol, "5m", now=ctx.now)),
                             ("daily", lambda: charts.analyze(symbol, "1d", now=ctx.now)),
                             ("chain", lambda: analyzer.analyze(chains.fetch(symbol, ctx.now), ctx.now, ctx.market.lot_size(symbol))),
                             ("history", lambda: history.analyse(symbol, 22, ctx.now))):
                try:
                    entry[key] = job()
                except IndianTraderError as exc:
                    self.log.warning("%s %s unavailable: %s", symbol, key, exc)
                    findings["errors"].append("%s %s: %s" % (symbol, key, exc))
            for key in ("intraday", "daily"):
                if key in entry:
                    entry[key].pop("series", None)
            if "intraday" in entry:
                entry["levels"] = key_levels(entry["intraday"], entry.get("chain"))
                entry["scenarios"] = scenarios(entry["intraday"]["last"], entry["levels"])
            findings["symbols"][symbol] = entry
        flows = MoneyFlows(ctx.market).collect(ctx.now, "participants")
        findings["flows"] = flows.get("participants")
        findings["errors"] += flows["errors"]
        findings["status"] = clock.market_status(ctx.now)
        return findings
