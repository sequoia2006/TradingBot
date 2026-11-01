"""Turns validated signals into broker orders by reconciling to a target position."""
from __future__ import annotations

import logging
import threading
from datetime import date
from typing import Optional

from .brokers import Broker
from .config import Settings
from .contracts import front_month
from .models import Signal
from .risk import Rejected, RiskManager

log = logging.getLogger(__name__)


class Executor:
    def __init__(self, s: Settings, broker: Broker, risk: Optional[RiskManager] = None):
        self.s, self.broker = s, broker
        self.risk = risk or RiskManager(s)
        self._lock = threading.Lock()  # one signal at a time
        self.history: list[dict] = []

    def contract(self) -> str:
        return self.s.contract or front_month("MNQ", date.today())

    def handle(self, sig: Signal) -> dict:
        with self._lock:
            result = self._handle(sig)
        self.history = (self.history + [{"signal": sig.model_dump(exclude={"secret"}), **result}])[-200:]
        log.info("signal %s %s -> %s", sig.action, sig.signal_id, result)
        return result

    def _handle(self, sig: Signal) -> dict:
        if sig.symbol.upper() not in self.s.allowed_symbols:
            return {"status": "rejected", "reason": f"symbol {sig.symbol} not allowed"}
        if self.risk.is_duplicate(sig):
            return {"status": "ignored", "reason": "duplicate signal_id"}

        contract = self.contract()
        current = self.broker.position(contract)
        target = sig.target_position

        if target == 0:
            if current == 0:
                self.broker.flatten(contract)  # still clears any orphaned bracket orders
                return {"status": "noop", "reason": "already flat", "contract": contract}
            self.broker.flatten(contract, sig.price)
            return {"status": "filled", "action": "flatten", "from": current, "contract": contract}

        if current != 0 and (current > 0) == (target > 0):
            return {"status": "noop", "reason": f"already {sig.action} {current}", "contract": contract}

        try:
            self.risk.check_entry(sig, self.broker.daily_pnl())
        except Rejected as e:
            # A reversal that fails the entry gate still closes the old position.
            if current != 0:
                self.broker.flatten(contract, sig.price)
                return {"status": "partial", "action": "flatten", "reason": str(e), "contract": contract}
            return {"status": "rejected", "reason": str(e), "contract": contract}

        if current != 0:
            self.broker.flatten(contract, sig.price)
        resp = self.broker.enter(contract, target, sig.stop, sig.target, sig.price)
        self.risk.record_entry()
        return {"status": "filled", "action": sig.action, "qty": target, "from": current,
                "contract": contract, "broker": resp}
