"""PerformanceCoachAgent: the trading record reviewed, with mistakes and advice."""

from indtrader.models.agents.base import Agent
from indtrader.models.agents.performance_coach.coach import PerformanceCoach


class PerformanceCoachAgent(Agent):
    name = "performance-coach"
    title = "Performance review"

    def collect(self) -> dict:
        return PerformanceCoach(self.ctx).review()
