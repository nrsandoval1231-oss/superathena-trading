"""In-memory broker double. No network, no credentials, deterministic."""
from __future__ import annotations

from ..execution.authority import require_paper
from ..execution.broker import BrokerError, BrokerOrder, OrderStatus
from ..execution.intent import OrderIntent


class FixtureBroker:
    """Paper-loop stand-in used by CI and ``--dry-run``.

    Submits land as ``NEW`` so cancel/track can be exercised. Tests that want a
    fill call ``fill``. Nothing here talks to Alpaca.
    """

    def __init__(self) -> None:
        self._orders: dict[str, BrokerOrder] = {}
        self._seq = 0
        self.submissions: list[OrderIntent] = []
        self.cancels: list[str] = []

    def submit(self, intent: OrderIntent) -> BrokerOrder:
        require_paper(intent.authority)
        self._seq += 1
        order = BrokerOrder(
            broker_order_id=f"fixture-{self._seq}",
            client_order_id=intent.client_order_id,
            status=OrderStatus.NEW,
            symbol=intent.symbol,
            side=intent.side,
            quantity=intent.quantity,
        )
        self._orders[order.broker_order_id] = order
        self.submissions.append(intent)
        return order

    def cancel(self, order_id: str) -> BrokerOrder:
        current = self.track(order_id)
        if current.status is OrderStatus.FILLED:
            raise BrokerError(f"cannot cancel a filled order: {order_id}")
        if current.status is OrderStatus.CANCELED:
            return current
        updated = _replace_status(current, OrderStatus.CANCELED)
        self._orders[order_id] = updated
        self.cancels.append(order_id)
        return updated

    def track(self, order_id: str) -> BrokerOrder:
        try:
            return self._orders[order_id]
        except KeyError as exc:
            raise BrokerError(f"unknown order: {order_id}") from exc

    def fill(self, order_id: str, *, price: float) -> BrokerOrder:
        current = self.track(order_id)
        if current.status is OrderStatus.CANCELED:
            raise BrokerError(f"cannot fill a canceled order: {order_id}")
        updated = BrokerOrder(
            broker_order_id=current.broker_order_id,
            client_order_id=current.client_order_id,
            status=OrderStatus.FILLED,
            symbol=current.symbol,
            side=current.side,
            quantity=current.quantity,
            filled_quantity=current.quantity,
            filled_price=price,
        )
        self._orders[order_id] = updated
        return updated


def _replace_status(order: BrokerOrder, status: OrderStatus) -> BrokerOrder:
    return BrokerOrder(
        broker_order_id=order.broker_order_id,
        client_order_id=order.client_order_id,
        status=status,
        symbol=order.symbol,
        side=order.side,
        quantity=order.quantity,
        filled_quantity=order.filled_quantity,
        filled_price=order.filled_price,
    )
