"""One paper risk view for both arms.

Each arm keeps its own approved caps. This gate adds only the account facts
both books can already see: a symbol cannot be reserved twice, and combined
reserved notional cannot exceed buying power. Correlation, concentration,
weekly and monthly loss, portfolio drawdown, and overnight stress have no
approved threshold. Those checks are listed and do not authorize exposure.
"""
from __future__ import annotations

import fcntl
import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from ..athena_adapter.contracts import canonical_hash
from ..accounting.journal import PaperJournal

UNRESOLVED_SHARED_POLICY = (
    "correlation_limit",
    "concentration_limit",
    "weekly_loss_limit",
    "monthly_loss_limit",
    "portfolio_drawdown_limit",
    "overnight_stress_limit",
)


@dataclass(frozen=True)
class OpenExposure:
    arm: str
    symbol: str
    notional: float
    stop_risk: float
    overnight: bool
    client_order_id: str
    acknowledged: bool = False


@dataclass(frozen=True)
class SharedDecision:
    allowed: bool
    reason: str
    unresolved: tuple[str, ...] = UNRESOLVED_SHARED_POLICY
    overnight_authority: str = "inactive"


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in {float("inf"), float("-inf")}:
        return None
    return result


# A filled or otherwise finished parent releases shares that never filled.
_TERMINAL_RELEASE = {"filled", "canceled", "expired", "rejected", "replaced"}
_WORKING = {
    "new", "accepted", "pending_new", "accepted_for_bidding", "partially_filled",
    "pending_cancel", "pending_replace", "held", "stopped", "suspended", "calculated",
    "done_for_day",  # GTC orders can resume tomorrow; this is not a cancellation.
}


class SharedExposureUnreadable(ValueError):
    """Peer exposure cannot be proven. New entries stop; open protection does not."""


def _malformed(detail: str) -> SharedExposureUnreadable:
    return SharedExposureUnreadable(f"malformed exposure: {detail}")


def _leg_fills(order: dict[str, Any], parent: dict[str, Any]) -> float:
    exited = 0.0
    legs = parent.get("legs") or []
    if not isinstance(legs, list):
        raise _malformed("legs")
    for leg in legs:
        if not isinstance(leg, dict) or leg.get("side") == order.get("side"):
            continue
        if leg.get("side") not in {"buy", "sell"}:
            raise _malformed("leg side")
        if leg.get("filled_qty") in {None, ""}:
            filled = 0.0
        else:
            filled = _number(leg.get("filled_qty"))
            if filled is None or filled < 0:
                raise _malformed("leg fill")
        exited += filled
    return exited


def _remaining_qty(order: dict[str, Any], parent: dict[str, Any] | None) -> float:
    """Working size is the unfilled remainder plus shares still held.

    Capacity is released only when the broker order is terminal. A zero fill on
    a live order reserves the whole quantity. Missing fill evidence is not zero.
    """
    reserved = _number(order.get("qty"))
    if reserved is None or reserved < 0:
        raise _malformed("quantity")
    if parent is None:
        return reserved
    if parent.get("filled_qty") in {None, ""}:
        raise _malformed("fill")
    entered = _number(parent.get("filled_qty"))
    if entered is None or entered < 0 or entered > reserved:
        raise _malformed("fill")
    exited = _leg_fills(order, parent)
    if exited > entered:
        raise _malformed("exit exceeds fill")
    status = parent.get("status")
    if status in _TERMINAL_RELEASE or (status in {None, ""} and entered == reserved):
        return entered - exited
    if status not in _WORKING:
        raise _malformed("status")
    return reserved - exited


def _acknowledged_ids(events: list[dict[str, Any]]) -> set[str]:
    found: set[str] = set()
    for event in events:
        if event.get("kind") != "entry_ack":
            continue
        identity = event.get("client_order_id")
        if isinstance(identity, str):
            found.add(identity)
        order = event.get("order")
        if isinstance(order, dict) and isinstance(order.get("client_order_id"), str):
            found.add(order["client_order_id"])
    return found


