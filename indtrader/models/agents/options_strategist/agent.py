"""OptionsStrategistAgent: the volatility regime and the best strike to buy, per index."""

from typing import Sequence

from indtrader.core.errors import IndianTraderError
from indtrader.models.agents.base import Agent
from indtrader.models.agents.options_strategist.strategist import OptionsStrategist


class OptionsStrategistAgent(Agent):
    name = "options-strategist"
    title = "Options strategist"
    symbols: Sequence[str] = ("NIFTY", "BANKNIFTY")

    def collect(self) -> dict:
        findings: dict = {"errors": [], "symbols": {}}
        for symbol in self.symbols:
            try:
                findings["symbols"][symbol] = OptionsStrategist(self.ctx).analyze(symbol)
            except IndianTraderError as exc:
                self.log.warning("options %s unavailable: %s", symbol, exc)
                findings["errors"].append("%s: %s" % (symbol, exc))
        return findings
