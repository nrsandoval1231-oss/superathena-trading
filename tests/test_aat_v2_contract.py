import pytest

from athena_trading.aat_v2 import (
    ContractError,
    arm_definitions,
    draw_assignment,
    freeze_claim_contract,
    load_contract,
    write_contract,
)
from athena_trading.exogenous import compressor_identity

ACTOR = {
    "provider": "openai", "model_id": "gpt-5.6-terra",
    "model_hash": "m" * 64, "prompt_hash": "p" * 64,
    "inference_hash": "i" * 64, "action_schema_hash": "s" * 64,
}
COVERAGE = {"news": 0.92, "macro": 1.0, "sentiment": 0.61, "prediction_market": 0.02}
REQUIRED = ("news", "macro")


def _freeze(**overrides):
    kwargs = {
        "assignment_hash": draw_assignment(
            "data/universe/manifest.json", seed=20260908)["assignment_hash"],
        "minimum_opportunity_count": 300,
        "coverage_floor": 0.6,
        "measured_coverage": COVERAGE,
        "required_sources": REQUIRED,
        "compressor_identity_hash": compressor_identity()["identity_hash"],
        "actor_identity": ACTOR,
        "arms": arm_definitions(
            deliberation_turns=4, per_turn_output_tokens=64, single_call_output_tokens=256),
        "scoring_hash": "c" * 64,
    }
    kwargs.update(overrides)
    return freeze_claim_contract(**kwargs)


def test_a_well_formed_contract_freezes():
    contract = _freeze()
    assert contract["minimum_opportunity_count"] == 300
    assert contract["claim_authorized"] is False
    assert contract["execution_authority"] == "ABSENT"
    assert contract["contract_hash"]


def test_a_contract_cannot_be_frozen_against_intended_coverage():
    """Coverage decides whether the comparison has power; it must be measured."""
    with pytest.raises(ContractError, match="measured coverage is required"):
        _freeze(measured_coverage={})


def test_a_required_source_with_no_measurement_blocks_the_freeze():
    with pytest.raises(ContractError, match="no measured coverage"):
        _freeze(required_sources=("news", "fundamentals"))


def test_thin_coverage_on_a_required_source_blocks_the_freeze():
    with pytest.raises(ContractError, match="lack power"):
        _freeze(measured_coverage={**COVERAGE, "news": 0.10})


def test_a_sparse_tier_three_source_does_not_block_a_run():
    """Polymarket is expected to be sparse; it must not be able to veto the experiment."""
    contract = _freeze()
    assert contract["measured_coverage"]["prediction_market"] == 0.02


def test_the_three_hundred_pair_floor_is_not_negotiable_downward():
    with pytest.raises(ContractError, match="at least 300"):
        _freeze(minimum_opportunity_count=249)


def test_an_out_of_range_coverage_floor_is_refused():
    for floor in (0.0, -0.1, 1.5):
        with pytest.raises(ContractError, match="coverage_floor"):
            _freeze(coverage_floor=floor)


def test_a_contract_without_a_bound_actor_identity_is_refused():
    with pytest.raises(ContractError, match="actor identity"):
        _freeze(actor_identity={"model_hash": "m" * 64})


def test_a_contaminated_arm_definition_cannot_be_frozen():
    arms = arm_definitions(
        deliberation_turns=2, per_turn_output_tokens=64, single_call_output_tokens=256)
    arms["exogenous_arms"].append("A_DETERMINISTIC")
    with pytest.raises(Exception, match="control arm"):
        _freeze(arms=arms)


def test_a_missing_assignment_hash_is_refused():
    with pytest.raises(ContractError, match="assignment_hash"):
        _freeze(assignment_hash="  ")


def test_a_frozen_contract_round_trips_and_refuses_overwrite(tmp_path):
    contract = _freeze()
    path = tmp_path / "contract.json"
    write_contract(contract, path)
    assert load_contract(path)["contract_hash"] == contract["contract_hash"]
    with pytest.raises(ContractError, match="refusing to overwrite"):
        write_contract(contract, path)


def test_editing_a_frozen_contract_in_place_is_detected(tmp_path):
    import json
    contract = _freeze()
    path = tmp_path / "contract.json"
    write_contract(contract, path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["minimum_opportunity_count"] = 249
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ContractError, match="drift"):
        load_contract(path)
