"""Freeze the AAT-V1 claim boundary without accessing sealed evidence."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..athena_adapter.contracts import canonical_hash
from .training import AATValidationError


def _object(path: str | Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AATValidationError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise AATValidationError(f"{label} is malformed")
    return value


def _verified(value: dict[str, Any], hash_field: str, label: str) -> dict[str, Any]:
    payload = dict(value)
    claimed = payload.pop(hash_field, None)
    if claimed != canonical_hash(payload):
        raise AATValidationError(f"{label} hash mismatch")
    return value


def freeze_claim_contract(
    contract_path: str | Path,
    training_result_path: str | Path,
    training_audit_path: str | Path,
) -> dict[str, Any]:
    """Validate preregistration inputs and emit a no-holdout-access receipt."""
    contract = _object(contract_path, "claim contract")
    required = {
        "schema_version": "aat-v1-final-claim-contract-v1",
        "claim_id": "AAT_V1_MEMORY_IMPROVES_DECISION_QUALITY",
        "decision_arm": "D_ATHENA",
        "primary_comparator": "B_MEMORYLESS",
        "secondary_comparator": "C_NAIVE_MEMORY",
        "required_partition": "SEALED_HOLDOUT",
        "minimum_effect_r": 0.01,
        "maximum_drawdown_regression_r": 0.1,
        "minimum_opportunity_count": 300,
        "minimum_regime_support": 100,
        "required_regimes": ["LONG", "SHORT"],
        "bootstrap_resamples": 4096,
        "confidence_level": 0.95,
        "success_requires_all_comparators": True,
        "single_use_holdout": True,
        "separate_holdout_authorization_required": True,
        "provider_model_limitation": "PROVIDER_MODEL_MUTABILITY",
        "supported_outcome": "CLAIM_SUPPORTED",
        "unsuccessful_outcome": "CLAIM_NOT_SUPPORTED",
        "execution_authority": "ABSENT",
    }
    if any(contract.get(key) != value for key, value in required.items()):
        raise AATValidationError("claim contract drift")
    if not isinstance(contract.get("bootstrap_seed"), int):
        raise AATValidationError("claim contract seed is invalid")

    result = _verified(_object(training_result_path, "training result"), "result_hash", "training result")
    audit = _verified(_object(training_audit_path, "training audit"), "audit_hash", "training audit")
    if (
        result.get("result_hash") != contract.get("four_arm_training_result_hash")
        or audit.get("audit_hash") != contract.get("four_arm_training_audit_hash")
        or audit.get("result_hash") != result.get("result_hash")
        or result.get("status") != "COMPLETE_TRAINING_ONLY"
        or audit.get("status") != "PASS_TRAINING_COMPARISON_INFRASTRUCTURE"
        or audit.get("claim_authorized") is not False
        or result.get("sealed_holdout_consumed") is not False
        or audit.get("sealed_holdout_consumed") is not False
        or result.get("execution_authority") != "ABSENT"
        or audit.get("execution_authority") != "ABSENT"
    ):
        raise AATValidationError("claim contract prerequisite evidence drift")

    receipt = {
        "schema_version": "aat-v1-final-claim-contract-receipt-v1",
        "status": "FROZEN_AWAITING_SEPARATE_HOLDOUT_AUTHORIZATION",
        "contract_hash": canonical_hash(contract),
        "training_result_hash": result["result_hash"],
        "training_audit_hash": audit["audit_hash"],
        "claim_authorized": False,
        "sealed_holdout_accessed": False,
        "execution_authority": "ABSENT",
    }
    receipt["receipt_hash"] = canonical_hash(receipt)
    return receipt
