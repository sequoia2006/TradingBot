"""Tradovate REST broker (https://api.tradovate.com).

Requires API access on your Tradovate account (API add-on) and an API key
(cid/sec) generated in Tradovate's settings. Always validate on TRADOVATE_ENV=demo first.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from ..config import Settings
from .base import Broker, BrokerError

log = logging.getLogger(__name__)

URLS = {
    "demo": "https://demo.tradovateapi.com/v1",
    "live": "https://live.tradovateapi.com/v1",
}
WORKING = {"Working", "PendingNew", "Suspended", "PendingReplace"}


class TradovateBroker(Broker):
    def __init__(self, s: Settings, client: Optional[httpx.Client] = None):
        if s.tv_env not in URLS:
            raise ValueError("TRADOVATE_ENV must be demo or live")
        self.s = s
        self.http = client or httpx.Client(base_url=URLS[s.tv_env], timeout=10.0)
        self._token: Optional[str] = None
        self._expires = 0.0
        self._lock = threading.Lock()
        self._account: Optional[dict] = None
        self._contract_ids: dict[str, int] = {}

    # ── auth ──────────────────────────────────────────────────────────────
    def _auth(self) -> str:
        with self._lock:
            if self._token and time.time() < self._expires - 600:
                return self._token
            body = {
                "name": self.s.tv_username, "password": self.s.tv_password,
                "appId": self.s.tv_app_id, "appVersion": self.s.tv_app_version,
                "cid": self.s.tv_cid, "sec": self.s.tv_sec, "deviceId": self.s.tv_device_id,
            }
            r = self.http.post("/auth/accesstokenrequest", json=body)
            data = r.json()
            if "p-ticket" in data:
                raise BrokerError(f"Tradovate rate-limited auth; retry in {data.get('p-time')}s")
            if r.status_code != 200 or "accessToken" not in data:
                raise BrokerError(f"Tradovate auth failed: {data.get('errorText', data)}")
            self._token = data["accessToken"]
            exp = data.get("expirationTime")
            self._expires = (
                datetime.fromisoformat(exp.replace("Z", "+00:00")).timestamp()
                if exp else time.time() + 75 * 60
            )
            log.info("Tradovate authenticated (%s)", self.s.tv_env)
            return self._token

    def _req(self, method: str, path: str, **kw):
        headers = {"Authorization": f"Bearer {self._auth()}"}
        r = self.http.request(method, path, headers=headers, **kw)
        if r.status_code >= 400:
            raise BrokerError(f"{method} {path} -> {r.status_code}: {r.text[:300]}")
        data = r.json() if r.content else None
        if isinstance(data, dict) and data.get("failureReason"):
            raise BrokerError(f"{path} rejected: {data.get('failureReason')} {data.get('failureText', '')}")
        return data

    # ── lookups ───────────────────────────────────────────────────────────
    def account(self) -> dict:
        if self._account is None:
            accts = self._req("GET", "/account/list")
            if not accts:
                raise BrokerError("No Tradovate accounts found")
            if self.s.tv_account_id:
                accts = [a for a in accts if str(a["id"]) == self.s.tv_account_id]
                if not accts:
                    raise BrokerError(f"Account {self.s.tv_account_id} not found")
            self._account = accts[0]
        return self._account

    def contract_id(self, contract: str) -> int:
        if contract not in self._contract_ids:
            c = self._req("GET", "/contract/find", params={"name": contract})
            if not c or "id" not in c:
                raise BrokerError(f"Contract {contract} not found")
            self._contract_ids[contract] = c["id"]
        return self._contract_ids[contract]

    # ── Broker interface ─────────────────────────────────────────────────
    def position(self, contract: str) -> int:
        cid, aid = self.contract_id(contract), self.account()["id"]
        return sum(p.get("netPos", 0) for p in self._req("GET", "/position/list")
                   if p.get("contractId") == cid and p.get("accountId") == aid)

    def _cancel_working(self, contract: str) -> None:
        cid, aid = self.contract_id(contract), self.account()["id"]
        for o in self._req("GET", "/order/list"):
            if o.get("contractId") == cid and o.get("accountId") == aid and o.get("ordStatus") in WORKING:
                self._req("POST", "/order/cancelorder", json={"orderId": o["id"]})
                log.info("Cancelled working order %s", o["id"])

    def flatten(self, contract: str, price: Optional[float] = None) -> None:
        if self.position(contract) != 0:
            self._req("POST", "/order/liquidateposition", json={
                "accountId": self.account()["id"], "contractId": self.contract_id(contract), "admin": False,
            })
            for _ in range(20):  # wait up to ~5s for the fill
                if self.position(contract) == 0:
                    break
                time.sleep(0.25)
            else:
                raise BrokerError(f"{contract} still not flat after liquidate")
        self._cancel_working(contract)

    def enter(self, contract, qty, stop, target, price=None) -> dict:
        acct = self.account()
        side, exit_side = ("Buy", "Sell") if qty > 0 else ("Sell", "Buy")
        order = {
            "accountSpec": acct["name"], "accountId": acct["id"],
            "action": side, "symbol": contract, "orderQty": abs(qty),
            "orderType": "Market", "isAutomated": True,
        }
        brackets = []
        if stop is not None:
            brackets.append({"action": exit_side, "orderType": "Stop", "stopPrice": stop})
        if target is not None:
            brackets.append({"action": exit_side, "orderType": "Limit", "price": target})
        if brackets:
            order["bracket1"] = brackets[0]
            if len(brackets) > 1:
                order["bracket2"] = brackets[1]  # bracket1/bracket2 are OCO-linked
            return self._req("POST", "/order/placeOSO", json=order)
        return self._req("POST", "/order/placeorder", json=order)

    def daily_pnl(self) -> float:
        snap = self._req("POST", "/cashBalance/getCashBalanceSnapshot",
                         json={"accountId": self.account()["id"]})
        return float(snap.get("realizedPnL", 0.0)) + float(snap.get("openPnL", 0.0))
