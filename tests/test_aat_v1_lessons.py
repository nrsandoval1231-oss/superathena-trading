import json

import pytest

from athena_trading.aat_v1 import AATValidationError
from athena_trading.aat_v1.lessons import (
    _finalize_dispositions,
    _lower_bound,
    load_promotion_rule,
)


def _rule():
    return {
        "schema_version": "aat-v1-lesson-promotion-rule-v1",
        "baseline_action": "ENTER_STANDARD",
        "candidate_actions": ["PASS"],
        "minimum_support": 300,
        "minimum_regime_support": 100,
        "minimum_effect_r": 0.01,
        "confidence_level": 0.95,
        "bootstrap_resamples": 1000,
        "bootstrap_seed": 20260904,
        "regime_feature": "direction",
        "required_regimes": ["LONG", "SHORT"],
        "max_drawdown_regression_r": 0.1,
        "maximum_promoted_lessons": 1,
        "revocation_rule": "REVOKE_ON_NEW_TRAINING_LCB_NONPOSITIVE_OR_DRAWNDOWN_REGRESSION",
    }


def test_promotion_rule_is_strict_and_deterministic(tmp_path):
    path = tmp_path / "rule.json"
    path.write_text(json.dumps(_rule()), encoding="utf-8")
    assert load_promotion_rule(path)["minimum_support"] == 300
    first = _lower_bound([0.1, 0.2, 0.3], resamples=1000, confidence=0.95, seed=7)
    second = _lower_bound([0.1, 0.2, 0.3], resamples=1000, confidence=0.95, seed=7)
    assert first == second > 0


def test_promotion_rule_rejects_weakened_support_and_unknown_action(tmp_path):
    value = _rule()
    value["minimum_support"] = 299
    value["candidate_actions"] = ["BUY_EVERYTHING"]
    path = tmp_path / "rule.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(AATValidationError, match="promotion rule is invalid"):
        load_promotion_rule(path)


def test_only_strongest_eligible_candidate_is_promoted():
    rows = [
        {"candidate_action": "PASS", "mean_effect_r": 0.2, "disposition": "ELIGIBLE", "reasons": []},
        {"candidate_action": "ENTER_REDUCED", "mean_effect_r": 0.1, "disposition": "ELIGIBLE", "reasons": []},
        {"candidate_action": "ENTER_HIGH_CONVICTION", "mean_effect_r": -0.1, "disposition": "REJECTED", "reasons": ["EFFECT_BELOW_THRESHOLD"]},
    ]
    _finalize_dispositions(rows)
    assert [row["disposition"] for row in rows] == ["PROMOTED", "REJECTED", "REJECTED"]
    assert rows[1]["reasons"] == ["SUPERSEDED_BY_STRONGER_ELIGIBLE_CANDIDATE"]
