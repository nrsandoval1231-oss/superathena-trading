import json

import pytest

from athena_trading.aat_v1.claim_contract import freeze_claim_contract
from athena_trading.aat_v1.training import AATValidationError
from athena_trading.athena_adapter.contracts import canonical_hash


def _write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def _evidence(tmp_path):
    result = {
        "status": "COMPLETE_TRAINING_ONLY", "sealed_holdout_consumed": False,
        "execution_authority": "ABSENT",
    }
    result["result_hash"] = canonical_hash(result)
    audit = {
        "status": "PASS_TRAINING_COMPARISON_INFRASTRUCTURE",
        "result_hash": result["result_hash"], "claim_authorized": False,
        "sealed_holdout_consumed": False, "execution_authority": "ABSENT",
    }
    audit["audit_hash"] = canonical_hash(audit)
    result_path, audit_path = tmp_path / "result.json", tmp_path / "audit.json"
    _write(result_path, result)
    _write(audit_path, audit)
    return result, audit, result_path, audit_path


def _contract(result, audit):
    return {
        "schema_version": "aat-v1-final-claim-contract-v1",
        "claim_id": "AAT_V1_MEMORY_IMPROVES_DECISION_QUALITY",
        "decision_arm": "D_ATHENA", "primary_comparator": "B_MEMORYLESS",
        "secondary_comparator": "C_NAIVE_MEMORY", "required_partition": "SEALED_HOLDOUT",
        "minimum_effect_r": 0.01, "maximum_drawdown_regression_r": 0.1,
        "minimum_opportunity_count": 300, "minimum_regime_support": 100,
        "required_regimes": ["LONG", "SHORT"], "bootstrap_resamples": 4096,
        "bootstrap_seed": 20260905, "confidence_level": 0.95,
        "success_requires_all_comparators": True, "single_use_holdout": True,
        "separate_holdout_authorization_required": True,
        "provider_model_limitation": "PROVIDER_MODEL_MUTABILITY",
        "supported_outcome": "CLAIM_SUPPORTED", "unsuccessful_outcome": "CLAIM_NOT_SUPPORTED",
        "execution_authority": "ABSENT", "protocol_hash": "p" * 64,
        "four_arm_training_result_hash": result["result_hash"],
        "four_arm_training_audit_hash": audit["audit_hash"],
    }


def test_freezes_contract_without_authorizing_claim_or_holdout(tmp_path):
    result, audit, result_path, audit_path = _evidence(tmp_path)
    contract_path = tmp_path / "contract.json"
    _write(contract_path, _contract(result, audit))
    receipt = freeze_claim_contract(contract_path, result_path, audit_path)
    assert receipt["status"] == "FROZEN_AWAITING_SEPARATE_HOLDOUT_AUTHORIZATION"
    assert receipt["claim_authorized"] is False
    assert receipt["sealed_holdout_accessed"] is False
    assert receipt["execution_authority"] == "ABSENT"


def test_rejects_training_audit_that_claims_authority(tmp_path):
    result, audit, result_path, audit_path = _evidence(tmp_path)
    audit["claim_authorized"] = True
    audit["audit_hash"] = canonical_hash({k: v for k, v in audit.items() if k != "audit_hash"})
    _write(audit_path, audit)
    contract_path = tmp_path / "contract.json"
    _write(contract_path, _contract(result, audit))
    with pytest.raises(AATValidationError, match="prerequisite evidence drift"):
        freeze_claim_contract(contract_path, result_path, audit_path)
