"""Receipted ingest for exogenous records.

Fetching is a separate, receipted step; compression is pure and offline.  This
module owns the boundary between them: it normalizes raw vendor rows into
``ExogenousRecord`` objects, enforces the guards that vendors do not, and
writes a hashed store the compressors can be replayed against.

No network access lives here.  A vendor adapter is a pure function from one raw
row to one record, so a source swap is a new adapter and not a new pipeline.
``passthrough_adapter`` handles rows already in contract shape.
``alfred_adapter`` maps FRED ALFRED vintage observations onto macro records;
live ALFRED fetches live in ``alfred.py``, fail closed without a key, and are
not invoked from this module.  No historical dump is stored here.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from ..athena_adapter.contracts import canonical_hash
from .contracts import (
    SOURCES,
    ExogenousContractError,
    ExogenousRecord,
    parse_record,
)

STORE_SCHEMA = "athena-exogenous-record-store-v1"

#: A vendor adapter maps one raw row to one contract record.
Adapter = Callable[[Mapping[str, Any]], ExogenousRecord]


class IngestError(ValueError):
    """Raw evidence cannot be admitted to the store."""


def passthrough_adapter(raw: Mapping[str, Any]) -> ExogenousRecord:
    """Adapter for rows already in contract shape."""
    return parse_record(raw)


def _external_id(record: ExogenousRecord) -> str | None:
    value = record.payload.get("external_id")
    return None if value is None else str(value)


def assert_stable_availability(
    records: Sequence[ExogenousRecord], previous: Iterable[Mapping[str, Any]] = (),
) -> None:
    """Reject a record whose ``available_at`` moved between pulls.

    This is the anti-backfill guard, and it is the reason the news source can be
    graded as usable at all.  Many news APIs re-timestamp a story when it is
    updated, or assign a backfill time on a later crawl.  Either silently
    rewrites when the market could first have seen it, which is precisely the
    number the whole contract depends on.

    Records are matched on ``payload.external_id``.  A vendor that supplies no
    stable id cannot be checked, and its rows pass -- so an adapter for such a
    source must synthesize one, and its provenance document must say how.
    """
    seen: dict[tuple[str, str], str] = {}
    for row in previous:
        identifier = row.get("payload", {}).get("external_id")
        if identifier is None:
            continue
        seen[(str(row["source"]), str(identifier))] = str(row["available_at"])
    for record in records:
        identifier = _external_id(record)
        if identifier is None:
            continue
        key = (record.source, identifier)
        current = record.available_at.isoformat()
        established = seen.setdefault(key, current)
        if established != current:
            raise IngestError(
                f"{record.source} record {identifier} changed availability "
                f"from {established} to {current}"
            )


def normalize(
    raw_rows: Iterable[Mapping[str, Any]], *, source: str, adapter: Adapter = passthrough_adapter,
) -> tuple[ExogenousRecord, ...]:
    """Map raw vendor rows to records, failing closed on the first bad row."""
    if source not in SOURCES:
        raise IngestError(f"unsupported exogenous source {source!r}")
    records = []
    for position, raw in enumerate(raw_rows):
        try:
            record = adapter(raw)
        except ExogenousContractError as exc:
            raise IngestError(f"{source} row {position} is not admissible: {exc}") from exc
        if record.source != source:
            raise IngestError(
                f"{source} row {position} declares source {record.source!r}"
            )
        records.append(record)
    return tuple(records)


def _deduplicate(records: Sequence[ExogenousRecord]) -> tuple[ExogenousRecord, ...]:
    """Collapse byte-identical facts, keeping deterministic order."""
    unique: dict[str, ExogenousRecord] = {}
    for record in records:
        unique.setdefault(record.record_id, record)
    return tuple(
        sorted(unique.values(), key=lambda item: (item.available_at, item.record_id))
    )


def write_record_store(
    records: Sequence[ExogenousRecord], rows_path: str | Path, receipt_path: str | Path,
    *, previous_rows_path: str | Path | None = None,
) -> dict[str, Any]:
    """Write a hashed record store plus its receipt.

    The receipt carries no outcome, no partition assignment and no execution
    authority.  It exists so a snapshot can name the exact evidence it read.
    """
    rows_file, receipt_file = Path(rows_path), Path(receipt_path)
    if rows_file.exists() or receipt_file.exists():
        raise IngestError("refusing to overwrite an existing record store")
    previous: list[Mapping[str, Any]] = []
    if previous_rows_path is not None:
        previous = [
            json.loads(line)
            for line in Path(previous_rows_path).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    assert_stable_availability(records, previous)
    admitted = _deduplicate(records)

    rows_file.parent.mkdir(parents=True, exist_ok=True)
    rows_file.write_text(
        "".join(
            json.dumps(record.as_row(), sort_keys=True, separators=(",", ":")) + "\n"
            for record in admitted
        ),
        encoding="utf-8",
    )
    counts = {source: 0 for source in SOURCES}
    revisions = 0
    for record in admitted:
        counts[record.source] += 1
        revisions += record.revision_of is not None
    receipt = {
        "schema_version": STORE_SCHEMA,
        "rows_path": rows_file.name,
        "rows_sha256": hashlib.sha256(rows_file.read_bytes()).hexdigest(),
        "row_count": len(admitted),
        "source_counts": counts,
        "revision_count": revisions,
        "earliest_available_at": (
            admitted[0].available_at.isoformat() if admitted else None
        ),
        "latest_available_at": (
            admitted[-1].available_at.isoformat() if admitted else None
        ),
        "contains_outcomes": False,
        "execution_authority": "ABSENT",
    }
    receipt["store_hash"] = canonical_hash(receipt)
    receipt_file.parent.mkdir(parents=True, exist_ok=True)
    receipt_file.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return receipt


def load_record_store(receipt_path: str | Path) -> tuple[dict[str, Any], tuple[ExogenousRecord, ...]]:
    """Load a store, verifying the receipt hash and the row digest."""
    receipt_file = Path(receipt_path)
    try:
        receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IngestError("record store receipt is unreadable") from exc
    payload = dict(receipt)
    claimed = payload.pop("store_hash", None)
    if receipt.get("schema_version") != STORE_SCHEMA or claimed != canonical_hash(payload):
        raise IngestError("record store receipt drift")
    rows_file = receipt_file.parent / str(receipt.get("rows_path", ""))
    if not rows_file.is_file():
        raise IngestError("record store rows are missing")
    if hashlib.sha256(rows_file.read_bytes()).hexdigest() != receipt.get("rows_sha256"):
        raise IngestError("record store rows hash mismatch")
    records = tuple(
        parse_record(json.loads(line))
        for line in rows_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    if len(records) != receipt.get("row_count"):
        raise IngestError("record store row count mismatch")
    return receipt, records
