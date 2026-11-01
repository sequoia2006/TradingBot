"""MCP server that lets Claude check and place MNQ orders through the bot.

It never talks to the broker directly: every call goes to the bot's HTTP API
(/status, /order, /kill, /resume), so the bot's risk rules still apply.

Run (stdio):  BOT_URL=https://your-bot BOT_ADMIN_TOKEN=... python -m mcp_server.server
"""
from __future__ import annotations

import os
from typing import Any, Literal, Optional

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

INSTRUCTIONS = """\
Tools for trading MNQ (Micro E-mini Nasdaq-100 futures, $2 per index point) through
the user's trading bot. Rules:
1. Before any order, call get_status, then preview_order, and show the user the preview
   (current position, what will happen, stop/target, risk in $).
2. Only call place_order or close_position after the user explicitly approves that
   specific order in this conversation. Never place orders on your own initiative.
3. If anything looks wrong, or the user asks to stop, use kill_switch.
"""

READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=True)
TRADE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False,
                        open_world_hint=True)

Action = Literal["long", "short", "flat"]


def build_server(base_url: str, admin_token: str,
                 http: Optional[httpx.AsyncClient] = None) -> MCPServer:
    client = http or httpx.AsyncClient(base_url=base_url, timeout=20.0)
    headers = {"x-admin-token": admin_token}
    mcp = MCPServer("mnq-bot", instructions=INSTRUCTIONS)

    async def call(method: str, path: str, **kw) -> dict[str, Any]:
        try:
            r = await client.request(method, path, headers=headers, **kw)
        except httpx.HTTPError as e:
            raise ToolError(f"cannot reach bot at {base_url}: {e}") from e
        if r.status_code >= 400:
            raise ToolError(f"bot returned {r.status_code}: {r.text[:300]}")
        return r.json()

    def order_body(action, qty, stop, target, price) -> dict:
        return {"action": action, "qty": qty, "stop": stop, "target": target, "price": price}

    @mcp.tool(annotations=READ)
    async def get_status() -> dict[str, Any]:
        """Current MNQ contract, position (+long/-short contracts), today's P&L in USD,
        entries today, kill-switch state and the most recent signals/orders."""
        return await call("GET", "/status")

    @mcp.tool(annotations=READ)
    async def preview_order(action: Action, qty: int = 1, stop: Optional[float] = None,
                            target: Optional[float] = None,
                            price: Optional[float] = None) -> dict[str, Any]:
        """Dry run: show what place_order would do right now, including whether the risk
        rules would block it. Places nothing. `action` is the desired position: long,
        short or flat. `stop`/`target` are absolute prices for the broker-side bracket.
        `price` is a reference price (required in paper mode, used for sanity checks)."""
        return await call("POST", "/order", params={"dry_run": "true"},
                          json=order_body(action, qty, stop, target, price))

    @mcp.tool(annotations=TRADE)
    async def place_order(action: Action, qty: int = 1, stop: Optional[float] = None,
                          target: Optional[float] = None,
                          price: Optional[float] = None) -> dict[str, Any]:
        """PLACES A REAL ORDER (market, with optional OCO stop/target at the broker).
        Moves the account to the desired position: long or short `qty` contracts, or flat.
        Reversing closes the old position first. Only call after the user approved a
        preview_order of this exact order."""
        return await call("POST", "/order", json=order_body(action, qty, stop, target, price))

    @mcp.tool(annotations=TRADE)
    async def close_position(price: Optional[float] = None) -> dict[str, Any]:
        """Flatten the MNQ position at market and cancel its stop/target orders.
        `price` is only used by the paper broker."""
        return await call("POST", "/order", json=order_body("flat", 1, None, None, price))

    @mcp.tool(annotations=TRADE)
    async def kill_switch(flatten: bool = True) -> dict[str, Any]:
        """Emergency stop: block all new entries (TradingView alerts and manual orders)
        and, by default, flatten the position immediately."""
        return await call("POST", "/kill", params={"flatten": str(flatten).lower()})

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False))
    async def resume_trading() -> dict[str, Any]:
        """Clear the kill switch so new entries are allowed again. Ask the user first."""
        return await call("POST", "/resume")

    return mcp


def main() -> None:
    url = os.environ.get("BOT_URL", "http://localhost:8000")
    token = os.environ.get("BOT_ADMIN_TOKEN", "")
    if not token:
        raise SystemExit("BOT_ADMIN_TOKEN is required")
    build_server(url, token).run("stdio")


if __name__ == "__main__":
    main()
