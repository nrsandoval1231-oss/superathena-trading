"""Cost-bounded, resumable four-arm AAT-V1 TRAINING comparison."""
from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from ..athena_adapter.contracts import canonical_hash
from .actor_canary import (
    INFERENCE,
    build_actor_packet,
    build_actor_payload,
    load_pricing,
    validate_actor_identity,
    _validate_decision,
)
from .providers import OPENAI
from .readiness import audit_adaptation_readiness
from .receipts import verified_receipt
from .training import AATValidationError, load_registered_protocol, load_training_projection

ARMS = ("A_DETERMINISTIC", "B_MEMORYLESS", "C_NAIVE_MEMORY", "D_ATHENA")


def _load_object(path: str | Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AATValidationError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise AATValidationError(f"{label} is malformed")
    return value


def _memories(inventory: Mapping[str, Any]) -> dict[str, list[dict[str, str]]]:
    lessons = inventory.get("lessons")
    if not isinstance(lessons, list):
        raise AATValidationError("lesson inventory rows are malformed")
    promoted = [row for row in lessons if row.get("disposition") == "PROMOTED"]
    rejected = [row for row in lessons if row.get("disposition") == "REJECTED"]
    if len(promoted) != 1 or not rejected:
        raise AATValidationError("four-arm memory requires one promoted and one rejected lesson")
    naive = max(
        rejected,
        key=lambda row: next(
            item["mean_effect_r"]
            for item in inventory["evaluations"]
            if item["evaluation_hash"] in row["evidence_hashes"]
        ),
    )

    def project(row: Mapping[str, Any]) -> dict[str, str]:
        return {"id": str(row["lesson_id"]), "text": str(row["text"])}

    if promoted[0].get("token_count") != naive.get("token_count"):
        raise AATValidationError("C/D memory token parity violated")
    return {
        "B_MEMORYLESS": [],
        "C_NAIVE_MEMORY": [project(naive)],
        "D_ATHENA": [project(promoted[0])],
    }


def _requests(rows, *, model_id: str, actor_identity: str, memories):
    return [
        {
            "opportunity_id": row.opportunity_id,
            "arm": arm,
            "memory": memories[arm],
            "payload": build_actor_payload(
                model_id,
                build_actor_packet(row, actor_identity, memories[arm]),
            ),
        }
        for row in rows
        for arm in ARMS[1:]
    ]


def plan_four_arm_training(
    *, config: Mapping[str, Any], rows, actor_identity: str,
    inventory: Mapping[str, Any], pricing: Mapping[str, Any],
) -> dict[str, Any]:
    memories = _memories(inventory)
    requests = _requests(
        rows, model_id=config["model_id"], actor_identity=actor_identity,
        memories=memories,
    )
    maximum_calls = len(requests) * config["maximum_attempts_per_decision"]
    input_ceiling = sum(
        len(json.dumps(row["payload"], sort_keys=True, separators=(",", ":")).encode("utf-8"))
        for row in requests
    ) * config["maximum_attempts_per_decision"]
    output_ceiling = maximum_calls * INFERENCE["max_output_tokens"]
    worst_cost = (
        input_ceiling * float(pricing["input_usd_per_million_tokens"])
        + output_ceiling * float(pricing["output_usd_per_million_tokens"])
    ) / 1_000_000
    if maximum_calls > config["call_ceiling"]:
        raise AATValidationError("four-arm call ceiling exceeded")
    if input_ceiling + output_ceiling > config["token_ceiling"]:
        raise AATValidationError("four-arm token ceiling exceeded")
    if config["prior_spend_upper_bound_usd"] + worst_cost > config["spend_ceiling_usd"]:
        raise AATValidationError("four-arm worst-case cost exceeds cumulative spend ceiling")
    return {
        "decision_count": len(requests),
        "maximum_call_count": maximum_calls,
        "input_token_ceiling": input_ceiling,
        "output_token_ceiling": output_ceiling,
        "worst_case_incremental_cost_usd": worst_cost,
        "worst_case_cumulative_cost_usd": config["prior_spend_upper_bound_usd"] + worst_cost,
        "memory_hashes": {
            arm: canonical_hash(memory) for arm, memory in memories.items()
        },
        "requests": requests,
    }


def _live(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    request = Request(
        OPENAI.endpoint, data=json.dumps(payload).encode("utf-8"),
        headers=OPENAI.build_headers(key), method="POST",
    )
    with urlopen(request, timeout=60) as response:  # nosec B310: fixed HTTPS endpoint
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, Mapping):
        raise AATValidationError(f"{OPENAI.provider} response is malformed")
    return value


def _load_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    for index, record in enumerate(records, 1):
        if record.get("sequence") != index or record.get("execution_authority") != "ABSENT":
            raise AATValidationError("four-arm ledger sequence or authority is invalid")
    return records


def execute_four_arm_training(
    *, plan: Mapping[str, Any], config: Mapping[str, Any], pricing: Mapping[str, Any],
    outcome_receipt_path: str | Path, inventory: Mapping[str, Any], ledger_path: str | Path,
    output_path: str | Path, api_key: str,
    transport: Callable[[Mapping[str, Any], str], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    ledger, output = Path(ledger_path), Path(output_path)
    episode_rows_path = output.with_suffix(".episodes.jsonl")
    if output.exists():
        raise AATValidationError("refusing to overwrite four-arm result")
    if episode_rows_path.exists():
        raise AATValidationError("refusing to overwrite four-arm episode evidence")
    outcomes_receipt = verified_receipt(Path(outcome_receipt_path), hash_field="result_hash")
    outcome_rows = Path(outcome_receipt_path).parent / outcomes_receipt["rows_path"]
    outcomes = {
        row["opportunity_id"]: row
        for row in (json.loads(line) for line in outcome_rows.read_text(encoding="utf-8").splitlines())
    }
    records = _load_ledger(ledger)
    completed: dict[tuple[str, str], dict[str, Any]] = {}
    attempts: dict[tuple[str, str], int] = {}
    total_input = total_output = 0
    for record in records:
        key = (record["opportunity_id"], record["arm"])
        attempts[key] = max(attempts.get(key, 0), record["attempt"])
        total_input += record["input_tokens"]
        total_output += record["output_tokens"]
        if record["accepted"]:
            completed[key] = record
    ledger.parent.mkdir(parents=True, exist_ok=True)
    pending = [
        item for item in plan["requests"]
        if (item["opportunity_id"], item["arm"]) not in completed
        and attempts.get((item["opportunity_id"], item["arm"]), 0)
        < config["maximum_attempts_per_decision"]
    ]
    while pending:
        transport_error: Exception | None = None
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {
                executor.submit(transport or _live, item["payload"], api_key): item
                for item in pending
            }
            for future in as_completed(futures):
                item = futures[future]
                key = (item["opportunity_id"], item["arm"])
                attempt = attempts.get(key, 0) + 1
                try:
                    response = future.result()
                except Exception as exc:  # no receipt exists for a failed transport
                    transport_error = transport_error or exc
                    continue
                usage = response.get("usage")
                if not isinstance(usage, Mapping):
                    raise AATValidationError("Actor response lacks usage evidence")
                input_tokens = usage.get("input_tokens")
                output_tokens = usage.get("output_tokens")
                if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
                    raise AATValidationError("Actor usage evidence is malformed")
                total_input += input_tokens
                total_output += output_tokens
                calls = len(records) + 1
                cost = (
                    total_input * float(pricing["input_usd_per_million_tokens"])
                    + total_output * float(pricing["output_usd_per_million_tokens"])
                ) / 1_000_000
                if calls > config["call_ceiling"] or total_input + total_output > config["token_ceiling"]:
                    raise AATValidationError("reported usage exceeds call or token ceiling")
                if config["prior_spend_upper_bound_usd"] + cost > config["spend_ceiling_usd"]:
                    raise AATValidationError("reported usage exceeds cumulative spend ceiling")
                rejection = None
                decision = None
                if response.get("model") != config["model_id"]:
                    rejection = "MODEL_IDENTITY_DRIFT"
                elif response.get("status") != "completed":
                    rejection = "RESPONSE_NOT_COMPLETED"
                else:
                    try:
                        decision = _validate_decision(response)
                    except AATValidationError as exc:
                        rejection = str(exc)
                record = {
                    "sequence": calls,
                    "opportunity_id": item["opportunity_id"],
                    "arm": item["arm"],
                    "attempt": attempt,
                    "memory_hash": canonical_hash(item["memory"]),
                    "request_hash": canonical_hash(item["payload"]),
                    "response_id": response.get("id"),
                    "response_model": response.get("model"),
                    "response_status": response.get("status"),
                    "decision": decision,
                    "decision_hash": canonical_hash(decision) if decision else None,
                    "accepted": rejection is None,
                    "rejection_reason": rejection,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cumulative_incremental_cost_usd": cost,
                    "partition": "TRAINING",
                    "execution_authority": "ABSENT",
                }
                with ledger.open("a", encoding="utf-8", newline="\n") as stream:
                    stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
                records.append(record)
                attempts[key] = attempt
                if record["accepted"]:
                    completed[key] = record
        if transport_error is not None:
            raise transport_error
        pending = [
            item for item in plan["requests"]
            if (item["opportunity_id"], item["arm"]) not in completed
            and attempts.get((item["opportunity_id"], item["arm"]), 0)
            < config["maximum_attempts_per_decision"]
        ]

    multipliers = {
        action: multiplier
        for action, multiplier in {
            "PASS": 0.0, "ENTER_REDUCED": 0.5,
            "ENTER_STANDARD": 1.0, "ENTER_HIGH_CONVICTION": 2.0,
        }.items()
    }
    episodes: list[dict[str, Any]] = []
    for opportunity_id, outcome in outcomes.items():
        net_r = float(outcome["net_r"])
        best = max(multiplier * net_r for multiplier in multipliers.values())
        for arm in ARMS:
            if arm == "A_DETERMINISTIC":
                action = config["deterministic_action"]
                decision_hash = None
                memory_hash = canonical_hash([])
            else:
                record = completed.get((opportunity_id, arm))
                if record is None:
                    continue
                action = record["decision"]["action"]
                decision_hash = record["decision_hash"]
                memory_hash = record["memory_hash"]
            score = multipliers[action] * net_r
            episodes.append({
                "opportunity_id": opportunity_id, "arm": arm,
                "action": action, "decision_hash": decision_hash,
                "memory_hash": memory_hash, "outcome_r": net_r,
                "score_r": score, "regret_r": best - score,
                "partition": "TRAINING", "execution_authority": "ABSENT",
            })
    expected = len(outcomes) * len(ARMS)
    complete = len(episodes) == expected
    episode_payload = "".join(
        json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
        for row in episodes
    )
    episode_rows_path.parent.mkdir(parents=True, exist_ok=True)
    episode_rows_path.write_text(episode_payload, encoding="utf-8", newline="\n")
    arm_summary = {}
    for arm in ARMS:
        arm_rows = [row for row in episodes if row["arm"] == arm]
        arm_summary[arm] = {
            "episode_count": len(arm_rows),
            "mean_score_r": (
                sum(row["score_r"] for row in arm_rows) / len(arm_rows)
                if arm_rows else None
            ),
            "mean_regret_r": (
                sum(row["regret_r"] for row in arm_rows) / len(arm_rows)
                if arm_rows else None
            ),
            "action_counts": {
                action: sum(row["action"] == action for row in arm_rows)
                for action in ("PASS", "ENTER_REDUCED", "ENTER_STANDARD", "ENTER_HIGH_CONVICTION")
            },
        }
    result = {
        "schema_version": "aat-v1-four-arm-training-result-v1",
        "status": "COMPLETE_TRAINING_ONLY" if complete else "BLOCKED_INCOMPLETE_ACTOR_EVIDENCE",
        "opportunity_count": len(outcomes), "episode_count": len(episodes),
        "expected_episode_count": expected,
        "attempt_count": len(records), "accepted_actor_decisions": len(completed),
        "rejected_attempt_count": sum(not row["accepted"] for row in records),
        "input_tokens": total_input, "output_tokens": total_output,
        "incremental_cost_usd": (
            total_input * float(pricing["input_usd_per_million_tokens"])
            + total_output * float(pricing["output_usd_per_million_tokens"])
        ) / 1_000_000,
        "prior_spend_upper_bound_usd": config["prior_spend_upper_bound_usd"],
        "cumulative_cost_upper_bound_usd": (
            config["prior_spend_upper_bound_usd"]
            + (
                total_input * float(pricing["input_usd_per_million_tokens"])
                + total_output * float(pricing["output_usd_per_million_tokens"])
            ) / 1_000_000
        ),
        "config_hash": canonical_hash(config),
        "ledger_sha256": hashlib.sha256(ledger.read_bytes()).hexdigest(),
        "lesson_inventory_hash": inventory["inventory_hash"],
        "promotion_rule_hash": inventory["promotion_rule_hash"],
        "outcome_result_hash": outcomes_receipt["result_hash"],
        "episodes_hash": canonical_hash(episodes),
        "episode_rows_path": episode_rows_path.name,
        "episode_rows_sha256": hashlib.sha256(episode_payload.encode("utf-8")).hexdigest(),
        "arm_summary": arm_summary,
        "sealed_holdout_consumed": False, "execution_authority": "ABSENT",
    }
    result["result_hash"] = canonical_hash(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    return result


def audit_four_arm_result(
    result_path: str | Path, ledger_path: str | Path,
) -> dict[str, Any]:
    """Verify a complete TRAINING comparison without making an adaptation claim."""
    result_file = Path(result_path)
    result = _load_object(result_file, "four-arm result")
    payload = dict(result)
    claimed = payload.pop("result_hash", None)
    if claimed != canonical_hash(payload):
        raise AATValidationError("four-arm result hash mismatch")
    ledger = Path(ledger_path)
    if result.get("ledger_sha256") != hashlib.sha256(ledger.read_bytes()).hexdigest():
        raise AATValidationError("four-arm ledger hash mismatch")
    episode_file = result_file.parent / result.get("episode_rows_path", "")
    if (
        not episode_file.is_file()
        or result.get("episode_rows_sha256") != hashlib.sha256(episode_file.read_bytes()).hexdigest()
    ):
        raise AATValidationError("four-arm episode row hash mismatch")
    episodes = [json.loads(line) for line in episode_file.read_text(encoding="utf-8").splitlines()]
    if canonical_hash(episodes) != result.get("episodes_hash"):
        raise AATValidationError("four-arm episode identity mismatch")
    if result.get("status") != "COMPLETE_TRAINING_ONLY" or len(episodes) != result.get("expected_episode_count"):
        raise AATValidationError("four-arm comparison is incomplete")
    grouped: dict[str, set[str]] = {}
    for row in episodes:
        if row.get("partition") != "TRAINING" or row.get("execution_authority") != "ABSENT":
            raise AATValidationError("four-arm episode escaped TRAINING or authority boundary")
        grouped.setdefault(row["opportunity_id"], set()).add(row["arm"])
    if len(grouped) != result.get("opportunity_count") or any(arms != set(ARMS) for arms in grouped.values()):
        raise AATValidationError("four-arm episode parity mismatch")
    if result.get("sealed_holdout_consumed") is not False or result.get("execution_authority") != "ABSENT":
        raise AATValidationError("four-arm result crossed an authority boundary")
    recomputed_summary = {}
    for arm in ARMS:
        arm_rows = [row for row in episodes if row["arm"] == arm]
        recomputed_summary[arm] = {
            "episode_count": len(arm_rows),
            "mean_score_r": sum(row["score_r"] for row in arm_rows) / len(arm_rows),
            "mean_regret_r": sum(row["regret_r"] for row in arm_rows) / len(arm_rows),
            "action_counts": {
                action: sum(row["action"] == action for row in arm_rows)
                for action in ("PASS", "ENTER_REDUCED", "ENTER_STANDARD", "ENTER_HIGH_CONVICTION")
            },
        }
    if result.get("arm_summary") != recomputed_summary:
        raise AATValidationError("four-arm summary does not match episode evidence")
    d_regret = recomputed_summary["D_ATHENA"]["mean_regret_r"]
    gaps = {
        arm: recomputed_summary[arm]["mean_regret_r"] - d_regret
        for arm in ("B_MEMORYLESS", "C_NAIVE_MEMORY")
    }
    audit = {
        "schema_version": "aat-v1-four-arm-training-audit-v1",
        "status": "PASS_TRAINING_COMPARISON_INFRASTRUCTURE",
        "result_hash": result["result_hash"],
        "episode_count": len(episodes),
        "opportunity_count": len(grouped),
        "d_regret_improvement_r": gaps,
        "claim_authorized": False,
        "sealed_holdout_consumed": False,
        "execution_authority": "ABSENT",
    }
    audit["audit_hash"] = canonical_hash(audit)
    return audit


def prepare_four_arm_training(
    *, config_path: str | Path, protocol_path: str | Path,
    amendment_path: str | Path, transport_ledger_path: str | Path,
    opportunity_receipt_path: str | Path, outcome_receipt_path: str | Path,
    inventory_path: str | Path, promotion_rule_path: str | Path,
    scoring_config_path: str | Path, pricing_path: str | Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    config = _load_object(config_path, "four-arm configuration")
    inventory = _load_object(inventory_path, "lesson inventory")
    required = {
        "schema_version": "aat-v1-four-arm-training-run-v1",
        "model_id": "gpt-5.6-terra", "opportunity_count": 300,
        "deterministic_arm": "A_DETERMINISTIC",
        "deterministic_action": "ENTER_STANDARD",
        "actor_arms": list(ARMS[1:]), "maximum_attempts_per_decision": 2,
        "call_ceiling": 1800, "token_ceiling": 3_500_000,
        "spend_ceiling_usd": 20.0, "sealed_holdout_access": False,
        "execution_authority": "ABSENT",
    }
    if any(config.get(key) != value for key, value in required.items()):
        raise AATValidationError("four-arm configuration drift")
    if config.get("lesson_inventory_hash") != inventory.get("inventory_hash"):
        raise AATValidationError("four-arm lesson inventory drift")
    if config.get("promotion_rule_hash") != inventory.get("promotion_rule_hash"):
        raise AATValidationError("four-arm promotion rule drift")
    if not 0 <= float(config.get("prior_spend_upper_bound_usd", -1)) < 20:
        raise AATValidationError("four-arm prior spend bound is invalid")
    readiness = audit_adaptation_readiness(
        protocol_path, opportunity_receipt_path, outcome_receipt_path,
        protocol_amendment_path=amendment_path,
        transport_ledger_path=transport_ledger_path,
        lesson_inventory_path=inventory_path,
        promotion_rule_path=promotion_rule_path,
        scoring_config_path=scoring_config_path,
    )
    if not readiness["status"].startswith("READY_") or readiness["promoted_lesson_count"] != 1:
        raise AATValidationError("four-arm prerequisite readiness failed")
    registered = load_registered_protocol(protocol_path)
    validate_actor_identity(registered["protocol"]["actor"], model_id=config["model_id"])
    _, rows = load_training_projection(opportunity_receipt_path, protocol_path)
    if len(rows) != config["opportunity_count"]:
        raise AATValidationError("four-arm opportunity count drift")
    pricing = load_pricing(pricing_path, model_id=config["model_id"])
    plan = plan_four_arm_training(
        config=config, rows=rows,
        actor_identity=canonical_hash(registered["protocol"]["actor"]),
        inventory=inventory, pricing=pricing,
    )
    return config, inventory, {**plan, "pricing": pricing}


def authorize_single_recovery(
    *, base_config: Mapping[str, Any], recovery_config_path: str | Path,
    blocked_result_path: str | Path, ledger_path: str | Path,
) -> dict[str, Any]:
    """Authorize one same-inference retry for one durably incomplete decision."""
    recovery = _load_object(recovery_config_path, "four-arm recovery configuration")
    blocked = _load_object(blocked_result_path, "blocked four-arm result")
    blocked_payload = dict(blocked)
    blocked_hash = blocked_payload.pop("result_hash", None)
    if blocked_hash != canonical_hash(blocked_payload):
        raise AATValidationError("blocked four-arm result hash mismatch")
    ledger = Path(ledger_path)
    if (
        recovery.get("schema_version") != "aat-v1-four-arm-training-recovery-v1"
        or recovery.get("base_config_hash") != canonical_hash(base_config)
        or recovery.get("blocked_result_hash") != blocked.get("result_hash")
        or blocked.get("status") != "BLOCKED_INCOMPLETE_ACTOR_EVIDENCE"
        or recovery.get("ledger_sha256") != hashlib.sha256(ledger.read_bytes()).hexdigest()
        or recovery.get("observed_attempt_count") != blocked.get("attempt_count")
        or recovery.get("additional_call_ceiling") != 1
        or recovery.get("same_actor_inference_required") is not True
        or recovery.get("sealed_holdout_access") is not False
        or recovery.get("execution_authority") != "ABSENT"
        or recovery.get("spend_ceiling_usd") != base_config.get("spend_ceiling_usd")
    ):
        raise AATValidationError("four-arm recovery configuration drift")
    records = _load_ledger(ledger)
    target = (recovery.get("failed_opportunity_id"), recovery.get("failed_arm"))
    target_rows = [row for row in records if (row["opportunity_id"], row["arm"]) == target]
    unresolved = {
        (row["opportunity_id"], row["arm"])
        for row in records if not row["accepted"]
    } - {
        (row["opportunity_id"], row["arm"])
        for row in records if row["accepted"]
    }
    if unresolved != {target} or len(target_rows) != 2 or any(row["accepted"] for row in target_rows):
        raise AATValidationError("four-arm recovery target mismatch")
    return {
        **base_config,
        "maximum_attempts_per_decision": 3,
        "call_ceiling": len(records) + 1,
    }
