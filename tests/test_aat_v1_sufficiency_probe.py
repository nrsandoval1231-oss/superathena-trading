import hashlib
import inspect
import json

import pytest

from athena_trading.aat_v1 import (
    AATValidationError,
    count_prior_probes,
    probe_holdout_sufficiency,
)
from athena_trading.athena_adapter.contracts import canonical_hash

ASSIGNMENT = "a" * 64


def _contract(tmp_path, minimum=300):
    path = tmp_path / "contract.json"
    path.write_text(json.dumps({
        "schema_version": "aat-v1-final-claim-contract-v1",
        "minimum_opportunity_count": minimum,
    }), encoding="utf-8")
    return path


def _receipt(tmp_path, *, count, partition="CANDIDATE_HOLDOUT", name="candidate"):
    rows = tmp_path / f"{name}.jsonl"
    rows.write_text("".join(json.dumps({"opportunity_id": f"op-{i}"}) + "\n" for i in range(count)),
                    encoding="utf-8")
    payload = {
        "partition": partition,
        "contains_sealed_holdout": True,
        "contains_outcomes": False,
        "execution_authority": "ABSENT",
        "rows_path": rows.name,
        "rows_sha256": hashlib.sha256(rows.read_bytes()).hexdigest(),
        "row_count": count,
    }
    payload["projection_hash"] = canonical_hash(payload)
    path = tmp_path / f"{name}-receipt.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_sufficient_dataset_clears(tmp_path):
    result = probe_holdout_sufficiency(
        _contract(tmp_path), _receipt(tmp_path, count=300), assignment_hash=ASSIGNMENT
    )
    assert result["status"] == "SUFFICIENT"
    assert result["qualified_opportunity_count"] == 300


def test_the_v1_shortfall_is_caught_without_spending_an_authorization(tmp_path):
    """249 of 300 -- the exact shortfall that burned the V1 holdout."""
    result = probe_holdout_sufficiency(
        _contract(tmp_path), _receipt(tmp_path, count=249), assignment_hash=ASSIGNMENT
    )
    assert result["status"] == "INSUFFICIENT"
    assert result["sealed_holdout_consumed"] is False
    assert result["actor_called"] is False
    assert result["claim_authorized"] is False


def test_the_probe_structurally_cannot_consume_an_authorization():
    """It takes no authorization argument, which beats remembering not to use one."""
    parameters = set(inspect.signature(probe_holdout_sufficiency).parameters)
    assert not {"authorization", "authorization_path", "authorization_id"} & parameters


def test_the_probe_leaks_no_tuning_channel(tmp_path):
    """A count and a verdict only -- no breakdown, no distribution, no sample."""
    result = probe_holdout_sufficiency(
        _contract(tmp_path), _receipt(tmp_path, count=310), assignment_hash=ASSIGNMENT
    )
    assert set(result) == {
        "schema_version", "status", "contract_hash", "assignment_hash",
        "opportunity_projection_hash", "qualified_opportunity_count",
        "minimum_opportunity_count", "actor_called", "claim_authorized",
        "authorization_consulted", "sealed_holdout_consumed", "execution_authority",
        "result_hash",
    }


def test_result_hash_is_reproducible(tmp_path):
    contract, receipt = _contract(tmp_path), _receipt(tmp_path, count=300)
    first = probe_holdout_sufficiency(contract, receipt, assignment_hash=ASSIGNMENT)
    second = probe_holdout_sufficiency(contract, receipt, assignment_hash=ASSIGNMENT)
    assert first["result_hash"] == second["result_hash"]


def test_a_different_assignment_produces_a_different_result_hash(tmp_path):
    contract, receipt = _contract(tmp_path), _receipt(tmp_path, count=300)
    first = probe_holdout_sufficiency(contract, receipt, assignment_hash=ASSIGNMENT)
    second = probe_holdout_sufficiency(contract, receipt, assignment_hash="b" * 64)
    assert first["result_hash"] != second["result_hash"]


def test_mutated_rows_are_detected(tmp_path):
    receipt = _receipt(tmp_path, count=300)
    (tmp_path / "candidate.jsonl").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(AATValidationError):
        probe_holdout_sufficiency(_contract(tmp_path), receipt, assignment_hash=ASSIGNMENT)


def test_a_receipt_carrying_outcomes_is_refused(tmp_path):
    rows = tmp_path / "leaky.jsonl"
    rows.write_text('{"opportunity_id": "op-0"}\n', encoding="utf-8")
    payload = {
        "partition": "CANDIDATE_HOLDOUT", "contains_sealed_holdout": True,
        "contains_outcomes": True, "execution_authority": "ABSENT",
        "rows_path": rows.name, "rows_sha256": hashlib.sha256(rows.read_bytes()).hexdigest(),
        "row_count": 1,
    }
    payload["projection_hash"] = canonical_hash(payload)
    path = tmp_path / "leaky-receipt.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(AATValidationError):
        probe_holdout_sufficiency(_contract(tmp_path), path, assignment_hash=ASSIGNMENT)


def test_probe_requires_an_assignment_hash(tmp_path):
    with pytest.raises(AATValidationError):
        probe_holdout_sufficiency(
            _contract(tmp_path), _receipt(tmp_path, count=300), assignment_hash="  "
        )


def test_repeat_probing_of_one_assignment_is_visible_in_the_log(tmp_path):
    contract, receipt = _contract(tmp_path), _receipt(tmp_path, count=300)
    log = tmp_path / "probes.jsonl"
    for _ in range(3):
        probe_holdout_sufficiency(contract, receipt, assignment_hash=ASSIGNMENT, probe_log_path=log)
    probe_holdout_sufficiency(contract, receipt, assignment_hash="c" * 64, probe_log_path=log)
    assert count_prior_probes(log, assignment_hash=ASSIGNMENT) == 3
    assert count_prior_probes(log, assignment_hash="c" * 64) == 1


def test_missing_probe_log_counts_as_no_prior_probes(tmp_path):
    assert count_prior_probes(tmp_path / "absent.jsonl", assignment_hash=ASSIGNMENT) == 0


def test_malformed_probe_log_is_refused(tmp_path):
    log = tmp_path / "probes.jsonl"
    log.write_text("not json\n", encoding="utf-8")
    with pytest.raises(AATValidationError):
        count_prior_probes(log, assignment_hash=ASSIGNMENT)
