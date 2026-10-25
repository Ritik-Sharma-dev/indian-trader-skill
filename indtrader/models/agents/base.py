"""The base class every agent derives from.

An agent is a model: :meth:`Agent.collect` gathers its findings from the
data layer and returns them as plain data, with no output and no files.
Rendering is done by :mod:`indtrader.views.reports` and saving by
:mod:`indtrader.controllers.agents`. The Claude agents of the same name
(``.claude/agents/*.md``) start from the saved report and add web research.
"""

import abc
import logging

from indtrader.core.context import AppContext


class Agent(abc.ABC):
    #: command-line name, e.g. "india-news"
    name: str = ""
    #: report heading
    title: str = ""

    def __init__(self, ctx: AppContext) -> None:
        if not self.name:
            raise TypeError("%s must set a name" % type(self).__name__)
        self.ctx = ctx
        self.log = logging.getLogger("indtrader.agents.%s" % self.name)

    @abc.abstractmethod
    def collect(self) -> dict:
        """Gather the findings: plain data, with an ``errors`` list for the sources that failed."""
