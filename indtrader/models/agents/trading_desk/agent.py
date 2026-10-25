"""TradingDeskAgent: research -> analysis -> risk -> decision, in one run.

The stages are the other agents, run in order so each can use the one
before it:

1. research: ``global-news`` (overnight markets, calendar, themed headlines),
   ``india-news`` (headlines, policy, filings, flows, results) and
   ``smart-money`` (FII / DII, FII positioning, big deals, insiders)
2. analysis: ``market-analyst`` (pulse, charts, option chains, levels and
   scenarios), ``chart-analyst`` (four indices on four timeframes),
   ``options-strategist`` (volatility regime, the strike to buy) and
   ``stock-picker`` (the F&O watchlists)
3. risk: ``risk-manager`` (loss budget, lots allowed, the kill switch)
4. decision: the decision maker's day plan before the open, or the live
   decision during the session

The findings hold every stage's own findings under ``reports``; a failing
stage is noted and the desk carries on.
"""

import time
from typing import Sequence, Type

from indtrader.core import clock
from indtrader.core.errors import IndianTraderError
from indtrader.models.agents.base import Agent
from indtrader.models.agents.chart_analyst import ChartAnalystAgent
from indtrader.models.agents.decision_maker.decider import Decider
from indtrader.models.agents.global_news import GlobalNewsAgent
from indtrader.models.agents.india_news import IndiaNewsAgent
from indtrader.models.agents.market_analyst import MarketAnalystAgent
from indtrader.models.agents.options_strategist import OptionsStrategistAgent
from indtrader.models.agents.risk_manager import RiskManagerAgent
from indtrader.models.agents.smart_money import SmartMoneyAgent
from indtrader.models.agents.stock_picker import StockPickerAgent

STAGES: Sequence[Sequence[Type[Agent]]] = (
    (GlobalNewsAgent, IndiaNewsAgent, SmartMoneyAgent),
    (MarketAnalystAgent, ChartAnalystAgent, OptionsStrategistAgent, StockPickerAgent),
    (RiskManagerAgent,),
)
STAGE_NAMES = {agent.name: "%d %s" % (number, title) for number, (title, stage) in
               enumerate(zip(("research", "analysis", "risk"), STAGES), 1) for agent in stage}


class TradingDeskAgent(Agent):
    name = "trading-desk"
    title = "Trading desk"
    symbol = "NIFTY"

    def collect(self) -> dict:
        findings: dict = {"errors": [], "stages": [], "reports": {}}
        for stage in STAGES:
            for agent_class in stage:
                started = time.time()
                try:
                    stage_findings = agent_class(self.ctx).collect()
                    findings["reports"][agent_class.name] = stage_findings
                    findings["stages"].append({"agent": agent_class.name, "seconds": round(time.time() - started, 1),
                                               "notes": len(stage_findings.get("errors", []))})
                except IndianTraderError as exc:
                    self.log.warning("desk: %s failed: %s", agent_class.name, exc)
                    findings["errors"].append("%s: %s" % (agent_class.name, exc))
                    findings["stages"].append({"agent": agent_class.name, "seconds": round(time.time() - started, 1), "failed": str(exc)})
        started = time.time()
        try:
            decider = Decider(self.ctx)
            live = clock.market_status(self.ctx.now)["state"] == "open"
            findings["decision"] = decider.decide(self.symbol) if live else decider.plan(self.symbol)
            findings["stages"].append({"agent": "decision-maker", "seconds": round(time.time() - started, 1)})
        except IndianTraderError as exc:
            findings["errors"].append("decision-maker: %s" % exc)
            findings["stages"].append({"agent": "decision-maker", "seconds": round(time.time() - started, 1), "failed": str(exc)})
        return findings
