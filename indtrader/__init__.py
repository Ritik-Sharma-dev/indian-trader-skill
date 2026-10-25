"""Indian Trader: analysis tools for intraday trading on NSE / BSE.

Standard library only. Reads free public data (NSE and BSE website APIs,
Yahoo Finance, news RSS feeds) and never places an order.

Package layout (model-view-controller)::

    core/         infrastructure: settings, logging, errors, the NSE clock,
                  HTTP with offline replay, storage, AppContext
    models/       data and logic, no presentation
      data/       market data clients (Yahoo, NSE, BSE) behind MarketData
      analytics/  indicators, Black-Scholes, option chains, charts, history,
                  flows, news, insider filings, shareholding patterns
      trading/    scanner, entry timer, planner, Time Machine, sizing, risk,
                  paper journal, alerts, screener, tax
      agents/     the agent team, one package per agent
    views/        terminal, Markdown and HTML rendering
    controllers/  command handlers: ask the models, print the views
    cli/          the command line: argument parsing and dispatch
    mcp/          the Model Context Protocol server (JSON-RPC over stdio)
"""

import logging

__version__ = "0.3.0"

# Library code logs through "indtrader.*"; the application (CLI or MCP
# server) decides where the records go. Without this, Python's last-resort
# handler would print warnings to stderr in library use.
logging.getLogger(__name__).addHandler(logging.NullHandler())
