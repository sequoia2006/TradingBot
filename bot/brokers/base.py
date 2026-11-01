from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class BrokerError(RuntimeError):
    pass


class Broker(ABC):
    """Minimal interface the executor needs. Quantities are signed (+long / -short)."""

    @abstractmethod
    def position(self, contract: str) -> int: ...

    @abstractmethod
    def flatten(self, contract: str, price: Optional[float] = None) -> None:
        """Close the position and cancel any working orders on the contract."""

    @abstractmethod
    def enter(self, contract: str, qty: int, stop: Optional[float],
              target: Optional[float], price: Optional[float] = None) -> dict:
        """Market order of signed `qty`, with a broker-side OCO stop/target bracket."""

    @abstractmethod
    def daily_pnl(self) -> float:
        """Today's realized + open P&L in USD."""
