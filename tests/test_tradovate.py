"""Tradovate broker against a mocked HTTP transport (no network)."""
import json

import httpx

from bot.brokers.tradovate import URLS, TradovateBroker


def make(settings):
    calls = []
    state = {"netPos": 0}

    def handler(req: httpx.Request):
        path = req.url.path.removeprefix("/v1")
        body = json.loads(req.content) if req.content else None
        calls.append((req.method, path, body))
        if path == "/auth/accesstokenrequest":
            return httpx.Response(200, json={"accessToken": "tok", "expirationTime": "2099-01-01T00:00:00Z"})
        assert req.headers["authorization"] == "Bearer tok"
        if path == "/account/list":
            return httpx.Response(200, json=[{"id": 7, "name": "DEMO123"}])
        if path == "/contract/find":
            return httpx.Response(200, json={"id": 99, "name": "MNQZ6"})
        if path == "/position/list":
            return httpx.Response(200, json=[{"accountId": 7, "contractId": 99, "netPos": state["netPos"]}])
        if path == "/order/placeOSO":
            state["netPos"] = body["orderQty"] * (1 if body["action"] == "Buy" else -1)
            return httpx.Response(200, json={"orderId": 1, "oso1Id": 2, "oso2Id": 3})
        if path == "/order/liquidateposition":
            state["netPos"] = 0
            return httpx.Response(200, json={"orderId": 4})
        if path == "/order/list":
            return httpx.Response(200, json=[{"id": 2, "accountId": 7, "contractId": 99, "ordStatus": "Working"}])
        if path == "/order/cancelorder":
            return httpx.Response(200, json={"orderId": body["orderId"]})
        if path == "/cashBalance/getCashBalanceSnapshot":
            return httpx.Response(200, json={"realizedPnL": -10.0, "openPnL": 4.0})
        return httpx.Response(404)

    client = httpx.Client(base_url=URLS["demo"], transport=httpx.MockTransport(handler))
    return TradovateBroker(settings, client), calls


def test_enter_with_bracket_and_flatten(settings):
    b, calls = make(settings)
    b.enter("MNQZ6", -1, stop=20030.0, target=19950.0)
    oso = next(c[2] for c in calls if c[1] == "/order/placeOSO")
    assert oso["action"] == "Sell" and oso["symbol"] == "MNQZ6" and oso["accountId"] == 7
    assert oso["bracket1"] == {"action": "Buy", "orderType": "Stop", "stopPrice": 20030.0}
    assert oso["bracket2"] == {"action": "Buy", "orderType": "Limit", "price": 19950.0}
    assert b.position("MNQZ6") == -1
    b.flatten("MNQZ6")
    assert b.position("MNQZ6") == 0
    assert ("POST", "/order/cancelorder", {"orderId": 2}) in calls
    assert b.daily_pnl() == -6.0
    assert sum(1 for c in calls if c[1] == "/auth/accesstokenrequest") == 1
