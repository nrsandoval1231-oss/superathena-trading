"""Which paper positions and orders belong to which arm.

The intraday runner and the earnings runner can share one Alpaca paper account.
Intraday client order ids start with ``athp-``. Earnings ids start with ``athe-``.
A position is earnings-owned when an earnings order (or a leg of one) names its
symbol, or when the earnings ledger still lists that symbol. The intraday arm
never treats its own symbol as foreign: a collision stays visible and blocks
account-wide cleanup.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

EARNINGS_ORDER_PREFIX = "athe-"
INTRADAY_ORDER_PREFIX = "athp-"
OWNERSHIP_FILENAME = "ownership.json"


def earnings_state_dir() -> Path | None:
    """Directory the earnings arm uses. Unset means the ledger is not consulted."""
    raw = os.environ.get("ATHENA_EARNINGS_STATE_DIR", "").strip()
    if not raw:
        return None
    return Path(raw)


def _prefixed(order: dict[str, Any], prefix: str) -> bool:
    client_order_id = order.get("client_order_id")
    return isinstance(client_order_id, str) and client_order_id.startswith(prefix)


def symbols_for_prefix(orders: Any, prefix: str) -> set[str]:
    """Symbols on orders with this prefix, including nested legs of those parents."""
    found: set[str] = set()

    def walk(order: Any, inherited: bool) -> None:
        if not isinstance(order, dict):
            return
        owned = inherited or _prefixed(order, prefix)
        symbol = order.get("symbol")
        if owned and isinstance(symbol, str) and symbol:
            found.add(symbol)
        legs = order.get("legs") or []
        if isinstance(legs, list):
            for leg in legs:
                walk(leg, owned)

    if isinstance(orders, list):
        for order in orders:
            walk(order, False)
    return found


def _load_ownership(state_dir: Path | None) -> dict[str, Any]:
    if state_dir is None:
        return {}
    path = state_dir / OWNERSHIP_FILENAME
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("earnings ownership ledger is unreadable") from exc
    if not isinstance(payload, dict):
        raise ValueError("earnings ownership ledger is unreadable")
    if payload.get("arm") != "earnings" or payload.get("prefix") != EARNINGS_ORDER_PREFIX:
        raise ValueError("earnings ownership ledger is not the earnings arm")
    return payload


def load_ownership_symbols(state_dir: Path | None) -> set[str]:
    """Active symbols only. Historical orders must never hide a new position."""
    payload = _load_ownership(state_dir)
    symbols = payload.get("symbols") if payload else []
    if not isinstance(symbols, list) or any(type(symbol) is not str or not symbol for symbol in symbols):
        raise ValueError("earnings ownership ledger symbols are invalid")
    return set(symbols)


_ORDER_IDENTITY = ("id", "client_order_id", "symbol", "side", "type")


def load_ownership_orders(state_dir: Path | None, account_id: str) -> dict[str, dict[str, str]]:
    """Exact historical order identities published from the durable earnings journal."""
    payload = _load_ownership(state_dir)
    rows = payload.get("historical_orders", [])
    if not isinstance(rows, list):
        raise ValueError("earnings historical ownership is invalid")
    if rows and payload.get("account_id") != account_id:
        raise ValueError("earnings historical ownership belongs to a different account")
    orders: dict[str, dict[str, str]] = {}
    for row in rows:
        if not isinstance(row, dict) or any(
            not isinstance(row.get(key), str) or not row[key] for key in _ORDER_IDENTITY
        ):
            raise ValueError("earnings historical ownership is invalid")
        identity = {key: row[key] for key in _ORDER_IDENTITY}
        if row["id"] in orders and orders[row["id"]] != identity:
            raise ValueError("conflicting earnings historical ownership")
        orders[row["id"]] = identity
    return orders


def write_ownership_ledger(
    state_dir: Path, symbols: set[str], orders: list[dict[str, str]], *,
    historical_orders: list[dict[str, str]] | None = None, account_id: str | None = None,
) -> None:
    """Publish live symbols separately from durable, account-bound order provenance."""
    state_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "arm": "earnings", "prefix": EARNINGS_ORDER_PREFIX,
        "symbols": sorted(symbols), "orders": orders,
        "historical_orders": historical_orders or [], "account_id": account_id,
    }
    path = state_dir / OWNERSHIP_FILENAME
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w") as stream:
        json.dump(payload, stream, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    descriptor = os.open(state_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def intraday_book(
    positions: Any, orders: Any, *, own_symbol: str, ledger_symbols: set[str],
) -> tuple[list[Any], list[Any]]:
    """Drop earnings-owned positions and orders. Keep every other symbol.

    ``own_symbol`` is never dropped. If both arms touch it, the intraday arm
    still sees the exposure and refuses to flatten the account.
    """
    if not isinstance(positions, list) or not isinstance(orders, list):
        raise ValueError("broker positions and orders are incomplete")
    foreign = symbols_for_prefix(orders, EARNINGS_ORDER_PREFIX) | set(ledger_symbols)
    foreign.discard(own_symbol)
    kept_positions = [item for item in positions if item.get("symbol") not in foreign]
    kept_orders = [item for item in orders if item.get("symbol") not in foreign]
    return kept_positions, kept_orders


def _prefixed_tree(order: dict[str, Any], prefix: str) -> bool:
    client_order_id = order.get("client_order_id")
    if isinstance(client_order_id, str) and client_order_id.startswith(prefix):
        return True
    legs = order.get("legs") or []
    if isinstance(legs, list):
        return any(isinstance(leg, dict) and _prefixed_tree(leg, prefix) for leg in legs)
    return False


def _tree_ids(order: dict[str, Any]) -> set[str]:
    found: set[str] = set()
    if isinstance(order.get("id"), str):
        found.add(order["id"])
    legs = order.get("legs") or []
    if isinstance(legs, list):
        for leg in legs:
            if isinstance(leg, dict):
                found.update(_tree_ids(leg))
    return found


def _terminal_role(
    order: dict[str, Any], *, owned_ids: set[str], earnings_orders: dict[str, dict[str, str]],
) -> str:
    """Attribute terminal history by order provenance, never by a live symbol alone."""
    if _prefixed_tree(order, EARNINGS_ORDER_PREFIX):
        return "earnings"
    if _prefixed_tree(order, INTRADAY_ORDER_PREFIX) or bool(_tree_ids(order) & owned_ids):
        return "intraday"
    identity = earnings_orders.get(order.get("id"))
    if identity and all(order.get(key) == identity[key] for key in _ORDER_IDENTITY):
        return "earnings"
    return "unexplained"


def terminal_learning_history(
    history: Any, *, owned_ids: set[str], earnings_orders: dict[str, dict[str, str]],
) -> list[Any]:
    """Learning input for one arm. Account evidence stays with the caller.

    Nested legs remain inside their parent. An owned close is kept even when the
    broker assigned its client id. Anything this arm cannot attribute is an error,
    not a silent omission.
    """
    if not isinstance(history, list):
        raise ValueError("terminal broker order history is incomplete")
    learning: list[Any] = []
    for order in history:
        if not isinstance(order, dict) or not isinstance(order.get("id"), str):
            raise ValueError("terminal broker order history is incomplete")
        role = _terminal_role(
            order, owned_ids=owned_ids, earnings_orders=earnings_orders,
        )
        if role == "earnings":
            continue
        if role == "intraday":
            learning.append(order)
            continue
        raise ValueError("unexplained exposure in terminal broker order history")
    return learning
