"""Stratified TRAINING subsample pins 7b volume and 14b gold without live GPU."""
import json
import hashlib
from pathlib import Path

import pytest

from athena_trading.aat_v2.assignment import partition_for
from athena_trading.aat_v2.identity import TERRA_PROTOCOL_HASH
from athena_trading.athena_adapter.contracts import canonical_hash
from athena_trading.aat_v2.training_subsample import (
    DEFAULT_SEED,
    FROZEN_ASSIGNMENT_HASH,
    FROZEN_DATASET_HASH,
    GOLD_KIND,
    VOLUME_KIND,
    SubsampleError,
    declared_training_subsample_plan,
    draw_training_subsample,
    load_subsample_receipt,
    load_training_subsample_plan,
    select_opportunities_for_receipt,
    write_subsample_receipt,
    verify_committed_subsample,
    verify_opportunity_index_receipt,
)


def test_frozen_index_receipt_binds_hash_count_and_actual_bytes(tmp_path):
    index = tmp_path / "training.jsonl"
    raw = b'{"opportunity_id":"a","symbol":"AAPL"}\n'
    index.write_bytes(raw)
    receipt = {
        "row_count": 1, "rows_sha256": hashlib.sha256(raw).hexdigest(),
        "contains_outcomes": False, "contains_sealed_holdout": False,
        "execution_authority": "ABSENT",
    }
    receipt["index_hash"] = canonical_hash(receipt)
    path = tmp_path / "index.receipt.json"
    path.write_text(json.dumps(receipt))
    verify_opportunity_index_receipt(index, path, expected_hash=receipt["index_hash"])
    index.write_bytes(raw + b'{"opportunity_id":"b","symbol":"AAPL"}\n')
    with pytest.raises(SubsampleError, match="does not match its frozen receipt"):
        verify_opportunity_index_receipt(index, path, expected_hash=receipt["index_hash"])
    index.write_bytes(raw)
    receipt["row_count"] = 2
    receipt["index_hash"] = canonical_hash({k:v for k,v in receipt.items() if k != "index_hash"})
    path.write_text(json.dumps(receipt))
    with pytest.raises(SubsampleError, match="does not match its frozen receipt"):
        verify_opportunity_index_receipt(index, path, expected_hash=receipt["index_hash"])


def test_self_hashed_subsample_cannot_substitute_ids_or_shorten_target(tmp_path):
    assignment = _assignment()
    plan = load_training_subsample_plan(PLAN)
    rows = _rows(_training_symbols()[:10], n_each=110)
    genuine = draw_training_subsample(
        rows, plan=plan, assignment=assignment,
        parent_dataset_hash=FROZEN_DATASET_HASH,
    )["volume_receipt"]
    verify_committed_subsample(genuine, rows, assignment, plan=plan)
    changed = dict(genuine)
    changed["opportunity_ids"] = list(genuine["opportunity_ids"])
    alternative = next(row["opportunity_id"] for row in rows
                       if row["opportunity_id"] not in changed["opportunity_ids"])
    changed["opportunity_ids"][0] = alternative
    changed["subsample_hash"] = canonical_hash({k:v for k,v in changed.items() if k != "subsample_hash"})
    path = tmp_path / "volume.receipt.json"
    path.write_text(json.dumps(changed))
    accepted = load_subsample_receipt(path)
    with pytest.raises(SubsampleError, match="frozen draw plan"):
        verify_committed_subsample(accepted, rows, assignment, plan=plan)
    changed["opportunity_ids"] = changed["opportunity_ids"][:-1]
    changed["selected_count"] = 999
    changed["subsample_hash"] = canonical_hash({k:v for k,v in changed.items() if k != "subsample_hash"})
    path.write_text(json.dumps(changed))
    with pytest.raises(SubsampleError, match="selected_count must equal target_count"):
        load_subsample_receipt(path)


ROOT = Path(__file__).parents[1]
PLAN = ROOT / "configs/aat_v2_training_subsample_plan_v1.json"
ASSIGNMENT = ROOT / "configs/aat_v2_dataset_assignment_v1.json"
SUBSAMPLE_PLAN_HASH = "914a70f95e1c46a41ace24d9f74ca71f24feef224b007da6f6ec8a6a0f48754f"


def _assignment():
    return json.loads(ASSIGNMENT.read_text(encoding="utf-8"))


def _training_symbols():
    return tuple(_assignment()["training_symbols"])


def _rows(symbols, n_each=8):
    rows = []
    for symbol in symbols:
        for index in range(n_each):
            rows.append({
                "opportunity_id": f"{symbol.lower()}-opp-{index:03d}",
                "symbol": symbol,
                "features": {"opaque": index},
            })
    return rows


def test_committed_subsample_plan_pins_1000_and_100_and_stays_absent():
    loaded = load_training_subsample_plan(PLAN)
    declared = declared_training_subsample_plan()
    assert loaded == declared
    assert loaded["plan_hash"] == SUBSAMPLE_PLAN_HASH
    assert loaded["seed"] == DEFAULT_SEED == 20260916
    assert loaded["volume_count"] == 1000
    assert loaded["gold_count"] == 100
    assert loaded["gold_is_subset_of_volume"] is True
    assert loaded["stratification"] == "symbol"
    assert loaded["parent_dataset_hash"] == FROZEN_DATASET_HASH
    assert loaded["assignment_hash"] == FROZEN_ASSIGNMENT_HASH
    assert loaded["consulted_terra_protocol_hash"] == TERRA_PROTOCOL_HASH
    assert loaded["authorizes_full_16705_plan"] is False
    assert loaded["execution_authority"] == "ABSENT"
    assert loaded["drawn_from_outcomes"] is False


