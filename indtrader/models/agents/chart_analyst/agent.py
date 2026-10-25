"""ChartAnalystAgent: NIFTY, BANKNIFTY, FINNIFTY and SENSEX on four timeframes."""

from indtrader.models.agents.base import Agent
from indtrader.models.agents.chart_analyst.mtf import MultiTimeframeAnalyzer


class ChartAnalystAgent(Agent):
    name = "chart-analyst"
    title = "Multi-timeframe chart analysis"

    def collect(self) -> dict:
        return MultiTimeframeAnalyzer(self.ctx.market).analyze(self.ctx.now)
