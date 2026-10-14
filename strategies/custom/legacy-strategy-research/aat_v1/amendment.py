"""Local, hash-bound amendment for a TRAINING-only AAT-V1 run."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..athena_adapter.contracts import canonical_hash
from .outcomes import FULL_EVALUATOR_ID, SCORING_SEMANTICS
from .training import AATValidationError, load_registered_protocol


def build_protocol_amendment(
    protocol_path: str | Path, transport_ledger_path: str | Path,
    scoring_config_path: str | Path,
) -> dict[str, Any]:
    registered = load_registered_protocol(protocol_path)
    actor = registered["protocol"]["actor"]
    ledger_path = Path(transport_ledger_path)
    if not ledger_path.is_file():
        raise AATValidationError("transport ledger is missing")
    try:
        scoring = json.loads(Path(scoring_config_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AATValidationError("scoring configuration is unreadable") from exc
    if scoring != SCORING_SEMANTICS:
        raise AATValidationError("scoring configuration does not match evaluator semantics")
    amendment = {
        "schema_version": "aat-v1-training-protocol-amendment-v2",
        "base_protocol_hash": registered["protocol_hash"],
        "minimum_pairs": 300,
        "actor": {
            "model_id": actor["model_id"],
            "model_identity_disposition": "PROVIDER_ALIAS_LOCALLY_BOUND",
            "model_hash": actor["model_hash"],
            "prompt_hash": actor["prompt_hash"],
            "inference_hash": actor["inference_hash"],
            "action_schema_hash": actor["action_schema_hash"],
            "transport_ledger_sha256": hashlib.sha256(ledger_path.read_bytes()).hexdigest(),
        },
        "evaluator": FULL_EVALUATOR_ID,
        "scoring_hash": canonical_hash(scoring),
        "permanent_limitations": ["PROVIDER_MODEL_MUTABILITY"],
        "partition": "TRAINING",
        "contains_sealed_holdout": False,
        "execution_authority": "ABSENT",
    }
    amendment["amendment_hash"] = canonical_hash(amendment)
    return amendment


def load_protocol_amendment(
    path: str | Path, registered: dict[str, Any],
) -> dict[str, Any]:
    try:
        amendment = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AATValidationError("protocol amendment is unreadable") from exc
    if not isinstance(amendment, dict):
        raise AATValidationError("protocol amendment is malformed")
    payload = dict(amendment)
    claimed = payload.pop("amendment_hash", None)
    if claimed != canonical_hash(payload):
        raise AATValidationError("protocol amendment hash mismatch")
    if amendment.get("base_protocol_hash") != registered.get("protocol_hash"):
        raise AATValidationError("protocol amendment base hash mismatch")
    if amendment.get("partition") != "TRAINING" or amendment.get("contains_sealed_holdout") is not False:
        raise AATValidationError("protocol amendment is not TRAINING-only")
    if amendment.get("execution_authority") != "ABSENT":
        raise AATValidationError("execution authority must be ABSENT")
    return amendment
