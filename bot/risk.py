"""Risk gate. Entries can be blocked; exits (flat) are never blocked."""
from __future__ import annotations

import time
from collections import OrderedDict
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import Settings
from .models import Signal

NY = ZoneInfo("America/New_York")


class Rejected(Exception):
    pass


class RiskManager:
    def __init__(self, s: Settings, clock=None):
        self.s = s
        self.clock = clock or (lambda: datetime.now(NY))
        self.killed = False
        self.kill_reason = ""
        self._day = None
        self.entries_today = 0
        self._seen: OrderedDict[str, float] = OrderedDict()

    def _roll_day(self, now: datetime) -> None:
        if now.date() != self._day:
            self._day = now.date()
            self.entries_today = 0

    def is_duplicate(self, sig: Signal) -> bool:
        if not sig.signal_id:
            return False
        if sig.signal_id in self._seen:
            return True
        self._seen[sig.signal_id] = time.time()
        while len(self._seen) > 1000:
            self._seen.popitem(last=False)
        return False

    def check_entry(self, sig: Signal, daily_pnl: float, now: datetime | None = None) -> None:
        now = now or self.clock()
        self._roll_day(now)
        if self.killed:
            raise Rejected(f"kill switch engaged: {self.kill_reason}")
        if sig.qty > self.s.max_contracts:
            raise Rejected(f"qty {sig.qty} > MAX_CONTRACTS {self.s.max_contracts}")
        start, end = self.s.entry_window
        if not (start <= now.timetz().replace(tzinfo=None) <= end) or now.weekday() >= 5:
            raise Rejected(f"outside entry window {start}-{end} NY")
        if self.entries_today >= self.s.max_trades_per_day:
            raise Rejected(f"max trades/day ({self.s.max_trades_per_day}) reached")
        if daily_pnl <= -abs(self.s.daily_loss_limit):
            self.kill(f"daily loss limit hit (P&L {daily_pnl:.2f})")
            raise Rejected(self.kill_reason)
        if sig.sent_at is not None and self.s.max_signal_age_sec > 0:
            age = now.timestamp() - sig.sent_at / 1000
            if age > self.s.max_signal_age_sec:
                raise Rejected(f"stale signal ({age:.0f}s old)")
        if sig.stop is not None and sig.price is not None:
            wrong_side = sig.stop >= sig.price if sig.action == "long" else sig.stop <= sig.price
            if wrong_side:
                raise Rejected("stop is on the wrong side of price")

    def record_entry(self) -> None:
        self.entries_today += 1

    def kill(self, reason: str) -> None:
        self.killed, self.kill_reason = True, reason

    def resume(self) -> None:
        self.killed, self.kill_reason = False, ""