def _exposures_from_events(events: list[dict[str, Any]], arm: str) -> list[OpenExposure]:
    """Open reservations in one event stream. Malformed evidence fails closed."""
    closed = {
        event.get("client_order_id") for event in events
        if event.get("kind") in {"position_closed", "entry_not_created", "flat_confirmed"}
        and isinstance(event.get("client_order_id"), str)
    }
    flat = next((event for event in reversed(events) if event.get("kind") == "flat_confirmed"), None)
    if flat and arm == "intraday":
        closed.update(
            event["order"]["client_order_id"] for event in events
            if event.get("kind") == "entry_intent" and isinstance(event.get("order"), dict)
        )
    parents: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.get("kind") != "entry_observation":
            continue
        identity = event.get("client_order_id")
        order = event.get("order")
        if isinstance(identity, str) and isinstance(order, dict):
            parents[identity] = order
    acknowledged = _acknowledged_ids(events)
    open_rows: list[OpenExposure] = []
    seen: set[str] = set()
    for event in events:
        if event.get("kind") != "entry_intent":
            continue
        order = event.get("order")
        if not isinstance(order, dict):
            raise _malformed("entry")
        identity = order.get("client_order_id")
        if not isinstance(identity, str) or identity in closed or identity in seen:
            continue
        seen.add(identity)
        qty = _remaining_qty(order, parents.get(identity))
        price = _number(order.get("limit_price"))
        stop_loss = order.get("stop_loss") or {}
        stop = _number(stop_loss.get("stop_price") if isinstance(stop_loss, dict) else None)
        if price is None or stop is None or price <= 0:
            raise _malformed("price")
        if qty == 0:
            continue
        open_rows.append(OpenExposure(
            arm=arm, symbol=str(order.get("symbol") or ""), notional=price * qty,
            stop_risk=abs(price - stop) * qty,
            # Describes legacy GTC exposure for recovery, never entry authority.
            overnight=arm == "earnings" and order.get("time_in_force") != "day",
            client_order_id=identity, acknowledged=identity in acknowledged,
        ))
    return open_rows


def exposures_from_journal(journal: PaperJournal, arm: str) -> list[OpenExposure]:
    """Open reservations in one journal. A finished fill keeps only residual shares."""
    return _exposures_from_events(journal.events, arm)


class SharedBookBusy(ValueError):
    """Another entry holds the account coordinator. Defer entries, never protection."""


def _coordinator_directory() -> Path:
    raw = os.environ.get("ATHENA_SHARED_RISK_DIR", "").strip()
    if not raw or not Path(raw).is_absolute():
        raise SharedExposureUnreadable("ATHENA_SHARED_RISK_DIR must name an absolute shared directory")
    return Path(raw).resolve()


def _check_coordination_binding(events: list[dict[str, Any]], account_id: str) -> None:
    expected = {"account_id": account_id, "directory": str(_coordinator_directory())}
    for event in events:
        if event.get("kind") == "shared_risk_binding" and event.get("binding") != expected:
            raise SharedExposureUnreadable("shared risk account/coordinator binding changed")
        if event.get("kind") == "binding":
            bound = event.get("binding", {}).get("account_id")
            if bound is not None and bound != account_id:
                raise SharedExposureUnreadable("peer journal belongs to a different account")


