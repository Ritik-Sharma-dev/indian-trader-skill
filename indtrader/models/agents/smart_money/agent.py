"""SmartMoneyAgent: institutions, insiders and big deals."""

from indtrader.models.agents.base import Agent
from indtrader.models.agents.smart_money.tracker import SmartMoneyTracker


class SmartMoneyAgent(Agent):
    name = "smart-money"
    title = "Smart money"

    def collect(self) -> dict:
        return SmartMoneyTracker(self.ctx.market).collect(self.ctx.now)
