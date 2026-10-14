"""Exogenous feature snapshot joined to opportunities.

The snapshot is the artifact an AAT-V2 protocol would register: one bucketed
feature vector per opportunity, hashed, with the compressor identity and the
source store named inside the receipt so the whole thing is replayable.

It reads an opportunity index -- ``opportunity_id``, ``symbol``,
``decision_at``, optional ``prior_close_at`` -- rather than importing from
``aat_v1``.  The dependency direction is one-way for the same reason it is
one-way at the Athena Core boundary: the strategy must stay runnable with this
package deleted.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from ..athena_adapter.contracts import canonical_hash
from .analysts import compress_all, compressor_identity, coverage, feature_keys
from .contracts import ExogenousRecord, visible_records
from .ingest import load_record_store

SNAPSHOT_SCHEMA = "athena-exogenous-snapshot-v1"


class SnapshotError(ValueError):
    """The snapshot cannot be built from the supplied evidence."""


def _parse_opportunity(raw: Mapping[str, Any], line_number: int) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise SnapshotError(f"opportunity {line_number} is not an object")
    missing = {"opportunity_id", "symbol", "decision_at"} - set(raw)
    if missing:
        raise SnapshotError(f"opportunity {line_number} is missing {sorted(missing)}")
    try:
        decision_at = datetime.fromisoformat(str(raw["decision_at"]))
        prior_close_at = (
            datetime.fromisoformat(str(raw["prior_close_at"]))
            if raw.get("prior_close_at") else None
        )
    except ValueError as exc:
        raise SnapshotError(f"opportunity {line_number} has invalid timestamps") from exc
    if decision_at.tzinfo is None or (prior_close_at and prior_close_at.tzinfo is None):
        raise SnapshotError(f"opportunity {line_number} timestamps must be timezone-aware")
    identifier, symbol = str(raw["opportunity_id"]), str(raw["symbol"])
    if not identifier.strip() or not symbol.strip():
        raise SnapshotError(f"opportunity {line_number} has an empty identifier")
    return {
        "opportunity_id": identifier,
        "symbol": symbol,
        "decision_at": decision_at,
        "prior_close_at": prior_close_at,
    }


def load_opportunity_index(path: str | Path) -> tuple[dict[str, Any], ...]:
    """Read the JSONL opportunity index the snapshot is built against."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise SnapshotError("opportunity index is unreadable") from exc
    rows = []
    seen = set()
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SnapshotError(f"opportunity {number} is not JSON") from exc
        row = _parse_opportunity(raw, number)
        if row["opportunity_id"] in seen:
            raise SnapshotError(f"duplicate opportunity {row['opportunity_id']}")
        seen.add(row["opportunity_id"])
        rows.append(row)
    if not rows:
        raise SnapshotError("opportunity index is empty")
    return tuple(rows)


def compress_opportunity(
    records: Iterable[ExogenousRecord], opportunity: Mapping[str, Any],
) -> dict[str, Any]:
    """Compress the evidence visible to one opportunity at its decision time."""
    as_of = opportunity["decision_at"]
    visible = visible_records(records, as_of=as_of, symbol=opportunity["symbol"])
    features = compress_all(
        visible, as_of=as_of, prior_close=opportunity.get("prior_close_at")
    )
    return {
        "opportunity_id": opportunity["opportunity_id"],
        "features": features,
        "visible_record_count": len(visible),
    }


def build_snapshot(
    opportunity_index_path: str | Path,
    store_receipt_path: str | Path,
    rows_path: str | Path,
    receipt_path: str | Path,
) -> dict[str, Any]:
    """Write one feature row per opportunity, plus a receipt naming its inputs."""
    rows_file, receipt_file = Path(rows_path), Path(receipt_path)
    if rows_file.exists() or receipt_file.exists():
        raise SnapshotError("refusing to overwrite an existing snapshot")
    opportunities = load_opportunity_index(opportunity_index_path)
    store_receipt, records = load_record_store(store_receipt_path)
    identity = compressor_identity()

    rows = [compress_opportunity(records, opportunity) for opportunity in opportunities]
    keys = set(feature_keys())
    for row in rows:
        if set(row["features"]) != keys:
            raise SnapshotError(f"opportunity {row['opportunity_id']} produced a drifted key set")

    rows_file.parent.mkdir(parents=True, exist_ok=True)
    rows_file.write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows
        ),
        encoding="utf-8",
    )
    receipt = {
        "schema_version": SNAPSHOT_SCHEMA,
        "rows_path": rows_file.name,
        "rows_sha256": hashlib.sha256(rows_file.read_bytes()).hexdigest(),
        "row_count": len(rows),
        "feature_keys": list(feature_keys()),
        "compressor_identity_hash": identity["identity_hash"],
        "compressor_version": identity["version"],
        "record_store_hash": store_receipt["store_hash"],
        "coverage_rates": coverage_rates(rows),
        "contains_outcomes": False,
        "execution_authority": "ABSENT",
    }
    receipt["snapshot_hash"] = canonical_hash(receipt)
    receipt_file.parent.mkdir(parents=True, exist_ok=True)
    receipt_file.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return receipt


def coverage_rates(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """Share of opportunities with any evidence, per source.

    This is the number that decides whether the V2 comparison has power. If
    coverage is thin the adaptive arms are the deterministic arm with extra
    steps, and a null result means nothing about adaptation.
    """
    if not rows:
        return {}
    totals: dict[str, int] = {}
    for row in rows:
        for source, present in coverage(row["features"]).items():
            totals[source] = totals.get(source, 0) + int(present)
    return {source: round(count / len(rows), 6) for source, count in sorted(totals.items())}
