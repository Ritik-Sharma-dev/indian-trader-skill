"""A Model Context Protocol server exposing Indian Trader's analysis tools.

Standard library only: JSON-RPC 2.0 messages, one per line, over stdio.
Registered for Claude Code in the project's ``.mcp.json``; started with
``python "Indian Trader Skill/it.py" mcp``. Every tool is read-only
analysis; nothing here can place an order.
"""
