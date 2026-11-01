"""FastAPI webhook server. Run: uvicorn bot.app:app --host 0.0.0.0 --port 8000"""
from __future__ import annotations

import hmac
import json
import logging
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import ValidationError

from .brokers import Broker, BrokerError, PaperBroker
from .config import Settings
from .executor import Executor
from .models import Signal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bot")


def make_broker(s: Settings) -> Broker:
    if s.broker == "paper":
        return PaperBroker()
    if s.broker == "tradovate":
        from .brokers.tradovate import TradovateBroker
        return TradovateBroker(s)
    raise RuntimeError(f"Unknown BROKER={s.broker}")


def create_app(settings: Optional[Settings] = None, broker: Optional[Broker] = None) -> FastAPI:
    s = settings or Settings.from_env()
    ex = Executor(s, broker or make_broker(s))
    app = FastAPI(title="MNQ TradingView Bot")
    app.state.executor = ex

    def require_admin(token: Optional[str]) -> None:
        if not s.admin_token or not token or not hmac.compare_digest(token, s.admin_token):
            raise HTTPException(401, "bad admin token")

    @app.get("/health")
    def health():
        return {"ok": True, "broker": s.broker, "contract": ex.contract(), "killed": ex.risk.killed}

    @app.post("/webhook")
    async def webhook(request: Request):
        client_ip = request.client.host if request.client else ""
        if s.allowed_ips and client_ip not in s.allowed_ips:
            log.warning("blocked webhook from %s", client_ip)
            raise HTTPException(403, "ip not allowed")
        raw = await request.body()
        try:
            sig = Signal.model_validate(json.loads(raw))
        except (json.JSONDecodeError, ValidationError) as e:
            log.warning("bad payload: %s", raw[:300])
            raise HTTPException(400, f"invalid payload: {e}")
        if not hmac.compare_digest(sig.secret, s.webhook_secret):
            raise HTTPException(401, "bad secret")
        try:
            return ex.handle(sig)
        except BrokerError as e:
            log.exception("broker error")
            raise HTTPException(502, str(e))

    @app.get("/status")
    def status(x_admin_token: Optional[str] = Header(None)):
        require_admin(x_admin_token)
        c = ex.contract()
        return {
            "contract": c, "position": ex.broker.position(c), "daily_pnl": ex.broker.daily_pnl(),
            "entries_today": ex.risk.entries_today, "killed": ex.risk.killed,
            "kill_reason": ex.risk.kill_reason, "recent": ex.history[-20:],
        }

    @app.post("/kill")
    def kill(flatten: bool = True, x_admin_token: Optional[str] = Header(None)):
        """Block new entries and (by default) flatten immediately."""
        require_admin(x_admin_token)
        ex.risk.kill("manual kill switch")
        if flatten:
            ex.broker.flatten(ex.contract())
        return {"killed": True, "flattened": flatten}

    @app.post("/resume")
    def resume(x_admin_token: Optional[str] = Header(None)):
        require_admin(x_admin_token)
        ex.risk.resume()
        return {"killed": False}

    return app


app = None
try:
    app = create_app()
except RuntimeError as e:  # allows importing the module in tests without env vars
    log.warning("app not created at import: %s", e)
