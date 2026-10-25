"""RiskManagerAgent: may the trader trade now, and how many lots."""

from indtrader.core import settings
from indtrader.core.errors import IndianTraderError
from indtrader.core.storage import read_json
from indtrader.models.agents.base import Agent
from indtrader.models.agents.risk_manager.status import RiskDesk
from indtrader.models.analytics.option_chain import OptionChainAnalyzer, OptionChainService, pick_strike


class RiskManagerAgent(Agent):
    name = "risk-manager"
    title = "Risk manager"
    symbol = "NIFTY"

    def collect(self) -> dict:
        ctx = self.ctx
        errors, option, vix, expiry_day = [], None, None, False
        try:
            chain = OptionChainService(ctx.market).fetch(self.symbol, ctx.now, "near")
            analysis = OptionChainAnalyzer(ctx.cfg).analyze(chain, ctx.now, ctx.market.lot_size(self.symbol))
            option = pick_strike(analysis, "CE", "atm")
            expiry_day = chain["expiry"] == ctx.now.date()
        except IndianTraderError as exc:
            errors.append("option chain: %s" % exc)
        try:
            vix = ctx.market.quote("INDIAVIX")["price"]
        except IndianTraderError as exc:
            errors.append("India VIX: %s" % exc)
        memory = read_json(settings.path("state", "decision-%s-%s.json" % (self.symbol, ctx.now.date().isoformat())), {}) or {}
        done = (memory.get("last") or {}).get("action") in ("DONE", "NO TRADE", "EXIT")
        result = RiskDesk(ctx).status(self.symbol, option, vix, expiry_day, done)
        result["errors"] = errors
        return result
