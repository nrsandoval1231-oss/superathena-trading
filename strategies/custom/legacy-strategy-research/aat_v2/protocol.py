"""Register a validated AAT-V2 protocol without authorizing execution."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..athena_adapter.contracts import canonical_hash
from .contract import load_contract

PROTOCOL_SCHEMA = "athena-aat-v2-registered-protocol-v1"


class ProtocolError(ValueError):
    """The V2 protocol inputs cannot be registered safely."""


def register_protocol(
    contract_path: str | Path,
    assignment_path: str | Path,
    opportunity_receipt_path: str | Path,
    snapshot_receipt_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    """Bind validated artifacts into a non-authorizing registered protocol."""
    target = Path(output_path)
    if target.exists():
        raise ProtocolError("refusing to overwrite a registered protocol")
    contract = load_contract(contract_path)
    assignment = _load_hashed_json(assignment_path, "assignment_hash")
    if assignment.get("execution_authority") != "ABSENT":
        raise ProtocolError("assignment authority must be ABSENT")
    if assignment.get("assignment_hash") != contract.get("assignment_hash"):
        raise ProtocolError("assignment does not match contract")
    opportunity = _load_json(opportunity_receipt_path)
    snapshot = _load_json(snapshot_receipt_path)
    if opportunity.get("contains_outcomes") is not False or opportunity.get("contains_sealed_holdout") is not False:
        raise ProtocolError("opportunity receipt is not outcome-free TRAINING evidence")
    if snapshot.get("contains_outcomes") is not False or snapshot.get("execution_authority") != "ABSENT":
        raise ProtocolError("snapshot receipt is not safe evidence")
    if snapshot.get("row_count") != opportunity.get("row_count"):
        raise ProtocolError("snapshot and opportunity row counts differ")
    if snapshot.get("coverage_rates", {}).get("macro", 0.0) < contract["coverage_floor"]:
        raise ProtocolError("macro snapshot is below the registered coverage floor")
    protocol = {
        "schema_version": PROTOCOL_SCHEMA,
        "contract_hash": contract["contract_hash"],
        "assignment_hash": assignment["assignment_hash"],
        "dataset_hash": opportunity.get("index_hash"),
        "opportunity_receipt_hash": canonical_hash(opportunity),
        "snapshot_hash": snapshot.get("snapshot_hash"),
        "compressor_identity_hash": contract["compressor_identity_hash"],
        "actor_identity": contract["actor_identity"],
        "scoring_hash": contract["scoring_hash"],
        "arms": contract["arms"],
        "required_sources": contract["required_sources"],
        "coverage_floor": contract["coverage_floor"],
        "minimum_opportunity_count": contract["minimum_opportunity_count"],
        "partition": contract["partition"],
        "registration_status": "REGISTERED_NOT_AUTHORIZED",
        "claim_authorized": False,
        "execution_authority": "ABSENT",
    }
    if not protocol["dataset_hash"] or not protocol["snapshot_hash"]:
        raise ProtocolError("source receipt hashes are required")
    result = {"schema_version": PROTOCOL_SCHEMA, "protocol": protocol, "execution_authority": "ABSENT"}
    result["protocol_hash"] = canonical_hash(result)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result


def _load_json(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProtocolError("protocol input is unreadable") from exc
    if not isinstance(value, dict):
        raise ProtocolError("protocol input is not an object")
    return value


def _load_hashed_json(path: str | Path, hash_field: str) -> dict[str, Any]:
    value = _load_json(path)
    payload = dict(value)
    claimed = payload.pop(hash_field, None)
    if not claimed or claimed != canonical_hash(payload):
        raise ProtocolError(f"{hash_field} does not match its contents")
    return value
