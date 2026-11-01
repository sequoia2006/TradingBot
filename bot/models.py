from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class Signal(BaseModel):
    """Payload sent by the Pine strategy. `action` is the desired position."""

    secret: str
    action: Literal["long", "short", "flat"]
    symbol: str = "MNQ"
    qty: int = Field(1, ge=1)
    price: Optional[float] = None
    stop: Optional[float] = None
    target: Optional[float] = None
    signal_id: Optional[str] = None
    sent_at: Optional[int] = None  # epoch milliseconds

    @property
    def target_position(self) -> int:
        return {"long": self.qty, "short": -self.qty, "flat": 0}[self.action]


class ManualOrder(BaseModel):
    """Order placed by a person/agent (MCP) rather than a TradingView alert."""

    action: Literal["long", "short", "flat"]
    qty: int = Field(1, ge=1)
    stop: Optional[float] = None
    target: Optional[float] = None
    price: Optional[float] = Field(None, description="Reference price (paper broker fills here)")
