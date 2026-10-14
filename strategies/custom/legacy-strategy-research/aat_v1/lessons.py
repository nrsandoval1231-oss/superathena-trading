"""Deterministic TRAINING-only lesson promotion with explicit abstention."""
from __future__ import annotations

import json
import random
from pathlib import Path
from statistics import fmean
from typing import Any

from ..athena_adapter.contracts import canonical_hash
from .outcomes import SCORING_SEMANTICS
from .receipts import verified_receipt
from .training import AATValidationError, load_training_projection

RULE_SCHEMA = "aat-v1-lesson-promotion-rule-v1"
INVENTORY_SCHEMA = "aat-v1-training-lesson-inventory-v2"


def _load_object(path: str | Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AATValidationError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise AATValidationError(f"{label} is malformed")
    return value


def load_promotion_rule(path: str | Path) -> dict[str, Any]:
    rule = _load_object(path, "promotion rule")
    actions = rule.get("candidate_actions")
    regimes = rule.get("required_regimes")
    if (
        rule.get("schema_version") != RULE_SCHEMA
        or rule.get("baseline_action") != "ENTER_STANDARD"
        or not isinstance(actions, list)
        or not actions
        or len(actions) != len(set(actions))
        or "ENTER_STANDARD" in actions
        or not set(actions).issubset(SCORING_SEMANTICS["legal_actions"])
        or rule.get("regime_feature") != "direction"
        or not isinstance(regimes, list)
        or sorted(regimes) != ["LONG", "SHORT"]
        or not isinstance(rule.get("minimum_support"), int)
        or rule["minimum_support"] < 300
        or not isinstance(rule.get("minimum_regime_support"), int)
        or rule["minimum_regime_support"] < 1
        or not isinstance(rule.get("bootstrap_resamples"), int)
        or rule["bootstrap_resamples"] < 1000
        or not isinstance(rule.get("bootstrap_seed"), int)
        or not 0.5 < float(rule.get("confidence_level", 0)) < 1
        or float(rule.get("minimum_effect_r", -1)) < 0
        or float(rule.get("max_drawdown_regression_r", -1)) < 0
        or rule.get("maximum_promoted_lessons") != 1
        or rule.get("revocation_rule")
        != "REVOKE_ON_NEW_TRAINING_LCB_NONPOSITIVE_OR_DRAWNDOWN_REGRESSION"
    ):
        raise AATValidationError("promotion rule is invalid")
    return rule


def _lower_bound(
    values: list[float], *, resamples: int, confidence: float, seed: int,
) -> float:
    if not values:
        raise AATValidationError("cannot calibrate an empty effect sample")
    rng = random.Random(seed)
    size = len(values)
    means = sorted(
        fmean(values[rng.randrange(size)] for _ in range(size))
        for _ in range(resamples)
    )
    index = max(0, int((1.0 - confidence) * resamples) - 1)
    return means[index]


def _max_drawdown(values: list[float]) -> float:
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def _finalize_dispositions(evaluations: list[dict[str, Any]]) -> None:
    """Promote exactly the strongest eligible global action, if one exists."""
    eligible = [row for row in evaluations if row["disposition"] == "ELIGIBLE"]
    winner = (
        max(eligible, key=lambda row: (row["mean_effect_r"], row["candidate_action"]))
        if eligible else None
    )
    for evaluation in evaluations:
        if evaluation is winner:
            evaluation["disposition"] = "PROMOTED"
        elif evaluation["disposition"] == "ELIGIBLE":
            evaluation["disposition"] = "REJECTED"
            evaluation["reasons"].append("SUPERSEDED_BY_STRONGER_ELIGIBLE_CANDIDATE")


def build_lesson_inventory(
    opportunity_receipt_path: str | Path,
    protocol_path: str | Path,
    outcome_receipt_path: str | Path,
    promotion_rule_path: str | Path,
    scoring_config_path: str | Path,
) -> dict[str, Any]:
    """Evaluate frozen global action candidates; never inspect a holdout."""
    opportunity_receipt, opportunities = load_training_projection(
        opportunity_receipt_path, protocol_path
    )
    outcome_path = Path(outcome_receipt_path)
    receipt = verified_receipt(outcome_path, hash_field="result_hash")
    if receipt.get("partition") != "TRAINING" or receipt.get("contains_sealed_holdout") is not False:
        raise AATValidationError("lesson source is not TRAINING-only")
    if receipt.get("adaptation_evidence") is not True:
        raise AATValidationError("lesson source is diagnostic-only")
    if receipt.get("opportunity_projection_hash") != opportunity_receipt.get("projection_hash"):
        raise AATValidationError("lesson opportunity/outcome mismatch")
    scoring = _load_object(scoring_config_path, "scoring configuration")
    if scoring != SCORING_SEMANTICS or canonical_hash(scoring) != receipt.get("scoring_hash"):
        raise AATValidationError("lesson scoring semantics drift")
    rule = load_promotion_rule(promotion_rule_path)
    rows_path = outcome_path.parent / receipt["rows_path"]
    outcomes = [json.loads(line) for line in rows_path.read_text(encoding="utf-8").splitlines()]
    if len(outcomes) != len(opportunities) or len(outcomes) != receipt.get("row_count"):
        raise AATValidationError("lesson evidence count mismatch")
    by_id = {row["opportunity_id"]: row for row in outcomes}
    paired: list[tuple[str, float, str]] = []
    for opportunity in opportunities:
        outcome = by_id.get(opportunity.opportunity_id)
        regime = opportunity.features.get(rule["regime_feature"])
        if not isinstance(outcome, dict) or regime not in rule["required_regimes"]:
            raise AATValidationError("lesson evidence identity or regime mismatch")
        paired.append((opportunity.opportunity_id, float(outcome["net_r"]), str(regime)))

    multipliers = scoring["action_multipliers"]
    baseline = float(multipliers[rule["baseline_action"]])
    evaluations: list[dict[str, Any]] = []
    for candidate_index, action in enumerate(rule["candidate_actions"]):
        delta = float(multipliers[action]) - baseline
        effects = [delta * net_r for _, net_r, _ in paired]
        seed = int(rule["bootstrap_seed"]) + candidate_index * 10_000
        overall_lcb = _lower_bound(
            effects, resamples=rule["bootstrap_resamples"],
            confidence=rule["confidence_level"], seed=seed,
        )
        regimes: dict[str, dict[str, Any]] = {}
        for regime_index, regime in enumerate(rule["required_regimes"]):
            values = [
                effect
                for effect, (_, _, observed) in zip(effects, paired, strict=True)
                if observed == regime
            ]
            regimes[regime] = {
                "support": len(values),
                "mean_effect_r": fmean(values) if values else None,
                "lower_confidence_bound_r": _lower_bound(
                    values, resamples=rule["bootstrap_resamples"],
                    confidence=rule["confidence_level"],
                    seed=seed + regime_index + 1,
                ) if values else None,
            }
        candidate_values = [float(multipliers[action]) * net_r for _, net_r, _ in paired]
        baseline_values = [baseline * net_r for _, net_r, _ in paired]
        drawdown_regression = _max_drawdown(candidate_values) - _max_drawdown(baseline_values)
        reasons: list[str] = []
        if len(effects) < rule["minimum_support"]:
            reasons.append("INSUFFICIENT_TOTAL_SUPPORT")
        if any(value["support"] < rule["minimum_regime_support"] for value in regimes.values()):
            reasons.append("INSUFFICIENT_REGIME_SUPPORT")
        if fmean(effects) < rule["minimum_effect_r"]:
            reasons.append("EFFECT_BELOW_THRESHOLD")
        if overall_lcb <= 0:
            reasons.append("UNCERTAINTY_CROSSES_ZERO")
        if any(
            value["lower_confidence_bound_r"] is None
            or value["lower_confidence_bound_r"] <= 0
            for value in regimes.values()
        ):
            reasons.append("REGIME_CONTRADICTION_OR_UNCERTAINTY")
        if drawdown_regression > rule["max_drawdown_regression_r"]:
            reasons.append("DRAWDOWN_REGRESSION")
        evaluation = {
            "candidate_action": action,
            "baseline_action": rule["baseline_action"],
            "support": len(effects),
            "mean_effect_r": fmean(effects),
            "lower_confidence_bound_r": overall_lcb,
            "regimes": regimes,
            "drawdown_regression_r": drawdown_regression,
            "disposition": "ELIGIBLE" if not reasons else "REJECTED",
            "reasons": reasons,
        }
        evaluations.append(evaluation)

    _finalize_dispositions(evaluations)
    lessons: list[dict[str, Any]] = []
    negative: list[dict[str, Any]] = []
    for evaluation in evaluations:
        evaluation["evaluation_hash"] = canonical_hash(evaluation)
        action = evaluation["candidate_action"]
        lesson = {
            "lesson_id": canonical_hash({"rule": canonical_hash(rule), "action": action}),
            "family": "GLOBAL_ENTRY_ACTION",
            "text": f"Prefer {action} to ENTER_STANDARD for registered ORB-M opportunities.",
            "token_count": 12,
            "evidence_hashes": [receipt["result_hash"], evaluation["evaluation_hash"]],
            "disposition": evaluation["disposition"],
            "partition": "TRAINING",
        }
        lessons.append(lesson)
        if evaluation["reasons"]:
            negative.append({
                "lesson_id": lesson["lesson_id"],
                "reasons": evaluation["reasons"],
            })

    promoted = sum(lesson["disposition"] == "PROMOTED" for lesson in lessons)
    inventory = {
        "schema_version": INVENTORY_SCHEMA,
        "source_outcome_result_hash": receipt["result_hash"],
        "opportunity_projection_hash": opportunity_receipt["projection_hash"],
        "promotion_rule_hash": canonical_hash(rule),
        "scoring_hash": canonical_hash(scoring),
        "disposition": "PROMOTED_LESSONS_AVAILABLE" if promoted else "NO_PROMOTED_LESSONS",
        "lessons": lessons,
        "evaluations": evaluations,
        "negative_knowledge": negative,
        "partition": "TRAINING",
        "contains_sealed_holdout": False,
        "execution_authority": "ABSENT",
    }
    inventory["inventory_hash"] = canonical_hash(inventory)
    return inventory
