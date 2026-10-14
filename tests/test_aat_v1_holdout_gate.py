import pytest
from pathlib import Path
import json
import hashlib

from athena_trading.aat_v1.holdout_gate import (
    assert_fresh_holdout,
    audit_holdout_preflight,
    evaluate_claim,
    validate_holdout_authorization,
    load_consumed_holdouts,
)
from athena_trading.athena_adapter.contracts import canonical_hash
from athena_trading.aat_v1.training import AATValidationError


def test_registered_authorization_is_contract_bound_and_unused():
    root = Path(__file__).parents[1]
    authorization = json.loads(
        (root / "configs/aat_v1_sealed_holdout_authorization_v1.json").read_text(encoding="utf-8")
    )
    validate_holdout_authorization(
        authorization,
        contract_hash="269a2e4842ac591d1f89de5b518bd9c2ffc49d682e2e313156df8c75e37fd904",
        prior_receipts=[],
    )


def _contract():
    return {
        "primary_comparator": "B_MEMORYLESS", "secondary_comparator": "C_NAIVE_MEMORY",
        "decision_arm": "D_ATHENA", "required_partition": "SEALED_HOLDOUT",
        "minimum_opportunity_count": 4, "minimum_regime_support": 2,
        "required_regimes": ["LONG", "SHORT"], "minimum_effect_r": 0.01,
        "maximum_drawdown_regression_r": 0.1, "bootstrap_resamples": 1000,
        "confidence_level": 0.95, "bootstrap_seed": 7,
        "supported_outcome": "CLAIM_SUPPORTED", "unsuccessful_outcome": "CLAIM_NOT_SUPPORTED",
    }


def _episodes(effect=0.2):
    rows = []
    for index in range(4):
        regime = "LONG" if index < 2 else "SHORT"
        for arm, regret, score in (
            ("B_MEMORYLESS", effect, 0.0), ("C_NAIVE_MEMORY", effect, 0.0),
            ("D_ATHENA", 0.0, effect),
        ):
            rows.append({
                "opportunity_id": str(index), "arm": arm, "regime": regime,
                "regret_r": regret, "score_r": score, "partition": "SEALED_HOLDOUT",
                "execution_authority": "ABSENT",
            })
    return rows


def test_requires_distinct_single_use_authorization():
    authorization = {
        "schema_version": "aat-v1-sealed-holdout-authorization-v1",
        "contract_hash": "c" * 64, "scope": "ONE_TIME_SEALED_HOLDOUT_EVALUATION",
        "single_use": True, "execution_authority": "ABSENT", "authorization_id": "auth-1",
        "authorized_by": "owner", "authorized_at_utc": "2026-09-05T00:00:00Z",
    }
    validate_holdout_authorization(authorization, contract_hash="c" * 64, prior_receipts=[])
    with pytest.raises(AATValidationError, match="already consumed"):
        validate_holdout_authorization(
            authorization, contract_hash="c" * 64, prior_receipts=[{"authorization_id": "auth-1"}],
        )


def test_claim_requires_both_comparators_to_pass():
    assert evaluate_claim(_contract(), _episodes())["status"] == "CLAIM_SUPPORTED"
    rows = _episodes()
    for row in rows:
        if row["arm"] == "C_NAIVE_MEMORY":
            row["regret_r"] = 0.0
    assert evaluate_claim(_contract(), rows)["status"] == "CLAIM_NOT_SUPPORTED"


def test_claim_evidence_fails_closed_on_missing_pair():
    with pytest.raises(AATValidationError, match="matched-pair evidence is incomplete"):
        evaluate_claim(_contract(), _episodes()[:-1])


def test_preflight_blocks_actor_when_opportunities_are_below_frozen_minimum(tmp_path):
    contract = _contract() | {
        "minimum_opportunity_count": 300,
    }
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    authorization = {
        "schema_version": "aat-v1-sealed-holdout-authorization-v1",
        "contract_hash": canonical_hash(contract), "scope": "ONE_TIME_SEALED_HOLDOUT_EVALUATION",
        "single_use": True, "execution_authority": "ABSENT", "authorization_id": "auth-1",
        "authorized_by": "owner", "authorized_at_utc": "2026-09-04T00:00:00Z",
    }
    authorization_path = tmp_path / "authorization.json"
    authorization_path.write_text(json.dumps(authorization), encoding="utf-8")
    rows = tmp_path / "opportunities.jsonl"
    rows.write_text("{}\n", encoding="utf-8")
    receipt = {
        "partition": "SEALED_HOLDOUT", "contains_sealed_holdout": True,
        "contains_outcomes": False, "execution_authority": "ABSENT",
        "rows_path": rows.name, "rows_sha256": hashlib.sha256(rows.read_bytes()).hexdigest(),
        "row_count": 249,
    }
    receipt["projection_hash"] = canonical_hash(receipt)
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    result = audit_holdout_preflight(contract_path, authorization_path, receipt_path)
    assert result["status"] == "INVALID_EVIDENCE"
    assert result["actor_called"] is False


def test_tracked_consumption_registry_prevents_v1_reuse():
    root = Path(__file__).parents[1]
    registry = load_consumed_holdouts(root / "configs/aat_consumed_holdouts_v1.json")
    entry = registry["entries"][0]
    assert entry["disposition"] == "INVALID_EVIDENCE"
    with pytest.raises(AATValidationError, match="dataset assignment was already consumed"):
        assert_fresh_holdout(
            registry, authorization_id="new-authorization",
            dataset_hash=entry["dataset_hash"], assignment_hash=entry["assignment_hash"],
        )
    with pytest.raises(AATValidationError, match="authorization was already consumed"):
        assert_fresh_holdout(
            registry, authorization_id=entry["authorization_id"],
            dataset_hash="new-dataset", assignment_hash="new-assignment",
        )