def test_subsample_plan_tamper_is_refused(tmp_path):
    payload = json.loads(PLAN.read_text(encoding="utf-8"))
    payload["volume_count"] = 16705
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SubsampleError, match="plan_hash"):
        load_training_subsample_plan(path)


def test_draw_is_symbol_stratified_reproducible_and_gold_is_a_subset():
    assignment = _assignment()
    symbols = _training_symbols()[:10]
    rows = _rows(symbols, n_each=6)
    plan = declared_training_subsample_plan()
    first = draw_training_subsample(
        rows, plan=plan, assignment=assignment,
        parent_dataset_hash=FROZEN_DATASET_HASH,
        volume_count=20, gold_count=5,
    )
    second = draw_training_subsample(
        rows, plan=plan, assignment=assignment,
        parent_dataset_hash=FROZEN_DATASET_HASH,
        volume_count=20, gold_count=5,
    )
    assert first["volume_receipt"] == second["volume_receipt"]
    volume_ids = {row["opportunity_id"] for row in first["volume_rows"]}
    gold_ids = {row["opportunity_id"] for row in first["gold_rows"]}
    assert len(volume_ids) == 20
    assert len(gold_ids) == 5
    assert gold_ids <= volume_ids
    volume_symbols = {row["symbol"] for row in first["volume_rows"]}
    assert volume_symbols == set(symbols)
    assert first["volume_receipt"]["subsample_kind"] == VOLUME_KIND
    assert first["gold_receipt"]["subsample_kind"] == GOLD_KIND
    assert first["gold_receipt"]["parent_hash"] == first["volume_receipt"]["subsample_hash"]
    assert first["execution_authority"] == "ABSENT"
    assert first["volume_receipt"]["authorizes_full_16705_plan"] is False


def test_a_different_seed_produces_a_different_volume_sample():
    assignment = _assignment()
    rows = _rows(_training_symbols()[:8], n_each=6)
    plan = declared_training_subsample_plan()
    first = draw_training_subsample(
        rows, plan=plan, assignment=assignment,
        parent_dataset_hash=FROZEN_DATASET_HASH,
        volume_count=16, gold_count=4, seed=1,
    )
    second = draw_training_subsample(
        rows, plan=plan, assignment=assignment,
        parent_dataset_hash=FROZEN_DATASET_HASH,
        volume_count=16, gold_count=4, seed=2,
    )
    assert first["volume_receipt"]["subsample_hash"] != second["volume_receipt"]["subsample_hash"]


def test_holdout_symbols_are_refused():
    assignment = _assignment()
    plan = declared_training_subsample_plan()
    rows = [
        {"opportunity_id": "should-not-draw", "symbol": "TSLA", "features": {}},
    ]
    with pytest.raises(SubsampleError, match="holdout"):
        draw_training_subsample(
            rows, plan=plan, assignment=assignment,
            parent_dataset_hash=FROZEN_DATASET_HASH,
            volume_count=1, gold_count=1,
        )


def test_parent_dataset_hash_mismatch_is_refused():
    assignment = _assignment()
    plan = declared_training_subsample_plan()
    rows = _rows(_training_symbols()[:4], n_each=4)
    with pytest.raises(SubsampleError, match="dataset_hash"):
        draw_training_subsample(
            rows, plan=plan, assignment=assignment,
            parent_dataset_hash="not-the-frozen-hash",
            volume_count=4, gold_count=2,
        )


def test_target_larger_than_index_is_refused():
    assignment = _assignment()
    plan = declared_training_subsample_plan()
    rows = _rows(_training_symbols()[:3], n_each=2)
    with pytest.raises(SubsampleError, match="exceeds"):
        draw_training_subsample(
            rows, plan=plan, assignment=assignment,
            parent_dataset_hash=FROZEN_DATASET_HASH,
            volume_count=100, gold_count=10,
        )


def test_select_opportunities_follows_receipt_order_and_limit(tmp_path):
    assignment = _assignment()
    plan = declared_training_subsample_plan()
    rows = _rows(_training_symbols()[:5], n_each=4)
    drawn = draw_training_subsample(
        rows, plan=plan, assignment=assignment,
        parent_dataset_hash=FROZEN_DATASET_HASH,
        volume_count=10, gold_count=3,
    )
    path = tmp_path / "volume.receipt.json"
    write_subsample_receipt(drawn["volume_receipt"], path)
    loaded = load_subsample_receipt(path)
    selected = select_opportunities_for_receipt(rows, loaded, limit=4)
    assert [row["opportunity_id"] for row in selected] == loaded["opportunity_ids"][:4]
    for row in selected:
        assert partition_for(assignment, row["symbol"]) == "TRAINING"


def test_holdout_receipt_path_is_forbidden(tmp_path):
    bad = tmp_path / "sealed_holdout.receipt.json"
    bad.write_text("{}", encoding="utf-8")
    with pytest.raises(SubsampleError, match="holdout"):
        load_subsample_receipt(bad)


def test_universe_training_symbols_are_the_stratification_axis():
    assignment = _assignment()
    training = set(assignment["training_symbols"])
    holdout = set(assignment["holdout_symbols"])
    assert training.isdisjoint(holdout)
    assert assignment["universe_member_count"] == len(training) + len(holdout)
    assert all(partition_for(assignment, symbol) == "TRAINING" for symbol in training)
