"""StockPickerAgent: today's long and short F&O watchlists."""

from indtrader.models.agents.base import Agent
from indtrader.models.agents.stock_picker.picker import StockPicker


class StockPickerAgent(Agent):
    name = "stock-picker"
    title = "F&O stock picks"

    def collect(self) -> dict:
        return StockPicker(self.ctx.market).pick(self.ctx.now)
