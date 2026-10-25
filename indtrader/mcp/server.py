"""The MCP server: JSON-RPC 2.0 over stdio, one message per line.

Implements the lifecycle (``initialize``, ``notifications/initialized``,
``ping``) and the tools capability (``tools/list``, ``tools/call``). A tool
that fails returns ``isError: true`` with the reason, so the model can read
it; protocol problems return JSON-RPC errors.

stdout carries protocol messages only; logs go to stderr and the log file.
"""

import json
import logging
import re
import sys
from typing import Any, Dict, IO, List, Optional

from indtrader.core.context import AppContext
from indtrader.core.errors import IndianTraderError
from indtrader.core.formatting import to_json
from indtrader.mcp.tools import BY_NAME, TOOLS
from indtrader import __version__

log = logging.getLogger(__name__)

SUPPORTED_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = -32700, -32600, -32601, -32602, -32603

INSTRUCTIONS = ("Indian Trader: analysis tools for NSE/BSE intraday trading (Nifty, Bank Nifty, Sensex, F&O stocks) and "
                "investor research (insider trades, shareholding patterns, stock screens, tax arithmetic). "
                "All times are IST. Data is free and unofficial (NSE, BSE, Yahoo, RSS); every tool is read-only and "
                "nothing can place an order. Treat outputs as analysis, not advice.")

_JSON_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict}


class ArgumentError(ValueError):
    """Tool arguments do not match the tool's input schema."""


def validate_arguments(schema: Dict[str, Any], arguments: Any) -> Dict[str, Any]:
    """Check ``arguments`` against the small JSON Schema subset the tools use."""
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise ArgumentError("arguments must be an object")
    properties = schema.get("properties", {})
    for name in schema.get("required", []):
        if name not in arguments:
            raise ArgumentError("missing required argument %r" % name)
    if schema.get("additionalProperties") is False:
        unknown = sorted(set(arguments) - set(properties))
        if unknown:
            raise ArgumentError("unknown argument(s): %s" % ", ".join(unknown))
    for name, value in arguments.items():
        _check_value(name, value, properties.get(name, {}))
    return arguments


def _check_value(name: str, value: Any, rule: Dict[str, Any]) -> None:
    expected = rule.get("type")
    if expected:
        python_type = _JSON_TYPES[expected]
        if isinstance(value, bool) and expected in ("integer", "number"):
            raise ArgumentError("%s must be %s" % (name, expected))
        if not isinstance(value, python_type):
            raise ArgumentError("%s must be %s" % (name, expected))
    if "enum" in rule and value not in rule["enum"]:
        raise ArgumentError("%s must be one of %s" % (name, ", ".join(map(str, rule["enum"]))))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in rule and value < rule["minimum"]:
            raise ArgumentError("%s must be >= %s" % (name, rule["minimum"]))
        if "maximum" in rule and value > rule["maximum"]:
            raise ArgumentError("%s must be <= %s" % (name, rule["maximum"]))
        if "exclusiveMinimum" in rule and value <= rule["exclusiveMinimum"]:
            raise ArgumentError("%s must be > %s" % (name, rule["exclusiveMinimum"]))
    if isinstance(value, str):
        if "minLength" in rule and len(value) < rule["minLength"]:
            raise ArgumentError("%s needs at least %d character(s)" % (name, rule["minLength"]))
        if "pattern" in rule and not re.search(rule["pattern"], value):
            raise ArgumentError("%s must match %s" % (name, rule["pattern"]))
    if isinstance(value, list):
        if "minItems" in rule and len(value) < rule["minItems"]:
            raise ArgumentError("%s needs at least %d item(s)" % (name, rule["minItems"]))
        if "maxItems" in rule and len(value) > rule["maxItems"]:
            raise ArgumentError("%s takes at most %d item(s)" % (name, rule["maxItems"]))
        for item in value:
            _check_value(name + "[]", item, rule.get("items", {}))


