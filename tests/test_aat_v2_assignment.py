import json

import pytest

from athena_trading.aat_v2 import (
    AssignmentError,
    assert_partitions_disjoint,
    draw_assignment,
    filter_opportunities,
    load_universe,
    partition_for,
    write_assignment,
)

MANIFEST = "data/universe/manifest.json"


def _manifest(tmp_path, members, manifest_hash="u" * 64):
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"members": members, "manifest_hash": manifest_hash}),
                    encoding="utf-8")
    return path


def test_the_frozen_universe_loads():
    manifest, members = load_universe(MANIFEST)
    assert len(members) == 50
    assert manifest["manifest_hash"]


def test_the_draw_is_reproducible_from_its_seed():
    first = draw_assignment(MANIFEST, seed=20260908)
    second = draw_assignment(MANIFEST, seed=20260908)
    assert first["assignment_hash"] == second["assignment_hash"]


def test_a_different_seed_produces_a_different_split():
    assert (
        draw_assignment(MANIFEST, seed=1)["assignment_hash"]
        != draw_assignment(MANIFEST, seed=2)["assignment_hash"]
    )


def test_no_symbol_straddles_both_partitions():
    assignment = draw_assignment(MANIFEST, seed=20260908)
    assert not set(assignment["training_symbols"]) & set(assignment["holdout_symbols"])
    assert len(assignment["training_symbols"]) + len(assignment["holdout_symbols"]) == 50


def test_the_draw_ignores_manifest_ordering(tmp_path):
    """Members are sorted before shuffling, so listing order cannot steer the split."""
    forward = _manifest(tmp_path / "a", ["AAA", "BBB", "CCC", "DDD"])
    backward = _manifest(tmp_path / "b", ["DDD", "CCC", "BBB", "AAA"])
    assert (
        draw_assignment(forward, seed=5)["assignment_hash"]
        == draw_assignment(backward, seed=5)["assignment_hash"]
    )


def test_the_draw_records_that_it_saw_no_outcomes_or_features():
    assignment = draw_assignment(MANIFEST, seed=20260908)
    assert assignment["drawn_from_outcomes"] is False
    assert assignment["drawn_from_exogenous_features"] is False
    assert assignment["execution_authority"] == "ABSENT"


def test_a_fraction_that_empties_a_partition_is_refused(tmp_path):
    manifest = _manifest(tmp_path, ["AAA", "BBB"])
    with pytest.raises(AssignmentError):
        draw_assignment(manifest, seed=1, holdout_fraction=0.01)
    with pytest.raises(AssignmentError):
        draw_assignment(manifest, seed=1, holdout_fraction=0.99)


def test_out_of_range_fractions_are_refused():
    for fraction in (0.0, 1.0, -0.2, 1.5):
        with pytest.raises(AssignmentError):
            draw_assignment(MANIFEST, seed=1, holdout_fraction=fraction)


def test_a_boolean_seed_is_refused():
    with pytest.raises(AssignmentError):
        draw_assignment(MANIFEST, seed=True)


def test_duplicate_universe_members_are_refused(tmp_path):
    with pytest.raises(AssignmentError):
        load_universe(_manifest(tmp_path, ["AAA", "AAA"]))


def test_partition_lookup_refuses_an_unassigned_symbol():
    assignment = draw_assignment(MANIFEST, seed=20260908)
    known = assignment["training_symbols"][0]
    assert partition_for(assignment, known) == "TRAINING"
    assert partition_for(assignment, assignment["holdout_symbols"][0]) == "SEALED_HOLDOUT"
    with pytest.raises(AssignmentError):
        partition_for(assignment, "NOTREAL")


def test_opportunity_filtering_splits_cleanly():
    assignment = draw_assignment(MANIFEST, seed=20260908)
    training_symbol = assignment["training_symbols"][0]
    holdout_symbol = assignment["holdout_symbols"][0]
    rows = [
        {"opportunity_id": "op-1", "symbol": training_symbol},
        {"opportunity_id": "op-2", "symbol": holdout_symbol},
    ]
    assert filter_opportunities(assignment, rows, partition="TRAINING") == (rows[0],)
    assert filter_opportunities(assignment, rows, partition="SEALED_HOLDOUT") == (rows[1],)


def test_an_opportunity_outside_the_universe_is_an_error_not_a_silent_drop():
    assignment = draw_assignment(MANIFEST, seed=20260908)
    with pytest.raises(AssignmentError):
        filter_opportunities(
            assignment, [{"opportunity_id": "op-1", "symbol": "NOTREAL"}], partition="TRAINING"
        )


def test_a_tampered_assignment_is_detected():
    assignment = draw_assignment(MANIFEST, seed=20260908)
    assignment["training_symbols"].append(assignment["holdout_symbols"][0])
    with pytest.raises(AssignmentError, match="straddle"):
        assert_partitions_disjoint(assignment)


def test_writing_refuses_to_overwrite_and_verifies_its_hash(tmp_path):
    assignment = draw_assignment(MANIFEST, seed=20260908)
    path = tmp_path / "assignment.json"
    write_assignment(assignment, path)
    with pytest.raises(AssignmentError):
        write_assignment(assignment, path)
    edited = draw_assignment(MANIFEST, seed=20260908)
    edited["seed"] = 999
    with pytest.raises(AssignmentError, match="hash"):
        write_assignment(edited, tmp_path / "edited.json")


def test_linked_share_classes_never_split_across_partitions():
    """GOOG and GOOGL are one asset; splitting them would let the holdout memorize."""
    for seed in range(60):
        assignment = draw_assignment(MANIFEST, seed=seed)
        in_holdout = {"GOOG", "GOOGL"} <= set(assignment["holdout_symbols"])
        in_training = {"GOOG", "GOOGL"} <= set(assignment["training_symbols"])
        assert in_holdout or in_training, f"seed {seed} split the linked pair"


def test_a_split_linked_pair_is_detected_after_the_fact():
    from athena_trading.aat_v2 import assert_linked_symbols_share_a_partition
    assignment = draw_assignment(MANIFEST, seed=20260908)
    training = set(assignment["training_symbols"]) | {"GOOG"}
    training.discard("GOOGL")
    tampered = {
        "training_symbols": sorted(training),
        "holdout_symbols": ["GOOGL"],
    }
    with pytest.raises(AssignmentError, match="linked symbols split"):
        assert_linked_symbols_share_a_partition(tampered)


def test_linked_grouping_is_recorded_in_the_assignment():
    assignment = draw_assignment(MANIFEST, seed=20260908)
    assert ["GOOG", "GOOGL"] in assignment["linked_symbol_groups"]


def test_a_universe_without_a_linked_pair_is_unaffected(tmp_path):
    manifest = _manifest(tmp_path, ["AAA", "BBB", "CCC", "DDD"])
    assignment = draw_assignment(manifest, seed=3, holdout_fraction=0.5)
    assert len(assignment["holdout_symbols"]) == 2
