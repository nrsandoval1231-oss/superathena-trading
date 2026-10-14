import json

import pytest

from athena_trading.aat_v1 import AATValidationError
from athena_trading.aat_v1.opportunities import compile_training_opportunities
from athena_trading.aat_v1.outcomes import evaluate_training_outcomes
from test_aat_v1_opportunities import _multi_session_source


def _protocol(tmp_path):
    path = tmp_path / "protocol.json"
    path.write_text(json.dumps({
        "schema_version": "athena-aat-v1-registered-protocol-v1",
        "execution_authority": "ABSENT", "protocol_hash": "p" * 64,
        "protocol": {"dataset_hash": "d" * 64, "assignment_hash": "a" * 64,
                     "actor": {"model_id": "gpt-5.6-terra"}},
    }), encoding="utf-8")
    return path


def test_evaluates_outcome_separately_from_actor_features(tmp_path):
    source_receipt, source_rows = _multi_session_source(tmp_path)
    opportunities = tmp_path / "opportunities.jsonl"
    opportunity_receipt = tmp_path / "opportunities.json"
    compile_training_opportunities(
        source_receipt, source_rows, opportunities, opportunity_receipt,
        maximum_opportunities=1, require_atr14=True,
    )
    protocol = _protocol(tmp_path)
    output_rows, output_receipt = tmp_path / "outcomes.jsonl", tmp_path / "outcomes.json"
    receipt = evaluate_training_outcomes(
        source_receipt, source_rows, opportunity_receipt, protocol,
        output_rows, output_receipt,
    )
    outcome = json.loads(output_rows.read_text(encoding="utf-8"))
    actor_features = json.loads(opportunities.read_text(encoding="utf-8"))["features"]
    assert receipt["actor_visible"] is False
    assert receipt["adaptation_evidence"] is False
    assert receipt["execution_authority"] == "ABSENT"
    assert outcome["partition"] == "TRAINING"
    assert isinstance(outcome["net_r"], float)
    assert "net_r" not in actor_features


def test_rejects_non_atr_opportunity_projection(tmp_path):
    source_receipt, source_rows = _multi_session_source(tmp_path)
    opportunities = tmp_path / "opportunities.jsonl"
    opportunity_receipt = tmp_path / "opportunities.json"
    compile_training_opportunities(
        source_receipt, source_rows, opportunities, opportunity_receipt,
        maximum_opportunities=1,
    )
    with pytest.raises(AATValidationError, match="ATR14-qualified"):
        evaluate_training_outcomes(
            source_receipt, source_rows, opportunity_receipt, _protocol(tmp_path),
            tmp_path / "outcomes.jsonl", tmp_path / "outcomes.json",
        )


def test_full_session_receipt_binds_scoring_and_is_eligible_evidence(tmp_path):
    source_receipt, source_rows = _multi_session_source(tmp_path)
    opportunities = tmp_path / "opportunities.jsonl"
    opportunity_receipt = tmp_path / "opportunities.json"
    compile_training_opportunities(
        source_receipt, source_rows, opportunities, opportunity_receipt,
        maximum_opportunities=1, require_atr14=True, require_resolved_session=True,
    )
    receipt = evaluate_training_outcomes(
        source_receipt, source_rows, opportunity_receipt, _protocol(tmp_path),
        tmp_path / "full.jsonl", tmp_path / "full.json", full_session=True,
    )
    assert receipt["evaluator"] == "FROZEN_FULL_ORB_M_EVALUATOR_V1"
    assert receipt["adaptation_evidence"] is True
    assert isinstance(receipt["scoring_hash"], str)