@contextmanager
def entry_coordination(journal: PaperJournal, account_id: str) -> Iterator[None]:
    """Serialize fresh evidence, checks and the durable intent across both processes.

    The shared file is only a mutex. The own journal remains the durable reservation,
    visible read-only to the peer after a crash. A dead process releases flock; it
    does not release that reservation. Only entry paths acquire this lock.
    """
    root = _coordinator_directory()
    try:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(
            root / (canonical_hash({"account_id": account_id}) + ".lock"),
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600,
        )
    except OSError as exc:
        raise SharedExposureUnreadable("shared risk coordinator is unavailable") from exc
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SharedBookBusy("another entry holds the shared account coordinator") from exc
        except OSError as exc:
            raise SharedExposureUnreadable("shared risk coordinator cannot be locked") from exc
        _check_coordination_binding(journal.events, account_id)
        if journal.last("shared_risk_binding") is None:
            # Publish before reading the peer, including if operators accidentally
            # configured different mutex locations. At most one entrant can miss
            # the other's binding; the other must fail closed on the mismatch.
            journal.append("shared_risk_binding", binding={
                "account_id": account_id, "directory": str(root),
            })
        yield
    finally:
        os.close(descriptor)


def _read_events(path: Path) -> list[dict[str, Any]]:
    """Read a committed hash chain without the owning runner's writer lock.

    The sqlite file is opened read-only. This does not create the lock file,
    write a checkpoint, or change permissions. Both the hash chain and existing
    durable checkpoint are verified. A moving checkpoint retries the read rather
    than combining unrelated versions of the file and its integrity anchor.
    """
    uri = path.resolve().as_uri() + "?mode=ro"
    checkpoint = path.with_suffix(path.suffix + ".checkpoint")
    for _attempt in range(3):
        try:
            before = checkpoint.read_bytes() if checkpoint.exists() else None
            db = sqlite3.connect(uri, uri=True, timeout=1.0)
            try:
                db.execute("BEGIN")
                rows = list(db.execute("SELECT seq, payload, previous, digest FROM events ORDER BY seq"))
                has_meta = db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='journal_meta'"
                ).fetchone()
                checkpointed = has_meta and db.execute("SELECT checkpointed FROM journal_meta").fetchone()
                after = checkpoint.read_bytes() if checkpoint.exists() else None
            finally:
                db.close()
        except (OSError, sqlite3.Error) as exc:
            raise SharedExposureUnreadable(f"peer exposure is unreadable: {path}") from exc
        if before == after:
            break
    else:
        raise SharedExposureUnreadable(f"peer checkpoint changed during read: {path}")
    events: list[dict[str, Any]] = []
    head = "0" * 64
    for seq, payload, previous, digest in rows:
        try:
            event = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise SharedExposureUnreadable(f"peer exposure is unreadable: {path}") from exc
        expected = canonical_hash({"seq": seq, "event": event, "previous": previous})
        if seq != len(events) + 1 or previous != head or digest != expected:
            raise SharedExposureUnreadable(f"peer exposure hash chain failed: {path}")
        if not isinstance(event, dict):
            raise SharedExposureUnreadable(f"peer exposure is unreadable: {path}")
        events.append(event)
        head = digest
    if before is not None:
        try:
            anchor = json.loads(before)
            seq = anchor["seq"]
            if type(seq) is not int or not 0 <= seq <= len(events):
                raise ValueError("journal truncated past checkpoint")
            digest = rows[seq - 1][3] if seq else "0" * 64
            if anchor["digest"] != digest or len(events) - seq > 1:
                raise ValueError("checkpoint mismatch")
        except (KeyError, TypeError, ValueError, UnicodeError) as exc:
            raise SharedExposureUnreadable(f"peer journal checkpoint failed: {path}") from exc
    elif checkpointed:
        raise SharedExposureUnreadable(f"peer journal checkpoint is missing: {path}")
    return events


def _read_journal(path: Path, arm: str, account_id: str | None = None) -> list[OpenExposure]:
    if not path.exists():
        if path.with_suffix(path.suffix + ".checkpoint").exists():
            raise SharedExposureUnreadable(f"peer journal is missing: {path}")
        return []
    events = _read_events(path)
    if account_id is not None:
        _check_coordination_binding(events, account_id)
    return _exposures_from_events(events, arm)


