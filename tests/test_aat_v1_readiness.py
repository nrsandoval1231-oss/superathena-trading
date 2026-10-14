import json

import pytest

from athena_trading.aat_v1 import AATValidationError
from athena_trading.aat_v1.opportunities import compile_training_opportunities
from athena_trading.aat_v1.outcomes import SCORING_SEMANTICS, evaluate_training_outcomes
from athena_trading.aat_v1.amendment import build_protocol_amendment
from athena_trading.aat_v1.lessons import build_lesson_inventory
from athena_trading.aat_v1.readiness import audit_adaptation_readiness
from test_aat_v1_opportunities import _multi_session_source


def _evidence(tmp_path):
    source_receipt, source_rows = _multi_session_source(tmp_path)
    opportunities, opportunity_receipt = tmp_path / "opportunities.jsonl", tmp_path / "opportunities.json"
    compile_training_opportunities(
        source_receipt, source_rows, opportunities, opportunity_receipt,
        maximum_opportunities=1, require_atr14=True,
    )
    protocol = tmp_path / "protocol.json"
    protocol.write_text(json.dumps({
        "schema_version": "athena-aat-v1-registered-protocol-v1",
        "execution_authority": "ABSENT", "protocol_hash": "p" * 64,
        "protocol": {
            "dataset_hash": "d" * 64, "assignment_hash": "a" * 64,
            "minimum_pairs": 1, "scoring_hash": "s" * 64,
            "actor": {
                "model_id": "gpt-5.6-terra", "model_hash": "m" * 64,
                "prompt_hash": "q" * 64, "inference_hash": "i" * 64,
                "action_schema_hash": "a" * 64,
            },
        },
    }), encoding="utf-8")
    outcomes, outcome_receipt = tmp_path / "outcomes.jsonl", tmp_path / "outcomes.json"
    evaluate_training_outcomes(
        source_receipt, source_rows, opportunity_receipt, protocol,
        outcomes, outcome_receipt,
    )
    return protocol, opportunity_receipt, outcome_receipt


def _promotion_files(tmp_path):
    scoring = tmp_path / "scoring.json"
    scoring.write_text(json.dumps(SCORING_SEMANTICS), encoding="utf-8")
    rule = tmp_path / "promotion.json"
    rule.write_text(json.dumps({
        "schema_version": "aat-v1-lesson-promotion-rule-v1",
        "baseline_action": "ENTER_STANDARD",
        "candidate_actions": ["PASS", "ENTER_REDUCED", "ENTER_HIGH_CONVICTION"],
        "minimum_support": 300,
        "minimum_regime_support": 1,
        "minimum_effect_r": 0.01,
        "confidence_level": 0.95,
        "bootstrap_resamples": 1000,
        "bootstrap_seed": 7,
        "regime_feature": "direction",
        "required_regimes": ["LONG", "SHORT"],
        "max_drawdown_regression_r": 0.1,
        "maximum_promoted_lessons": 1,
        "revocation_rule": "REVOKE_ON_NEW_TRAINING_LCB_NONPOSITIVE_OR_DRAWNDOWN_REGRESSION",
    }), encoding="utf-8")
    return scoring, rule


def test_current_shape_is_durable_negative_knowledge(tmp_path):
    protocol, opportunities, outcomes = _evidence(tmp_path)
    report = audit_adaptation_readiness(protocol, opportunities, outcomes)
    codes = {blocker["code"] for blocker in report["blockers"]}
    assert report["status"] == "BLOCKED_NEGATIVE_KNOWLEDGE"
    assert report["actor_called"] is False
    assert report["sealed_holdout_consumed"] is False
    assert report["execution_authority"] == "ABSENT"
    assert {
        "ACTOR_MODEL_IDENTITY_NOT_LOCALLY_BOUND",
        "REGISTERED_MINIMUM_PAIRS_BELOW_FLOOR",
        "TRAINING_OPPORTUNITIES_BELOW_FLOOR",
        "OUTCOME_EVALUATOR_DIAGNOSTIC_ONLY",
        "FULL_SESSION_REENTRY_AND_DETERIORATION_ABSENT",
        "SCORING_SEMANTICS_NOT_BOUND",
        "TRAINING_LESSON_INVENTORY_ABSENT",
    }.issubset(codes)


def test_tampered_outcome_receipt_is_rejected(tmp_path):
    protocol, opportunities, outcomes = _evidence(tmp_path)
    value = json.loads(outcomes.read_text(encoding="utf-8"))
    value["row_count"] = 999
    outcomes.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(AATValidationError, match="receipt hash mismatch"):
        audit_adaptation_readiness(protocol, opportunities, outcomes)


def test_local_binding_and_empty_lesson_inventory_are_explicit(tmp_path):
    protocol, opportunities, outcomes = _evidence(tmp_path)
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text('{"response":"bound"}\n', encoding="utf-8")
    scoring, rule = _promotion_files(tmp_path)
    amendment = build_protocol_amendment(protocol, ledger, scoring)
    amendment_path = tmp_path / "amendment.json"
    amendment_path.write_text(json.dumps(amendment), encoding="utf-8")

    # Rebuild the one-row evidence with full-session semantics so the lesson
    # inventory can prove an intentionally empty memory without inventing one.
    full_rows, full_receipt = tmp_path / "full.jsonl", tmp_path / "full.json"
    source_receipt = tmp_path / "history-receipt.json"
    source_rows = tmp_path / "training-history.jsonl"
    evaluate_training_outcomes(
        source_receipt, source_rows, opportunities, protocol,
        full_rows, full_receipt, full_session=True,
    )
    inventory = build_lesson_inventory(
        opportunities, protocol, full_receipt, rule, scoring
    )
    inventory_path = tmp_path / "lessons.json"
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
    report = audit_adaptation_readiness(
        protocol, opportunities, full_receipt,
        protocol_amendment_path=amendment_path,
        transport_ledger_path=ledger,
        lesson_inventory_path=inventory_path,
        promotion_rule_path=rule,
        scoring_config_path=scoring,
    )
    codes = {blocker["code"] for blocker in report["blockers"]}
    assert codes == {"TRAINING_OPPORTUNITIES_BELOW_FLOOR"}
    assert report["permanent_limitations"] == ["PROVIDER_MODEL_MUTABILITY"]
    assert report["promoted_lesson_count"] == 0
    assert report["lesson_inventory_hash"] == inventory["inventory_hash"]
    assert report["promotion_rule_hash"] == inventory["promotion_rule_hash"]
    assert report["lesson_scoring_hash"] == inventory["scoring_hash"]


def test_tampered_protocol_amendment_is_rejected(tmp_path):
    protocol, opportunities, outcomes = _evidence(tmp_path)
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("{}\n", encoding="utf-8")
    scoring, _ = _promotion_files(tmp_path)
    amendment = build_protocol_amendment(protocol, ledger, scoring)
    amendment["minimum_pairs"] = 1
    amendment_path = tmp_path / "amendment.json"
    amendment_path.write_text(json.dumps(amendment), encoding="utf-8")
    with pytest.raises(AATValidationError, match="amendment hash mismatch"):
        audit_adaptation_readiness(
            protocol, opportunities, outcomes,
            protocol_amendment_path=amendment_path,
        )
