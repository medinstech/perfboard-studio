"""``python -m perfboard_studio.mcp`` — run the MCP server over stdio."""

from __future__ import annotations

from perfboard_studio.mcp.server import main

if __name__ == "__main__":
    raise SystemExit(main())
