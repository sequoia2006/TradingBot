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

    def entry_block_reason(self, sig: Signal, daily_pnl: float,
                           now: datetime | None = None) -> str | None:
        """Why an entry would be rejected, or None. Has no side effects."""
        now = now or self.clock()
        entries = 0 if now.date() != self._day else self.entries_today
        if self.killed:
            return f"kill switch engaged: {self.kill_reason}"
        if sig.qty > self.s.max_contracts:
            return f"qty {sig.qty} > MAX_CONTRACTS {self.s.max_contracts}"
        start, end = self.s.entry_window
        if not (start <= now.timetz().replace(tzinfo=None) <= end) or now.weekday() >= 5:
            return f"outside entry window {start}-{end} NY"
        if entries >= self.s.max_trades_per_day:
            return f"max trades/day ({self.s.max_trades_per_day}) reached"
        if daily_pnl <= -abs(self.s.daily_loss_limit):
            return f"daily loss limit hit (P&L {daily_pnl:.2f})"
        if sig.sent_at is not None and self.s.max_signal_age_sec > 0:
            age = now.timestamp() - sig.sent_at / 1000
            if age > self.s.max_signal_age_sec:
                return f"stale signal ({age:.0f}s old)"
        if sig.stop is not None and sig.price is not None:
            wrong_side = sig.stop >= sig.price if sig.action == "long" else sig.stop <= sig.price
            if wrong_side:
                return "stop is on the wrong side of price"
        if sig.stop is not None and sig.target is not None:
            wrong = sig.target <= sig.stop if sig.action == "long" else sig.target >= sig.stop
            if wrong:
                return "target is on the wrong side of stop"
        return None

    def check_entry(self, sig: Signal, daily_pnl: float, now: datetime | None = None) -> None:
        now = now or self.clock()
        self._roll_day(now)
        reason = self.entry_block_reason(sig, daily_pnl, now)
        if reason:
            if reason.startswith("daily loss limit"):
                self.kill(reason)
            raise Rejected(reason)

    def record_entry(self) -> None:
        self.entries_today += 1

    def kill(self, reason: str) -> None:
        self.killed, self.kill_reason = True, reason

    def resume(self) -> None:
        self.killed, self.kill_reason = False, ""
