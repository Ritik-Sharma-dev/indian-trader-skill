"""The agents. Each lives in its own package with its own code:

    india_news/      Indian market news, filings, policy and flows
    global_news/     US and global markets, calendar and themed headlines
    market_analyst/  pulse, charts, option chains, history: levels and scenarios
    live_monitor/    the live entry / exit engine
    decision_maker/  one instruction now: buy, hold, exit, wait or no trade
    trading_desk/    research -> analysis -> risk -> decision in one run
    chart_analyst/   four indices on four timeframes: alignment, divergence, fear
    options_strategist/  volatility regime, expected move, the strike to buy
    stock_picker/    F&O stocks: relative strength, today's move, futures OI buildup
    smart_money/     FII / DII flows, FII positioning, big deals, insiders
    risk_manager/    loss budget, trade limits, lots allowed, the kill switch
    performance_coach/  the journals reviewed: mistakes and advice

:data:`REGISTRY` maps the command-line name to the class.
"""

from typing import Dict, Type

from indtrader.models.agents.base import Agent
from indtrader.models.agents.chart_analyst import ChartAnalystAgent
from indtrader.models.agents.decision_maker import DecisionMakerAgent
from indtrader.models.agents.global_news import GlobalNewsAgent
from indtrader.models.agents.india_news import IndiaNewsAgent
from indtrader.models.agents.live_monitor import LiveMonitorAgent
from indtrader.models.agents.market_analyst import MarketAnalystAgent
from indtrader.models.agents.options_strategist import OptionsStrategistAgent
from indtrader.models.agents.performance_coach import PerformanceCoachAgent
from indtrader.models.agents.risk_manager import RiskManagerAgent
from indtrader.models.agents.smart_money import SmartMoneyAgent
from indtrader.models.agents.stock_picker import StockPickerAgent
from indtrader.models.agents.trading_desk import TradingDeskAgent

REGISTRY: Dict[str, Type[Agent]] = {cls.name: cls for cls in (
    IndiaNewsAgent, GlobalNewsAgent, SmartMoneyAgent,                                       # research
    MarketAnalystAgent, ChartAnalystAgent, OptionsStrategistAgent, StockPickerAgent,       # analysis
    LiveMonitorAgent, RiskManagerAgent, DecisionMakerAgent,                                 # live, risk, decision
    PerformanceCoachAgent, TradingDeskAgent)}                                               # review, the whole team

__all__ = ["Agent", "REGISTRY"]
