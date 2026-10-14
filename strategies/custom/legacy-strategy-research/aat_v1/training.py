"""Training-only AAT-V1 projection validation and dry-run planning.

This module intentionally does not import a broker, strategy, or OpenAI client.
It plans calls; a later, separately authorized runner may execute them.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..athena_adapter.contracts import canonical_hash, canonical_json

_FORBIDDEN = {"sealed_holdout", "holdout", "outcome", "regret", "partition", "ticker", "timestamp", "date"}
_SCHEMA = "athena-aat-v1-opportunity-projection-v1"


class AATValidationError(ValueError):
    """The registered protocol or training projection is unsafe to consume."""


@dataclass(frozen=True)
class TrainingRow:
    opportunity_id: str
    candidate_hash: str
    features: Mapping[str, Any]


def _safe_path(path: Path) -> None:
    if "sealed_holdout" in str(path).lower() or "holdout" in str(path).lower():
        raise AATValidationError("SEALED_HOLDOUT path is forbidden")


def load_registered_protocol(path: str | Path) -> Mapping[str, Any]:
    path = Path(path)
    _safe_path(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AATValidationError("registered protocol is unreadable") from exc
    if value.get("schema_version") != "athena-aat-v1-registered-protocol-v1":
        raise AATValidationError("registered protocol schema mismatch")
    if value.get("execution_authority") != "ABSENT":
        raise AATValidationError("execution authority must be ABSENT")
    protocol = value.get("protocol")
    if not isinstance(protocol, Mapping):
        raise AATValidationError("registered protocol payload is malformed")
    actor = protocol.get("actor")
    if not isinstance(actor, Mapping) or actor.get("model_id") != "gpt-5.6-terra":
        raise AATValidationError("Actor is not pinned to gpt-5.6-terra")
    return value


def load_training_projection(receipt_path: str | Path, protocol_path: str | Path) -> tuple[Mapping[str, Any], tuple[TrainingRow, ...]]:
    """Load only a separately materialized TRAINING JSONL projection."""
    receipt_file, protocol_file = Path(receipt_path), Path(protocol_path)
    _safe_path(receipt_file)
    receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
    if not isinstance(receipt, Mapping) or receipt.get("schema_version") != _SCHEMA:
        raise AATValidationError("training projection receipt schema mismatch")
    if receipt.get("partition") != "TRAINING" or receipt.get("execution_authority") != "ABSENT":
        raise AATValidationError("projection is not TRAINING-only with absent authority")
    if receipt.get("contains_outcomes") is not False or receipt.get("contains_sealed_holdout") is not False:
        raise AATValidationError("projection must explicitly exclude outcomes and sealed holdout content")
    projection_payload = dict(receipt)
    projection_hash = projection_payload.pop("projection_hash", None)
    if projection_hash != canonical_hash(projection_payload):
        raise AATValidationError("opportunity projection hash mismatch")
    registered = load_registered_protocol(protocol_file)
    protocol = registered["protocol"]
    for key in ("dataset_hash", "assignment_hash"):
        if receipt.get(key) != protocol.get(key):
            raise AATValidationError(f"{key} mismatch")
    if receipt.get("protocol_hash") != registered.get("protocol_hash"):
        raise AATValidationError("protocol hash mismatch")
    rows_name = receipt.get("rows_path")
    if not isinstance(rows_name, str):
        raise AATValidationError("training rows path is missing")
    rows_path = (receipt_file.parent / rows_name).resolve()
    _safe_path(rows_path)
    if not rows_path.is_file():
        raise AATValidationError("training rows file is missing")
    if receipt.get("rows_sha256") != hashlib.sha256(rows_path.read_bytes()).hexdigest():
        raise AATValidationError("training rows hash mismatch")
    rows: list[TrainingRow] = []
    seen: set[str] = set()
    with rows_path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise AATValidationError(f"invalid training row at line {line_number}") from exc
            if not isinstance(raw, Mapping):
                raise AATValidationError("training row is not an object")
            if any(str(key).lower() in _FORBIDDEN for key in raw):
                raise AATValidationError("training row contains forbidden leakage field")
            ident, candidate, features = raw.get("opportunity_id"), raw.get("candidate_hash"), raw.get("features")
            if not isinstance(ident, str) or not ident or ident in seen or not isinstance(candidate, str) or not isinstance(features, Mapping):
                raise AATValidationError("training row identity/features are malformed")
            if any(str(key).lower() in _FORBIDDEN for key in features):
                raise AATValidationError("training features contain forbidden leakage field")
            seen.add(ident)
            rows.append(TrainingRow(ident, candidate, dict(features)))
    if len(rows) != receipt.get("row_count") or not rows:
        raise AATValidationError("training row count mismatch or empty projection")
    return receipt, tuple(rows)


def plan_training_run(receipt: Mapping[str, Any], rows: Sequence[TrainingRow], *, call_ceiling: int | None, token_ceiling: int | None, spend_ceiling_usd: float | None) -> Mapping[str, Any]:
    """Return a deterministic plan; this function cannot make an Actor call."""
    if call_ceiling is None or token_ceiling is None or spend_ceiling_usd is None:
        raise AATValidationError("explicit call, token, and spend ceilings are required")
    if call_ceiling < 1 or token_ceiling < 1 or spend_ceiling_usd < 0:
        raise AATValidationError("ceilings must be non-negative/positive as applicable")
    # Arm A is deterministic and must never be attributed to or billed as an
    # Actor call. Only B/C/D invoke the pinned model.
    calls = len(rows) * 3
    tokens_per_call = 256 + 64 + max(1, max(len(canonical_json(row.features)) for row in rows) // 4)
    tokens = calls * tokens_per_call
    if calls > call_ceiling or tokens > token_ceiling:
        raise AATValidationError("explicit run ceiling exceeded")
    return {"schema_version": "athena-aat-v1-training-plan-v1", "protocol_hash": receipt["protocol_hash"], "dataset_hash": receipt["dataset_hash"], "partition": "TRAINING", "row_count": len(rows), "arm_count": 4, "actor_arm_count": 3, "planned_calls": calls, "planned_tokens": tokens, "spend_ceiling_usd": spend_ceiling_usd, "spend_estimate": "UNPRICED", "dry_run": True, "execution_authority": "ABSENT"}
