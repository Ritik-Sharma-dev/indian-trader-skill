"""The MCP server: protocol lifecycle, tool listing, argument validation and calls."""

import io
import json
import unittest

from _base import SNAP, WorkspaceTest

from indtrader.mcp.server import INVALID_PARAMS, INVALID_REQUEST, METHOD_NOT_FOUND, PARSE_ERROR, McpServer, validate_arguments, ArgumentError
from indtrader.mcp.tools import TOOLS


def request(method, params=None, request_id=1):
    message = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    return message


class TestMcpProtocol(WorkspaceTest):
    def setUp(self):
        super().setUp()
        self.server = McpServer(offline=SNAP, now="2026-10-22 23:30")

    def test_initialize_and_lifecycle(self):
        reply = self.server.handle(request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                                          "clientInfo": {"name": "test", "version": "1"}}))
        result = reply["result"]
        self.assertEqual(result["protocolVersion"], "2025-06-18")
        self.assertIn("tools", result["capabilities"])
        self.assertEqual(result["serverInfo"]["name"], "indian-trader")
        old = self.server.handle(request("initialize", {"protocolVersion": "1999-01-01"}))["result"]
        self.assertEqual(old["protocolVersion"], "2025-06-18")             # unknown version: offer our latest
        self.assertIsNone(self.server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertTrue(self.server.initialized)
        self.assertEqual(self.server.handle(request("ping"))["result"], {})

    def test_errors(self):
        self.assertEqual(self.server.handle(request("does/not/exist"))["error"]["code"], METHOD_NOT_FOUND)
        self.assertEqual(self.server.handle({"id": 3, "method": "ping"})["error"]["code"], INVALID_REQUEST)
        reply = self.server.handle(request("tools/call", {"name": "no_such_tool"}))
        self.assertEqual(reply["error"]["code"], INVALID_PARAMS)
        reply = self.server.handle(request("tools/call", {"name": "quote", "arguments": {}}))
        self.assertEqual(reply["error"]["code"], INVALID_PARAMS)

    def test_tools_list(self):
        tools = self.server.handle(request("tools/list"))["result"]["tools"]
        self.assertEqual(len(tools), len(TOOLS))
        for tool in tools:
            self.assertTrue(tool["name"] and tool["description"])
            self.assertEqual(tool["inputSchema"]["type"], "object")
        self.assertIn("option_chain", {t["name"] for t in tools})

    def test_tool_calls(self):
        reply = self.server.handle(request("tools/call", {"name": "quote", "arguments": {"symbols": ["NIFTY", "SENSEX"]}}))
        result = reply["result"]
        self.assertFalse(result["isError"])
        data = json.loads(result["content"][0]["text"])
        self.assertAlmostEqual(data["NIFTY"]["price"], 22687.65)
        self.assertAlmostEqual(data["SENSEX"]["change"], -460.30, places=2)
        chain = json.loads(self.server.handle(request("tools/call", {"name": "option_chain", "arguments": {"symbol": "NIFTY"}}))
                           ["result"]["content"][0]["text"])
        self.assertEqual((chain["max_pain"], chain["lot"]), (22850, 65))
        failed = self.server.handle(request("tools/call", {"name": "option_chain", "arguments": {"symbol": "SENSEX"}}))["result"]
        self.assertTrue(failed["isError"])
        self.assertIn("BSE", failed["content"][0]["text"])

    def test_argument_validation(self):
        schema = next(t.schema for t in TOOLS if t.name == "charges")
        self.assertEqual(validate_arguments(schema, {"type": "option", "buy": 100, "sell": 110}),
                         {"type": "option", "buy": 100, "sell": 110})
        for bad in ({"type": "crypto", "buy": 1, "sell": 1}, {"type": "option", "buy": 0, "sell": 1},
                    {"type": "option", "buy": 1, "sell": 1, "extra": 1}, {"type": "option", "buy": True, "sell": 1}):
            with self.assertRaises(ArgumentError, msg=str(bad)):
                validate_arguments(schema, bad)

    def test_stdio_transport(self):
        lines = [json.dumps(request("initialize", {"protocolVersion": "2025-06-18"})),
                 json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                 "not json",
                 json.dumps(request("tools/call", {"name": "market_status", "arguments": {}}, request_id=2))]
        out = io.StringIO()
        self.server.serve(io.StringIO("\n".join(lines) + "\n"), out)
        replies = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual(len(replies), 3)                    # the notification gets no reply
        self.assertEqual(replies[1]["error"]["code"], PARSE_ERROR)
        status = json.loads(replies[2]["result"]["content"][0]["text"])
        self.assertEqual(status["state"], "closed")


if __name__ == "__main__":
    unittest.main()
