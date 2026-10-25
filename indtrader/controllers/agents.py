"""Running an agent: collect its findings, render the report, save it.

The agents are models and the reports are views; this module joins them.
The trading desk returns every stage's findings, so running it also saves
each stage's own report next to the desk report.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional, Union

from indtrader.core import settings
from indtrader.core.context import AppContext
from indtrader.core.errors import ValidationError
from indtrader.models.agents import REGISTRY
from indtrader.models.agents.base import Agent
from indtrader.views.reports import REPORTS

log = logging.getLogger(__name__)


@dataclass
class AgentReport:
    agent: str
    findings: dict
    markdown: str
    path: Optional[str] = None
    seconds: float = 0.0
    errors: List[str] = field(default_factory=list)


def report_path(ctx: AppContext, name: str) -> str:
    return settings.path("research", ctx.now.date().isoformat(), "%s-data.md" % name)


def render(agent: Agent, findings: dict) -> str:
    return REPORTS[agent.name](agent.title, agent.ctx.now, findings)


def _save(ctx: AppContext, name: str, markdown: str) -> str:
    path = report_path(ctx, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(markdown)
    return path


def run_agent(ctx: AppContext, agent: Union[str, Agent], write: bool = True) -> AgentReport:
    """Run one agent (by name or instance) and return its report; ``write`` saves the Markdown."""
    if isinstance(agent, str):
        if agent not in REGISTRY:
            raise ValidationError("unknown agent %r (%s)" % (agent, ", ".join(sorted(REGISTRY))))
        agent = REGISTRY[agent](ctx)
    started = time.time()
    log.info("%s: collecting", agent.name)
    findings = agent.collect()
    markdown = render(agent, findings)
    path = _save(ctx, agent.name, markdown) if write else None
    if write and agent.name == "trading-desk":
        for name, stage_findings in findings.get("reports", {}).items():
            stage = REGISTRY[name](ctx)
            _save(ctx, name, render(stage, stage_findings))
    report = AgentReport(agent.name, findings, markdown, path, round(time.time() - started, 2), list(findings.get("errors", [])))
    log.info("%s: done in %.1fs with %d data note(s)%s", agent.name, report.seconds, len(report.errors), (", wrote " + path) if path else "")
    return report
