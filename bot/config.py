"""Configuration loaded from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import time


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).split(" #", 1)[0].strip()


def _parse_window(s: str) -> tuple[time, time]:
    start, end = s.split("-")
    h1, m1 = map(int, start.split(":"))
    h2, m2 = map(int, end.split(":"))
    return time(h1, m1), time(h2, m2)


@dataclass
class Settings:
    webhook_secret: str = ""
    admin_token: str = ""
    broker: str = "paper"
    contract: str = ""
    max_contracts: int = 2
    max_trades_per_day: int = 6
    daily_loss_limit: float = 300.0
    entry_window: tuple[time, time] = (time(9, 35), time(15, 45))
    max_signal_age_sec: int = 30
    allowed_ips: list[str] = field(default_factory=list)
    allowed_symbols: tuple[str, ...] = ("MNQ",)

    # Tradovate
    tv_env: str = "demo"
    tv_username: str = ""
    tv_password: str = ""
    tv_app_id: str = ""
    tv_app_version: str = "1.0"
    tv_cid: str = ""
    tv_sec: str = ""
    tv_device_id: str = ""
    tv_account_id: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        s = cls(
            webhook_secret=_env("WEBHOOK_SECRET"),
            admin_token=_env("ADMIN_TOKEN"),
            broker=_env("BROKER", "paper").lower(),
            contract=_env("CONTRACT").upper(),
            max_contracts=int(_env("MAX_CONTRACTS", "2")),
            max_trades_per_day=int(_env("MAX_TRADES_PER_DAY", "6")),
            daily_loss_limit=float(_env("DAILY_LOSS_LIMIT", "300")),
            entry_window=_parse_window(_env("ENTRY_WINDOW", "09:35-15:45")),
            max_signal_age_sec=int(_env("MAX_SIGNAL_AGE_SEC", "30")),
            allowed_ips=[ip.strip() for ip in _env("ALLOWED_IPS").split(",") if ip.strip()],
            tv_env=_env("TRADOVATE_ENV", "demo").lower(),
            tv_username=_env("TRADOVATE_USERNAME"),
            tv_password=_env("TRADOVATE_PASSWORD"),
            tv_app_id=_env("TRADOVATE_APP_ID"),
            tv_app_version=_env("TRADOVATE_APP_VERSION", "1.0"),
            tv_cid=_env("TRADOVATE_CID"),
            tv_sec=_env("TRADOVATE_SEC"),
            tv_device_id=_env("TRADOVATE_DEVICE_ID"),
            tv_account_id=_env("TRADOVATE_ACCOUNT_ID"),
        )
        if len(s.webhook_secret) < 12:
            raise RuntimeError("WEBHOOK_SECRET must be set (12+ chars)")
        return s
