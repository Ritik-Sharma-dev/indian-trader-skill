"""DecisionMakerAgent: the live decision (or the day plan when the market is closed).

The Claude agent ``trade-decision-maker`` calls ``it.py decide now NIFTY``
on a timer; this class gives the same decision through the agent interface
(``it.py agent run decision-maker``) and the MCP server.
"""

from indtrader.models.agents.base import Agent
from indtrader.models.agents.decision_maker.decider import Decider


class DecisionMakerAgent(Agent):
    name = "decision-maker"
    title = "Trade decision"
    symbol = "NIFTY"

    def collect(self) -> dict:
        return {"decision": Decider(self.ctx).decide(self.symbol), "errors": []}
