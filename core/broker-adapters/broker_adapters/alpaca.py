"""Alpaca paper broker adapter.

Pinned to ``https://paper-api.alpaca.markets``. Any other base URL is rejected.
Credentials come from the environment only and are never logged. Absence of
keys fails closed; the adapter does not invent a dry-run send.

A live HTTP call is optional. CI uses an injected transport or
``FixtureBroker``. This module does not enable live trading.
"""
from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..execution.authority import require_paper
from ..execution.broker import BrokerError, BrokerOrder, OrderStatus
from ..execution.intent import OrderIntent

PAPER_API_BASE = "https://paper-api.alpaca.markets"
_STATUS_MAP = {
    "new": OrderStatus.NEW,
    "accepted": OrderStatus.ACCEPTED,
    "pending_new": OrderStatus.ACCEPTED,
    "filled": OrderStatus.FILLED,
    "partially_filled": OrderStatus.ACCEPTED,
    "canceled": OrderStatus.CANCELED,
    "cancelled": OrderStatus.CANCELED,
    "rejected": OrderStatus.REJECTED,
    "expired": OrderStatus.CANCELED,
}

Transport = Callable[[str, str, dict[str, str], bytes | None], tuple[int, bytes]]


class MissingCredentialsError(BrokerError):
    """Alpaca paper keys were not provided. Fail closed; do not send."""


class AlpacaPaperError(BrokerError):
    """Paper endpoint refused the request or returned an unusable payload."""


def _canonical_base(url: str) -> str:
    return url.strip().rstrip("/")


def _default_transport(
    method: str, url: str, headers: dict[str, str], body: bytes | None,
) -> tuple[int, bytes]:
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, response.read()
    except HTTPError as exc:
        if exc.code == 204:
            return 204, b""
        detail = _safe_error_body(exc)
        raise AlpacaPaperError(
            f"Alpaca paper {method} failed closed with HTTP {exc.code}{detail}"
        ) from exc
    except URLError as exc:
        raise AlpacaPaperError("Alpaca paper request failed closed") from exc


def _safe_error_body(exc: HTTPError) -> str:
    try:
        raw = exc.read().decode("utf-8", errors="replace")[:200]
    except OSError:
        return ""
    if not raw:
        return ""
    return f": {raw}"


class AlpacaPaperBroker:
    """Submit / cancel / track against the Alpaca paper endpoint only."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        base_url: str = PAPER_API_BASE,
        transport: Transport | None = None,
    ) -> None:
        if not api_key or not api_secret:
            raise MissingCredentialsError("Alpaca paper credentials are required")
        if _canonical_base(base_url) != PAPER_API_BASE:
            raise ValueError("Alpaca adapter is pinned to the paper endpoint")
        self._api_key = api_key
        self._api_secret = api_secret
        self._base = PAPER_API_BASE
        self._transport = transport or _default_transport

    @classmethod
    def from_env(cls, **kwargs: Any) -> AlpacaPaperBroker:
        key = os.environ.get("ALPACA_API_KEY")
        secret = os.environ.get("ALPACA_API_SECRET")
        if not key or not secret:
            raise MissingCredentialsError(
                "ALPACA_API_KEY and ALPACA_API_SECRET are required for Alpaca paper"
            )
        return cls(key, secret, **kwargs)

    def submit(self, intent: OrderIntent) -> BrokerOrder:
        require_paper(intent.authority)
        payload = {
            "symbol": intent.symbol,
            "qty": str(intent.quantity),
            "side": intent.side.lower(),
            "type": intent.order_type.lower(),
            "time_in_force": intent.time_in_force.lower(),
            "client_order_id": intent.client_order_id,
        }
        raw = self._request("POST", "/v2/orders", payload)
        return order_from_alpaca(raw)

    def cancel(self, order_id: str) -> BrokerOrder:
        if not order_id:
            raise AlpacaPaperError("order id is required")
        self._request("DELETE", f"/v2/orders/{order_id}")
        return self.track(order_id)

    def track(self, order_id: str) -> BrokerOrder:
        if not order_id:
            raise AlpacaPaperError("order id is required")
        raw = self._request("GET", f"/v2/orders/{order_id}")
        return order_from_alpaca(raw)

    def preflight(self) -> Mapping[str, Any]:
        """Read-only account ping. Optional; fails closed without keys or network."""
        return self._request("GET", "/v2/account")

    def _headers(self) -> dict[str, str]:
        return {
            "APCA-API-KEY-ID": self._api_key,
            "APCA-API-SECRET-KEY": self._api_secret,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _request(
        self, method: str, path: str, payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        url = f"{self._base}{path}"
        status, raw = self._transport(method, url, self._headers(), body)
        if status == 204:
            return {}
        if status < 200 or status >= 300:
            raise AlpacaPaperError(
                f"Alpaca paper {method} failed closed with HTTP {status}"
            )
        if not raw:
            return {}
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AlpacaPaperError("Alpaca paper response was not JSON") from exc
        if not isinstance(parsed, dict):
            raise AlpacaPaperError("Alpaca paper response was not an object")
        return parsed


def order_from_alpaca(payload: Mapping[str, Any]) -> BrokerOrder:
    """Map an Alpaca order payload. Unknown statuses fail closed."""
    try:
        status_raw = str(payload["status"]).strip().lower()
        status = _STATUS_MAP[status_raw]
        quantity = int(float(payload["qty"]))
        filled_raw = payload.get("filled_qty") or 0
        filled_quantity = int(float(filled_raw))
        price_raw = payload.get("filled_avg_price")
        filled_price = float(price_raw) if price_raw not in (None, "") else None
        side = str(payload["side"]).strip().upper()
        return BrokerOrder(
            broker_order_id=str(payload["id"]),
            client_order_id=str(payload["client_order_id"]),
            status=status,
            symbol=str(payload["symbol"]).strip().upper(),
            side=side,
            quantity=quantity,
            filled_quantity=filled_quantity,
            filled_price=filled_price,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AlpacaPaperError("Alpaca paper order payload is unusable") from exc
