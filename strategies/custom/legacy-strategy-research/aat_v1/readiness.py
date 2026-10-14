"""Fail-closed readiness audit for an AAT adaptation run."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..athena_adapter.contracts import canonical_hash
from .amendment import load_protocol_amendment
from .lessons import INVENTORY_SCHEMA, load_promotion_rule
from .outcomes import FULL_EVALUATOR_ID
from .receipts import verified_receipt
from .training import AATValidationError, load_registered_protocol, load_training_projection


def audit_adaptation_readiness(
    protocol_path: str | Path,
    opportunity_receipt_path: str | Path,
    outcome_receipt_path: str | Path,
    *,
    protocol_amendment_path: str | Path | None = None,
    transport_ledger_path: str | Path | None = None,
    lesson_inventory_path: str | Path | None = None,
    promotion_rule_path: str | Path | None = None,
    scoring_config_path: str | Path | None = None,
) -> dict[str, Any]:
    """Return reproducible negative knowledge; never run an Actor or holdout."""
    protocol_file = Path(protocol_path)
    registered = load_registered_protocol(protocol_file)
    protocol = registered["protocol"]
    amendment = (
        load_protocol_amendment(protocol_amendment_path, registered)
        if protocol_amendment_path is not None else None
    )
    opportunity_receipt, opportunities = load_training_projection(
        opportunity_receipt_path, protocol_file)
    outcome_receipt = verified_receipt(Path(outcome_receipt_path), hash_field="result_hash")
    if outcome_receipt.get("opportunity_projection_hash") != opportunity_receipt.get("projection_hash"):
        raise AATValidationError("outcome/opportunity projection mismatch")
    if outcome_receipt.get("partition") != "TRAINING" or outcome_receipt.get("contains_sealed_holdout") is not False:
        raise AATValidationError("outcome evidence is not TRAINING-only")
    if outcome_receipt.get("execution_authority") != "ABSENT":
        raise AATValidationError("execution authority must be ABSENT")

    blockers: list[dict[str, Any]] = []

    def block(code: str, observed: Any, required: Any) -> None:
        blockers.append({"code": code, "observed": observed, "required": required})

    effective = amendment if amendment is not None else protocol
    actor = effective.get("actor", {})
    model_id = actor.get("model_id") if isinstance(actor, dict) else None
    disposition = actor.get("model_identity_disposition") if isinstance(actor, dict) else None
    limitations = effective.get("permanent_limitations", [])
    ledger_hash = None
    if transport_ledger_path is not None:
        ledger_file = Path(transport_ledger_path)
        if ledger_file.is_file():
            ledger_hash = hashlib.sha256(ledger_file.read_bytes()).hexdigest()
    if not (
        model_id == "gpt-5.6-terra"
        and disposition == "PROVIDER_ALIAS_LOCALLY_BOUND"
        and "PROVIDER_MODEL_MUTABILITY" in limitations
        and all(actor.get(key) == protocol["actor"].get(key) for key in (
            "model_hash", "prompt_hash", "inference_hash", "action_schema_hash"
        ))
        and ledger_hash == actor.get("transport_ledger_sha256")
    ):
        block("ACTOR_MODEL_IDENTITY_NOT_LOCALLY_BOUND", disposition, "PROVIDER_ALIAS_LOCALLY_BOUND_WITH_MUTABILITY_LIMITATION")
    minimum_pairs = effective.get("minimum_pairs")
    if not isinstance(minimum_pairs, int) or minimum_pairs < 300:
        block("REGISTERED_MINIMUM_PAIRS_BELOW_FLOOR", minimum_pairs, 300)
    if len(opportunities) < 300:
        block("TRAINING_OPPORTUNITIES_BELOW_FLOOR", len(opportunities), 300)
    if outcome_receipt.get("row_count") != len(opportunities):
        block("OUTCOME_PAIR_COUNT_MISMATCH", outcome_receipt.get("row_count"), len(opportunities))
    if outcome_receipt.get("adaptation_evidence") is not True:
        block("OUTCOME_EVALUATOR_DIAGNOSTIC_ONLY", outcome_receipt.get("adaptation_evidence"), True)
    evaluator = outcome_receipt.get("evaluator")
    if evaluator != FULL_EVALUATOR_ID or evaluator != effective.get("evaluator"):
        block("FULL_SESSION_REENTRY_AND_DETERIORATION_ABSENT", evaluator, FULL_EVALUATOR_ID)
    if outcome_receipt.get("scoring_hash") != effective.get("scoring_hash"):
        block("SCORING_SEMANTICS_NOT_BOUND", outcome_receipt.get("scoring_hash"), effective.get("scoring_hash"))

    lessons = None
    if lesson_inventory_path is not None:
        lesson_file = Path(lesson_inventory_path)
        if lesson_file.is_file():
            try:
                lessons = json.loads(lesson_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise AATValidationError("lesson inventory is unreadable") from exc
    if not isinstance(lessons, dict):
        block("TRAINING_LESSON_INVENTORY_ABSENT", None, "HASH_BOUND_TRAINING_INVENTORY")
    else:
        payload = dict(lessons)
        claimed = payload.pop("inventory_hash", None)
        if claimed != canonical_hash(payload):
            raise AATValidationError("lesson inventory hash mismatch")
        if lessons.get("source_outcome_result_hash") != outcome_receipt.get("result_hash"):
            raise AATValidationError("lesson inventory source mismatch")
        if lessons.get("partition") != "TRAINING" or lessons.get("contains_sealed_holdout") is not False:
            raise AATValidationError("lesson inventory is not TRAINING-only")
        if lessons.get("execution_authority") != "ABSENT" or not isinstance(lessons.get("lessons"), list):
            raise AATValidationError("lesson inventory authority or rows are malformed")
        if lessons.get("schema_version") == INVENTORY_SCHEMA:
            if promotion_rule_path is None or scoring_config_path is None:
                raise AATValidationError("lesson rule and scoring bindings are required")
            rule = load_promotion_rule(promotion_rule_path)
            try:
                scoring = json.loads(Path(scoring_config_path).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise AATValidationError("lesson scoring configuration is unreadable") from exc
            if lessons.get("promotion_rule_hash") != canonical_hash(rule):
                raise AATValidationError("lesson promotion rule hash mismatch")
            if lessons.get("scoring_hash") != canonical_hash(scoring):
                raise AATValidationError("lesson scoring hash mismatch")
            promoted = [
                row for row in lessons["lessons"]
                if isinstance(row, dict) and row.get("disposition") == "PROMOTED"
            ]
            if len(promoted) > rule["maximum_promoted_lessons"]:
                raise AATValidationError("lesson promotion count exceeds registered maximum")

    report = {
        "schema_version": "aat-v1-adaptation-readiness-v1",
        "status": "READY_TRAINING_ONLY_WITH_PROVIDER_MODEL_MUTABILITY" if not blockers else "BLOCKED_NEGATIVE_KNOWLEDGE",
        "protocol_hash": registered["protocol_hash"],
        "protocol_amendment_hash": amendment.get("amendment_hash") if amendment else None,
        "opportunity_projection_hash": opportunity_receipt["projection_hash"],
        "outcome_result_hash": outcome_receipt["result_hash"],
        "lesson_inventory_hash": lessons.get("inventory_hash") if isinstance(lessons, dict) else None,
        "promotion_rule_hash": lessons.get("promotion_rule_hash") if isinstance(lessons, dict) else None,
        "lesson_scoring_hash": lessons.get("scoring_hash") if isinstance(lessons, dict) else None,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "permanent_limitations": limitations if amendment else [],
        "promoted_lesson_count": sum(
            row.get("disposition") == "PROMOTED" for row in lessons.get("lessons", [])
        ) if isinstance(lessons, dict) else None,
        "sealed_holdout_consumed": False,
        "actor_called": False,
        "execution_authority": "ABSENT",
    }
    report["report_hash"] = canonical_hash(report)
    return report
