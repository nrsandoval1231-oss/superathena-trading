"""Point-in-time contract for non-price evidence.

News, sentiment, fundamentals and macro series are the fastest way to destroy a
backtest, because the convenient timestamp on a record is almost never the
moment a trader could first have acted on it.  This module makes the honest
timestamp mandatory: every record carries ``available_at``, visibility is
``available_at <= decision_time`` and nothing else, and a record that revises an
earlier one is never visible in place of the original.

Nothing here imports from ``orb_m`` or ``aat_v1``.  The deterministic strategy
must stay runnable with this package deleted.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..athena_adapter.contracts import canonical_hash

#: Frozen source vocabulary.  A new source is a schema change, not a new string.
SOURCES = ("news", "sentiment", "fundamentals", "macro", "prediction_market")

#: ``symbol is None`` is only legal for market-wide evidence.
MARKET_WIDE_SOURCES = ("macro", "prediction_market")


class ExogenousLeakageError(ValueError):
    """A record cannot be shown at the requested decision time."""


class ExogenousContractError(ValueError):
    """A record is malformed and cannot be admitted at any decision time."""


@dataclass(frozen=True)
class ExogenousRecord:
    """One non-price fact, with the two timestamps kept separate.

    ``event_at`` is when the fact became true.  ``available_at`` is when it
    first became observable.  They are different numbers for almost every
    interesting source -- an earnings figure is true at the period end and
    observable weeks later -- and collapsing them is the leak.
    """

    source: str
    symbol: str | None
    event_at: datetime
    available_at: datetime
    payload: Mapping[str, Any]
    #: Set when this record restates an earlier one.  Revisions are admitted to
    #: the store so their existence is auditable, but never made visible: a
    #: decision replayed at time T must see what was published then, not what
    #: the number was later corrected to.
    revision_of: str | None = None

    def __post_init__(self) -> None:
        if self.source not in SOURCES:
            raise ExogenousContractError(f"unsupported exogenous source {self.source!r}")
        if self.symbol is None:
            if self.source not in MARKET_WIDE_SOURCES:
                raise ExogenousContractError(f"{self.source} records require a symbol")
        elif not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ExogenousContractError("symbol must be a non-empty string or None")
        for label, value in (("event_at", self.event_at), ("available_at", self.available_at)):
            if not isinstance(value, datetime):
                raise ExogenousContractError(f"{label} must be a datetime")
            if value.tzinfo is None or value.utcoffset() is None:
                raise ExogenousContractError(f"{label} must be timezone-aware")
        if self.available_at < self.event_at:
            raise ExogenousContractError("available_at precedes event_at")
        if not isinstance(self.payload, Mapping) or not self.payload:
            raise ExogenousContractError("payload must be a non-empty mapping")
        if self.revision_of is not None and (
            not isinstance(self.revision_of, str) or not self.revision_of.strip()
        ):
            raise ExogenousContractError("revision_of must be a non-empty string or None")

    @property
    def record_id(self) -> str:
        """Content identity.  Two byte-identical facts are the same record."""
        return canonical_hash({
            "source": self.source,
            "symbol": self.symbol,
            "event_at": self.event_at,
            "available_at": self.available_at,
            "payload": dict(self.payload),
        })

    def __hash__(self) -> int:
        # The generated hash would fold in ``payload`` and fail on a dict.
        # Content identity is already defined, so hash by it.
        return hash(self.record_id)

    def publication_lag_seconds(self) -> float:
        return (self.available_at - self.event_at).total_seconds()

    def as_row(self) -> dict[str, Any]:
        """Serializable form.  ``record_id`` is derived, never stored as truth."""
        return {
            "source": self.source,
            "symbol": self.symbol,
            "event_at": self.event_at.isoformat(),
            "available_at": self.available_at.isoformat(),
            "payload": dict(self.payload),
            "revision_of": self.revision_of,
        }


def parse_record(raw: Mapping[str, Any]) -> ExogenousRecord:
    """Build a record from a decoded JSON object, failing closed."""
    if not isinstance(raw, Mapping):
        raise ExogenousContractError("record is not an object")
    missing = {"source", "symbol", "event_at", "available_at", "payload"} - set(raw)
    if missing:
        raise ExogenousContractError(f"record is missing {sorted(missing)}")
    try:
        event_at = datetime.fromisoformat(str(raw["event_at"]))
        available_at = datetime.fromisoformat(str(raw["available_at"]))
    except ValueError as exc:
        raise ExogenousContractError("record timestamps are not ISO-8601") from exc
    return ExogenousRecord(
        source=str(raw["source"]),
        symbol=None if raw["symbol"] is None else str(raw["symbol"]),
        event_at=event_at,
        available_at=available_at,
        payload=raw["payload"],
        revision_of=None if raw.get("revision_of") is None else str(raw["revision_of"]),
    )


def visible_records(
    records: Iterable[ExogenousRecord],
    *,
    as_of: datetime,
    symbol: str | None = None,
    sources: Sequence[str] | None = None,
    lookback_seconds: float | None = None,
) -> tuple[ExogenousRecord, ...]:
    """Return exactly what was observable at ``as_of``, in deterministic order.

    Filtering is inclusive of ``as_of`` itself: a record published on the
    decision minute was readable on the decision minute.  Revisions are dropped
    outright rather than replacing their originals, which is the conservative
    direction -- a replay sees the stale number a trader actually had.

    A symbol filter keeps market-wide records (``symbol is None``) alongside the
    named symbol, because macro evidence applies to every name at once.
    """
    if not isinstance(as_of, datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ExogenousLeakageError("as_of must be timezone-aware")
    if lookback_seconds is not None and lookback_seconds <= 0:
        raise ExogenousLeakageError("lookback_seconds must be positive")
    allowed = tuple(sources) if sources is not None else SOURCES
    unknown = set(allowed) - set(SOURCES)
    if unknown:
        raise ExogenousContractError(f"unsupported exogenous source {sorted(unknown)}")

    selected = []
    for record in records:
        if record.revision_of is not None:
            continue
        if record.source not in allowed:
            continue
        if record.available_at > as_of:
            continue
        if symbol is not None and record.symbol not in (symbol, None):
            continue
        if lookback_seconds is not None and (
            (as_of - record.available_at).total_seconds() > lookback_seconds
        ):
            continue
        selected.append(record)
    # Sort by observability, then by content identity so ties are stable across
    # runs and platforms.  Analyst output must not depend on input file order.
    selected.sort(key=lambda item: (item.available_at, item.record_id))
    return tuple(selected)


def assert_no_lookahead(records: Iterable[ExogenousRecord], *, as_of: datetime) -> None:
    """Raise if any record in a supposedly-filtered set postdates ``as_of``."""
    for record in records:
        if record.available_at > as_of:
            raise ExogenousLeakageError(
                f"record {record.record_id[:12]} became available after {as_of.isoformat()}"
            )
        if record.revision_of is not None:
            raise ExogenousLeakageError(
                f"record {record.record_id[:12]} is a revision and is never visible"
            )
