"""MCP client -> MCP server -> FastAPI bot (paper broker), all in-process."""
import json

import anyio
import httpx
from mcp.client import Client

from bot.app import create_app
from bot.brokers import PaperBroker
from mcp_server.server import build_server


def run(settings, executor, scenario):
    app = create_app(settings, PaperBroker(commission_per_side=0))
    app.state.executor.risk = executor.risk  # frozen Tuesday-10:30 clock

    async def main():
        http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bot")
        server = build_server("http://bot", "admin-tok", http)
        async with Client(server) as c:
            async def call(name, **args):
                res = await c.call_tool(name, args)
                text = res.content[0].text
                return res.is_error, (text if res.is_error else json.loads(text))
            await scenario(c, call, app)

    anyio.run(main)


def test_tools_listed_with_annotations(settings, executor):
    async def scenario(c, call, app):
        tools = {t.name: t for t in (await c.list_tools()).tools}
        assert set(tools) == {"get_status", "preview_order", "place_order", "close_position",
                              "kill_switch", "resume_trading"}
        assert tools["get_status"].annotations.read_only_hint
        assert tools["preview_order"].annotations.read_only_hint
        assert tools["place_order"].annotations.destructive_hint
    run(settings, executor, scenario)


def test_preview_places_nothing_then_order_and_close(settings, executor):
    async def scenario(c, call, app):
        err, p = await call("preview_order", action="long", qty=1, stop=19980, target=20040, price=20000)
        assert not err and p["dry_run"] and "market buy 1 MNQZ6" in p["would"]
        _, st = await call("get_status")
        assert st["position"] == 0 and st["entries_today"] == 0

        _, r = await call("place_order", action="long", qty=1, stop=19980, target=20040, price=20000)
        assert r["status"] == "filled"
        _, st = await call("get_status")
        assert st["position"] == 1

        _, r = await call("close_position", price=20010)
        assert r["status"] == "filled"
        _, st = await call("get_status")
        assert st["position"] == 0 and st["daily_pnl"] == 20.0
    run(settings, executor, scenario)


def test_risk_rules_apply_to_mcp_orders(settings, executor):
    async def scenario(c, call, app):
        _, p = await call("preview_order", action="long", qty=5, price=20000)
        assert "MAX_CONTRACTS" in p["entry_blocked"]
        _, r = await call("place_order", action="long", qty=5, price=20000)
        assert r["status"] == "rejected"
        _, r = await call("place_order", action="long", stop=20010, price=20000)
        assert r["status"] == "rejected" and "wrong side" in r["reason"]
    run(settings, executor, scenario)


def test_kill_switch_and_resume(settings, executor):
    async def scenario(c, call, app):
        await call("place_order", action="short", price=20000)
        _, k = await call("kill_switch")
        assert k["killed"]
        _, st = await call("get_status")
        assert st["position"] == 0 and st["killed"]
        _, p = await call("preview_order", action="long", price=20000)
        assert "kill switch" in p["entry_blocked"]
        await call("resume_trading")
        _, r = await call("place_order", action="long", price=20000)
        assert r["status"] == "filled"
    run(settings, executor, scenario)


def test_bad_token_is_a_tool_error(settings, executor):
    app = create_app(settings, PaperBroker())

    async def main():
        http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bot")
        async with Client(build_server("http://bot", "wrong", http)) as c:
            res = await c.call_tool("get_status", {})
            assert res.is_error and "401" in res.content[0].text
    anyio.run(main)
