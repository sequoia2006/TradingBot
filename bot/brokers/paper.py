"""In-memory simulated broker. Fills at the signal price; good for wiring tests."""
from __future__ import annotations

import logging
from typing import Optional

from .base import Broker

log = logging.getLogger(__name__)
POINT_VALUE = {"MNQ": 2.0, "NQ": 20.0, "MES": 5.0, "ES": 50.0}


class PaperBroker(Broker):
    def __init__(self, commission_per_side: float = 0.62):
        self.pos: dict[str, int] = {}
        self.avg: dict[str, float] = {}
        self.realized = 0.0
        self.commission = commission_per_side
        self.fills: list[dict] = []

    def _pv(self, contract: str) -> float:
        return POINT_VALUE.get(contract.rstrip("0123456789")[:-1], 2.0)

    def position(self, contract: str) -> int:
        return self.pos.get(contract, 0)

    def _fill(self, contract: str, qty: int, price: Optional[float]) -> None:
        cur = self.position(contract)
        px = price or self.avg.get(contract, 0.0)
        self.realized -= abs(qty) * self.commission
        if cur and price is not None and (cur > 0) != (qty > 0):
            closed = min(abs(cur), abs(qty))
            sign = 1 if cur > 0 else -1
            self.realized += (px - self.avg[contract]) * closed * sign * self._pv(contract)
        new = cur + qty
        if new == 0:
            self.avg.pop(contract, None)
        elif cur == 0 or (cur > 0) == (qty > 0):
            self.avg[contract] = (self.avg.get(contract, 0) * abs(cur) + px * abs(qty)) / abs(new)
        self.pos[contract] = new
        self.fills.append({"contract": contract, "qty": qty, "price": px})
        log.info("PAPER fill %s %+d @ %s -> pos %d, realized %.2f", contract, qty, px, new, self.realized)

    def flatten(self, contract: str, price: Optional[float] = None) -> None:
        cur = self.position(contract)
        if cur:
            self._fill(contract, -cur, price)

    def enter(self, contract, qty, stop, target, price=None) -> dict:
        self._fill(contract, qty, price)
        return {"paper": True, "qty": qty, "price": price, "stop": stop, "target": target}

    def daily_pnl(self) -> float:
        return self.realized
