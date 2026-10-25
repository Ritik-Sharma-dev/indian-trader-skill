"""GlobalNewsAgent: the data half of the US and global news report.

Collects the overnight snapshot and mood score, this week's economic
calendar and the themed headlines with their usual India impact, and writes
``global-news-data.md`` for the Claude agent ``global-market-news``.
"""

from indtrader.models.agents.base import Agent
from indtrader.models.agents.global_news.desk import GlobalDesk


class GlobalNewsAgent(Agent):
    name = "global-news"
    title = "US and global news for the Indian market (data)"

    def collect(self) -> dict:
        return GlobalDesk(self.ctx.market).collect(self.ctx.now, "all", hours=18)
