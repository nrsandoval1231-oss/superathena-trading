import hashlib
import json

from athena_trading.aat_v1.four_arm import (
    audit_four_arm_result,
    execute_four_arm_training,
    plan_four_arm_training,
)
from athena_trading.aat_v1.training import TrainingRow
from athena_trading.athena_adapter.contracts import canonical_hash


def _inventory():
    promoted_eval = {"evaluation_hash": "p" * 64, "mean_effect_r": 0.2}
    rejected_eval = {"evaluation_hash": "r" * 64, "mean_effect_r": 0.1}
    return {
        "inventory_hash": "i" * 64,
        "promotion_rule_hash": "h" * 64,
        "evaluations": [promoted_eval, rejected_eval],
        "lessons": [
            {
                "lesson_id": "promoted", "text": "prefer PASS",
                "token_count": 12, "disposition": "PROMOTED",
                "evidence_hashes": [promoted_eval["evaluation_hash"]],
            },
            {
                "lesson_id": "naive", "text": "prefer reduced",
                "token_count": 12, "disposition": "REJECTED",
                "evidence_hashes": [rejected_eval["evaluation_hash"]],
            },
        ],
    }


def _config():
    return {
        "model_id": "gpt-5.6-terra", "maximum_attempts_per_decision": 2,
        "call_ceiling": 6, "token_ceiling": 100_000,
        "prior_spend_upper_bound_usd": 0.1, "spend_ceiling_usd": 20.0,
        "deterministic_action": "ENTER_STANDARD",
    }


def _pricing():
    return {
        "input_usd_per_million_tokens": 2.0,
        "output_usd_per_million_tokens": 12.0,
    }


def test_plan_has_three_actor_decisions_and_equal_distinct_memory():
    rows = [TrainingRow("opportunity", "candidate", {"direction": "LONG"})]
    plan = plan_four_arm_training(
        config=_config(), rows=rows, actor_identity="actor",
        inventory=_inventory(), pricing=_pricing(),
    )
    assert plan["decision_count"] == 3
    assert plan["maximum_call_count"] == 6
    assert plan["requests"][0]["memory"] == []
    assert plan["requests"][1]["memory"][0]["id"] == "naive"
    assert plan["requests"][2]["memory"][0]["id"] == "promoted"


def test_mocked_execution_scores_four_matched_training_arms(tmp_path):
    rows = [TrainingRow("opportunity", "candidate", {"direction": "LONG"})]
    inventory = _inventory()
    plan = plan_four_arm_training(
        config=_config(), rows=rows, actor_identity="actor",
        inventory=inventory, pricing=_pricing(),
    )
    outcome_rows = tmp_path / "outcomes.jsonl"
    payload = json.dumps({"opportunity_id": "opportunity", "net_r": -1.0}) + "\n"
    outcome_rows.write_text(payload, encoding="utf-8", newline="\n")
    receipt = {
        "rows_path": outcome_rows.name,
        "rows_sha256": hashlib.sha256(payload.encode()).hexdigest(),
    }
    receipt["result_hash"] = canonical_hash(receipt)
    outcome_receipt = tmp_path / "outcomes.json"
    outcome_receipt.write_text(json.dumps(receipt), encoding="utf-8")

    def transport(_payload, _key):
        return {
            "id": "response", "model": "gpt-5.6-terra", "status": "completed",
            "output_text": json.dumps({
                "action": "PASS", "confidence": 0.5, "horizon": "SESSION",
                "invalidation": "registered", "rationale": "mock",
            }),
            "usage": {"input_tokens": 10, "output_tokens": 10},
        }

    result = execute_four_arm_training(
        plan=plan, config=_config(), pricing=_pricing(),
        outcome_receipt_path=outcome_receipt, inventory=inventory,
        ledger_path=tmp_path / "ledger.jsonl", output_path=tmp_path / "result.json",
        api_key="test", transport=transport,
    )
    assert result["status"] == "COMPLETE_TRAINING_ONLY"
    assert result["episode_count"] == 4
    assert result["accepted_actor_decisions"] == 3
    assert result["execution_authority"] == "ABSENT"
    assert result["sealed_holdout_consumed"] is False
    audit = audit_four_arm_result(tmp_path / "result.json", tmp_path / "ledger.jsonl")
    assert audit["status"] == "PASS_TRAINING_COMPARISON_INFRASTRUCTURE"
    assert audit["claim_authorized"] is False