def reflected_exposure(snapshot: dict[str, Any]) -> tuple[set[str], set[str]]:
    """Exposure sampled before the account by the broker snapshot contract.

    LivePaperAPI samples account last. A later order can never use an earlier
    buying-power sample to exempt its reservation. Synthetic brokers must return
    a coherent snapshot (or honor that same sampling order).
    """
    ids: set[str] = set()

    def walk(order: Any) -> None:
        if not isinstance(order, dict):
            return
        identity = order.get("client_order_id")
        if isinstance(identity, str) and identity:
            ids.add(identity)
        legs = order.get("legs") or []
        if isinstance(legs, list):
            for leg in legs:
                walk(leg)

    orders = snapshot.get("orders") or []
    if isinstance(orders, list):
        for order in orders:
            walk(order)
    symbols: set[str] = set()
    positions = snapshot.get("positions") or []
    if isinstance(positions, list):
        for position in positions:
            if isinstance(position, dict) and isinstance(position.get("symbol"), str):
                symbols.add(position["symbol"])
    return ids, symbols


def other_arm_exposure(
    arm: str, *, today: date | None = None, account_id: str | None = None,
) -> list[OpenExposure]:
    """The other book. A missing directory is an arm that is not running."""
    if arm == "earnings":
        root = Path(os.environ.get("ATHENA_STATE_DIR", ""))
        if not os.environ.get("ATHENA_STATE_DIR", "").strip() or not root.is_dir():
            return []
        rows: list[OpenExposure] = []
        # A new date does not release yesterday's unresolved reservation. Include
        # orphaned anchors as well, so deleting the DB cannot hide its exposure.
        paths = sorted(set(root.glob("*.sqlite")) | {
            path.with_suffix("") for path in root.glob("*.sqlite.checkpoint")
        })
        for path in paths:
            rows.extend(_read_journal(path, "intraday", account_id))
        return rows
    root = Path(os.environ.get("ATHENA_EARNINGS_STATE_DIR", ""))
    if not os.environ.get("ATHENA_EARNINGS_STATE_DIR", "").strip() or not root.is_dir():
        return []
    return _read_journal(root / "book.sqlite", "earnings", account_id)


def _already_in_buying_power(
    item: OpenExposure, *, reflected_client_order_ids: set[str], reflected_symbols: set[str],
) -> bool:
    """Broker buying power already deducts an acknowledged order visible in that snapshot."""
    if not item.acknowledged:
        return False
    return item.client_order_id in reflected_client_order_ids or (
        bool(item.symbol) and item.symbol in reflected_symbols
    )


def authorize_entry(
    *, arm: str, symbol: str, notional: float, stop_risk: float, overnight: bool,
    buying_power: float, open_exposure: list[OpenExposure],
    reflected_client_order_ids: set[str] | None = None,
    reflected_symbols: set[str] | None = None,
) -> SharedDecision:
    """Refuse a new entry that spends capacity the other arm already reserved.

    ``buying_power`` is the broker figure from one snapshot. Acknowledged orders
    visible in that same snapshot are not added again. A local reservation the
    snapshot does not show, including a stale snapshot or a concurrent entry,
    still counts. Unresolved portfolio checks stay inactive.
    """
    if arm not in {"intraday", "earnings"}:
        return SharedDecision(False, "UNKNOWN_ARM")
    if overnight:
        return SharedDecision(False, "OVERNIGHT_NOT_AUTHORIZED")
    if notional < 0 or stop_risk < 0 or buying_power < 0:
        return SharedDecision(False, "INVALID_EXPOSURE")
    if any(item.symbol == symbol and item.symbol for item in open_exposure):
        return SharedDecision(False, "SYMBOL_ALREADY_RESERVED")
    reflected_ids = reflected_client_order_ids or set()
    visible_symbols = reflected_symbols or set()
    used = sum(
        item.notional for item in open_exposure
        if not _already_in_buying_power(
            item, reflected_client_order_ids=reflected_ids, reflected_symbols=visible_symbols,
        )
    )
    if used + notional > buying_power:
        return SharedDecision(False, "BUYING_POWER")
    return SharedDecision(True, "AUTHORIZED", overnight_authority="flat-by-close")