class McpServer:
    def __init__(self, offline: Optional[str] = None, now: Optional[str] = None) -> None:
        self.offline = offline
        self.now = now
        self.initialized = False

    # -- dispatch -------------------------------------------------------------------

    def handle(self, message: Any) -> Optional[Dict[str, Any]]:
        """One incoming message -> the response, or None for notifications."""
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
            return self._error(message.get("id") if isinstance(message, dict) else None, INVALID_REQUEST, "invalid JSON-RPC request")
        method, request_id, params = message["method"], message.get("id"), message.get("params") or {}
        is_notification = "id" not in message
        if method.startswith("notifications/"):
            if method == "notifications/initialized":
                self.initialized = True
                log.info("client initialised")
            return None
        handler = {"initialize": self._initialize, "ping": lambda p: {}, "tools/list": self._list_tools,
                   "tools/call": self._call_tool}.get(method)
        if handler is None:
            return None if is_notification else self._error(request_id, METHOD_NOT_FOUND, "method not found: %s" % method)
        try:
            result = handler(params)
        except ArgumentError as exc:
            return self._error(request_id, INVALID_PARAMS, str(exc))
        except Exception:                                    # a bug: keep serving
            log.exception("MCP %s failed", method)
            return self._error(request_id, INTERNAL_ERROR, "internal error (see the log)")
        return None if is_notification else {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _error(request_id: Any, code: int, text: str) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": text}}

    # -- methods ----------------------------------------------------------------------

    @staticmethod
    def _initialize(params: Dict[str, Any]) -> Dict[str, Any]:
        requested = params.get("protocolVersion")
        version = requested if requested in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]
        client = (params.get("clientInfo") or {}).get("name", "unknown")
        log.info("initialize from %s, protocol %s", client, version)
        return {"protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "indian-trader", "version": __version__}, "instructions": INSTRUCTIONS}

    @staticmethod
    def _list_tools(params: Dict[str, Any]) -> Dict[str, Any]:
        return {"tools": [tool.describe() for tool in TOOLS]}

    def _call_tool(self, params: Dict[str, Any]) -> Dict[str, Any]:
        name = params.get("name")
        tool = BY_NAME.get(name)
        if tool is None:
            raise ArgumentError("unknown tool %r" % name)
        arguments = validate_arguments(tool.schema, params.get("arguments"))
        log.info("tool %s %s", name, json.dumps(arguments, sort_keys=True))
        try:
            ctx = AppContext.create(now=self.now, offline=self.offline)
            data = tool.handler(ctx, arguments)
        except IndianTraderError as exc:
            log.warning("tool %s: %s", name, exc)
            return {"content": [{"type": "text", "text": "error: %s" % exc}], "isError": True}
        except Exception:
            log.exception("tool %s crashed", name)
            return {"content": [{"type": "text", "text": "internal error in %s (see the Indian Trader log)" % name}], "isError": True}
        return {"content": [{"type": "text", "text": to_json(data)}], "isError": False}

    # -- transport -------------------------------------------------------------------

    def serve(self, stdin: IO[str] = None, stdout: IO[str] = None) -> None:
        """Read messages from ``stdin`` until EOF; write responses to ``stdout``."""
        stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
        log.info("MCP server %s ready (%d tools)", __version__, len(TOOLS))
        for line in stdin:
            line = line.strip().lstrip("﻿")        # Windows pipes can prefix the first line with a byte-order mark
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError:
                self._write(stdout, self._error(None, PARSE_ERROR, "parse error"))
                continue
            replies: List[Dict[str, Any]] = []
            for item in (message if isinstance(message, list) else [message]):
                reply = self.handle(item)
                if reply is not None:
                    replies.append(reply)
            if replies:
                self._write(stdout, replies if isinstance(message, list) else replies[0])
        log.info("MCP server stopped (stdin closed)")

    @staticmethod
    def _write(stdout: IO[str], payload: Any) -> None:
        stdout.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        stdout.flush()
