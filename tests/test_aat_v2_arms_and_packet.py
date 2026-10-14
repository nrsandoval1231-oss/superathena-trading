import pytest

from athena_trading.aat_v2 import (
    ARMS,
    EXOGENOUS_ARMS,
    ArmError,
    arm_definitions,
    assert_control_arm_never_saw_treatment,
    assert_equal_token_budget,
    assert_treatment_asymmetry,
    build_packet,
    calls_actor,
    ledger_projection,
    receives_exogenous,
)
from athena_trading.exogenous import feature_keys

CONTROL = "A_DETERMINISTIC"
TREATED = "D_ATHENA"
FEATURES = {"opaque": 1}


def _exogenous():
    return {key: 0 for key in feature_keys()}


# --- the treatment asymmetry is the experiment ------------------------------

def test_the_control_arm_receives_no_exogenous_evidence():
    assert receives_exogenous(CONTROL) is False
    assert all(receives_exogenous(arm) for arm in EXOGENOUS_ARMS)
    assert CONTROL not in EXOGENOUS_ARMS


def test_the_control_arm_calls_no_actor_at_all():
    """Arm A is the frozen strategy, not an Actor with features withheld."""
    assert calls_actor(CONTROL) is False


def test_a_packet_cannot_be_built_for_the_control_arm_with_treatment():
    with pytest.raises(ArmError, match="must not receive exogenous"):
        build_packet(
            arm=CONTROL, opportunity_id="op-1", features=FEATURES,
            actor_identity="id", exogenous_features=_exogenous(),
        )


def test_a_treated_arm_refuses_to_run_without_the_treatment():
    """Silently degrading to a V1 packet would produce a null for the wrong reason."""
    with pytest.raises(ArmError, match="requires exogenous"):
        build_packet(arm=TREATED, opportunity_id="op-1", features=FEATURES, actor_identity="id")


def test_partial_exogenous_vectors_are_refused():
    partial = _exogenous()
    partial.pop(feature_keys()[0])
    with pytest.raises(ArmError, match="key drift"):
        build_packet(
            arm=TREATED, opportunity_id="op-1", features=FEATURES,
            actor_identity="id", exogenous_features=partial,
        )


def test_unexpected_exogenous_keys_are_refused():
    extra = _exogenous() | {"smuggled_outcome": 1}
    with pytest.raises(ArmError, match="key drift"):
        build_packet(
            arm=TREATED, opportunity_id="op-1", features=FEATURES,
            actor_identity="id", exogenous_features=extra,
        )


def test_a_memoryless_arm_refuses_memory():
    with pytest.raises(ArmError, match="must not receive memory"):
        build_packet(
            arm="B_MEMORYLESS", opportunity_id="op-1", features=FEATURES,
            actor_identity="id", exogenous_features=_exogenous(),
            memory=[{"id": "l1", "text": "x"}],
        )


def test_a_well_formed_treated_packet_carries_the_vector():
    packet = build_packet(
        arm=TREATED, opportunity_id="op-1", features=FEATURES,
        actor_identity="id", exogenous_features=_exogenous(),
        memory=[{"id": "l1", "text": "x"}],
    )
    assert set(packet["exogenous"]) == set(feature_keys())
    assert packet["candidate_hash"] == "op-1"
    assert packet["schema_version"] == "athena-aat-v2-actor-packet-v1"


def test_unknown_arm_fails_closed():
    with pytest.raises(ArmError):
        receives_exogenous("F_WISHFUL")


# --- equal-budget deliberation ----------------------------------------------

def test_deliberation_may_not_outspend_a_single_call():
    """A win from spending more tokens is not a win from deliberating."""
    with pytest.raises(ArmError, match="unattributable"):
        assert_equal_token_budget(
            deliberation_turns=4, per_turn_output_tokens=256, single_call_output_tokens=256
        )


def test_deliberation_within_the_single_call_budget_is_allowed():
    assert_equal_token_budget(
        deliberation_turns=4, per_turn_output_tokens=64, single_call_output_tokens=256
    )


def test_deliberation_needs_at_least_two_sides():
    with pytest.raises(ArmError):
        assert_equal_token_budget(
            deliberation_turns=1, per_turn_output_tokens=64, single_call_output_tokens=256
        )


def test_arm_definitions_hash_and_carry_the_asymmetry():
    definitions = arm_definitions(
        deliberation_turns=4, per_turn_output_tokens=64, single_call_output_tokens=256
    )
    assert definitions["arms"] == list(ARMS)
    assert CONTROL not in definitions["exogenous_arms"]
    assert_treatment_asymmetry(definitions)


def test_a_contaminated_arm_definition_is_rejected():
    definitions = arm_definitions(
        deliberation_turns=2, per_turn_output_tokens=64, single_call_output_tokens=256
    )
    definitions["exogenous_arms"].append(CONTROL)
    with pytest.raises(ArmError, match="control arm cannot receive"):
        assert_treatment_asymmetry(definitions)


def test_an_empty_treatment_set_is_rejected():
    with pytest.raises(ArmError, match="no mechanism"):
        assert_treatment_asymmetry({"exogenous_arms": [], "actor_arms": []})


# --- post-hoc ledger audit ---------------------------------------------------

def test_ledger_audit_catches_a_contaminated_control_row():
    rows = [{"arm": CONTROL, "exogenous_present": True}]
    with pytest.raises(ArmError, match="control arm"):
        assert_control_arm_never_saw_treatment(rows)


def test_ledger_audit_catches_an_untreated_treatment_row():
    rows = [{"arm": TREATED, "exogenous_present": False}]
    with pytest.raises(ArmError, match="treated arm"):
        assert_control_arm_never_saw_treatment(rows)


def test_ledger_audit_passes_a_clean_run():
    packet = build_packet(
        arm=TREATED, opportunity_id="op-1", features=FEATURES,
        actor_identity="id", exogenous_features=_exogenous(),
    )
    row = ledger_projection(packet, arm=TREATED)
    assert row["exogenous_present"] is True
    assert row["execution_authority"] == "ABSENT"
    assert_control_arm_never_saw_treatment([row, {"arm": CONTROL, "exogenous_present": False}])
