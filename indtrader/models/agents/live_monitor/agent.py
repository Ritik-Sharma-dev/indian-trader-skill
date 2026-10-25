"""LiveMonitorAgent: one live tick for each symbol.

The Claude agent ``live-market-monitor`` calls ``it.py live tick`` on a
timer; this agent class gives the same check through the agent interface
(``it.py agent run live-monitor``) and the MCP server.
"""

from typing import Sequence

from indtrader.models.agents.base import Agent
from indtrader.models.agents.live_monitor.monitor import LiveMonitor

#: the settings the live status block reads (entry window, trade limit, square-off)
RULE_KEYS = ("no_entries_before", "no_entries_after", "square_off_by", "live_max_trades")


class LiveMonitorAgent(Agent):
    name = "live-monitor"
    title = "Live monitor"
    symbols: Sequence[str] = ("NIFTY",)

    def collect(self) -> dict:
        monitor = LiveMonitor(self.ctx)
        return {"errors": [], "ticks": {symbol: monitor.tick(symbol) for symbol in self.symbols},
                "rules": {key: self.ctx.cfg[key] for key in RULE_KEYS}}
