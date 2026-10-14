"""Broker adapter surface: submit, cancel, track.

The session runner talks to this protocol, not to Alpaca directly. CI uses a
fixture double; the paper adapter is pinned to Alpaca's paper endpoint.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from .intent import OrderIntent


class BrokerError(RuntimeError):
    """Broker refused, was unreachable, or returned an unusable payload."""


class OrderStatus(StrEnum):
    NEW = "NEW"
    ACCEPTED = "ACCEPTED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class BrokerOrder:
    broker_order_id: str
    client_order_id: str
    status: OrderStatus
    symbol: str
    side: str
    quantity: int
    filled_quantity: int = 0
    filled_price: float | None = None

    def __post_init__(self) -> None:
        if not self.broker_order_id or not self.client_order_id:
            raise ValueError("broker and client order ids are required")
        if self.quantity < 1:
            raise ValueError("quantity must be positive")
        if self.filled_quantity < 0 or self.filled_quantity > self.quantity:
            raise ValueError("filled quantity is out of range")
        if self.side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        if self.filled_price is not None and self.filled_price <= 0:
            raise ValueError("filled price must be positive")

    @property
    def is_working(self) -> bool:
        return self.status in {OrderStatus.NEW, OrderStatus.ACCEPTED}


class BrokerAdapter(Protocol):
    def submit(self, intent: OrderIntent) -> BrokerOrder:
        """Accept an intent and return the broker's acknowledged order."""

    def cancel(self, order_id: str) -> BrokerOrder:
        """Cancel a working order. Unknown ids fail closed."""

    def track(self, order_id: str) -> BrokerOrder:
        """Return the current broker state of an order. Unknown ids fail closed."""
