"""Logging setup for the applications (CLI and MCP server).

Library modules only call ``logging.getLogger(__name__)``. This module
attaches the handlers once per process:

* a rotating file, ``workspace/logs/indtrader.log`` (1 MB x 5), at the
  configured level (``INFO`` by default, ``INDTRADER_LOG_LEVEL`` overrides);
* stderr at ``WARNING`` and above (``ERROR`` for the CLI, which prints its own
  one-line message), so command output on stdout stays clean and the MCP
  server's stdout carries nothing but protocol messages.
"""

import logging
import logging.handlers
import os
from typing import Optional

from indtrader.core import settings

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
CONSOLE_FORMAT = "%(levelname)s %(name)s: %(message)s"
_configured = False


def configure(level: Optional[str] = None, console_level: str = "WARNING", log_file: bool = True) -> None:
    """Attach handlers to the ``indtrader`` logger (idempotent)."""
    global _configured
    if _configured:
        return
    level_name = (level or os.environ.get("INDTRADER_LOG_LEVEL") or "INFO").upper()
    root = logging.getLogger("indtrader")
    root.setLevel(getattr(logging, level_name, logging.INFO))
    root.propagate = False

    console = logging.StreamHandler()
    console.setLevel(getattr(logging, console_level.upper(), logging.WARNING))
    console.setFormatter(logging.Formatter(CONSOLE_FORMAT))
    root.addHandler(console)

    if log_file and os.environ.get("INDTRADER_LOG_FILE", "1") != "0":
        path = settings.path("logs", "indtrader.log")
        handler = logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        root.addHandler(handler)
    _configured = True


def reset() -> None:
    """Remove the handlers (tests use this between runs)."""
    global _configured
    root = logging.getLogger("indtrader")
    for handler in list(root.handlers):
        if not isinstance(handler, logging.NullHandler):
            root.removeHandler(handler)
            handler.close()
    _configured = False
