import ast
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from athena_trading.exogenous import (
    ExogenousRecord,
    SnapshotError,
    build_snapshot,
    compress_opportunity,
    coverage_rates,
    feature_keys,
    load_opportunity_index,
    write_record_store,
)

DECISION = datetime(2026, 2, 3, 14, 45, tzinfo=UTC)
PRIOR_CLOSE = datetime(2026, 2, 2, 21, 0, tzinfo=UTC)


def _record(source, symbol, minutes_before, payload=None):
    available = DECISION - timedelta(minutes=minutes_before)
    return ExogenousRecord(
        source=source, symbol=symbol, event_at=available - timedelta(minutes=5),
        available_at=available,
        payload=payload or {"external_id": f"{source}-{symbol}-{minutes_before}"},
    )


def _index(tmp_path, rows):
    path = tmp_path / "opportunities.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def _opportunity(identifier="op-1", symbol="ABC"):
    return {
        "opportunity_id": identifier, "symbol": symbol,
        "decision_at": DECISION.isoformat(), "prior_close_at": PRIOR_CLOSE.isoformat(),
    }


def _build(tmp_path, records, opportunities):
    store_receipt = tmp_path / "store-receipt.json"
    write_record_store(records, tmp_path / "store.jsonl", store_receipt)
    return build_snapshot(
        _index(tmp_path, opportunities), store_receipt,
        tmp_path / "snapshot.jsonl", tmp_path / "snapshot-receipt.json",
    )


def test_snapshot_emits_one_row_per_opportunity(tmp_path):
    receipt = _build(
        tmp_path,
        [_record("news", "ABC", 30), _record("news", "XYZ", 30)],
        [_opportunity("op-1", "ABC"), _opportunity("op-2", "XYZ")],
    )
    assert receipt["row_count"] == 2
    assert receipt["feature_keys"] == list(feature_keys())
    assert receipt["execution_authority"] == "ABSENT"
    assert receipt["contains_outcomes"] is False
    rows = [
        json.loads(line)
        for line in (tmp_path / "snapshot.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [row["opportunity_id"] for row in rows] == ["op-1", "op-2"]


def test_a_symbol_never_sees_another_symbols_evidence(tmp_path):
    records = [_record("news", "XYZ", 30), _record("news", "XYZ", 60)]
    row = compress_opportunity(records, {
        "opportunity_id": "op-1", "symbol": "ABC",
        "decision_at": DECISION, "prior_close_at": PRIOR_CLOSE,
    })
    assert row["visible_record_count"] == 0
    assert row["features"]["news_present"] is False


def test_market_wide_evidence_reaches_every_symbol(tmp_path):
    macro = _record("macro", None, 75, {"category": "inflation", "external_id": "m1"})
    row = compress_opportunity([macro], {
        "opportunity_id": "op-1", "symbol": "ABC",
        "decision_at": DECISION, "prior_close_at": PRIOR_CLOSE,
    })
    assert row["features"]["macro_present"] is True


def test_evidence_published_after_the_decision_is_invisible(tmp_path):
    late = _record("news", "ABC", -5)  # five minutes after the decision
    row = compress_opportunity([late], {
        "opportunity_id": "op-1", "symbol": "ABC",
        "decision_at": DECISION, "prior_close_at": PRIOR_CLOSE,
    })
    assert row["visible_record_count"] == 0


def test_coverage_rates_are_reported_per_source(tmp_path):
    receipt = _build(
        tmp_path,
        [_record("news", "ABC", 30)],
        [_opportunity("op-1", "ABC"), _opportunity("op-2", "XYZ")],
    )
    assert receipt["coverage_rates"]["news"] == 0.5
    assert receipt["coverage_rates"]["sentiment"] == 0.0


def test_coverage_rates_handle_an_empty_snapshot():
    assert coverage_rates([]) == {}


def test_snapshot_names_its_inputs(tmp_path):
    receipt = _build(tmp_path, [_record("news", "ABC", 30)], [_opportunity()])
    store = json.loads((tmp_path / "store-receipt.json").read_text(encoding="utf-8"))
    assert receipt["record_store_hash"] == store["store_hash"]
    assert receipt["compressor_version"] == "athena-exogenous-compressors-v1"


def test_snapshot_refuses_to_overwrite(tmp_path):
    _build(tmp_path, [_record("news", "ABC", 30)], [_opportunity()])
    with pytest.raises(SnapshotError):
        build_snapshot(
            _index(tmp_path, [_opportunity()]), tmp_path / "store-receipt.json",
            tmp_path / "snapshot.jsonl", tmp_path / "snapshot-receipt.json",
        )


def test_duplicate_opportunity_ids_are_rejected(tmp_path):
    with pytest.raises(SnapshotError):
        load_opportunity_index(_index(tmp_path, [_opportunity(), _opportunity()]))


def test_naive_decision_time_is_rejected(tmp_path):
    row = _opportunity()
    row["decision_at"] = "2026-02-03T09:45:00"
    with pytest.raises(SnapshotError):
        load_opportunity_index(_index(tmp_path, [row]))


def test_empty_index_is_rejected(tmp_path):
    with pytest.raises(SnapshotError):
        load_opportunity_index(_index(tmp_path, []))


def test_exogenous_package_does_not_depend_on_the_strategy_or_the_experiment():
    """The deterministic strategy must stay runnable with this package deleted."""
    forbidden = {"orb_m", "aat_v1"}
    for path in Path("src/athena_trading/exogenous").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not forbidden & set(node.module.split(".")), f"{path.name} imports {node.module}"
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert not forbidden & set(alias.name.split(".")), f"{path.name} imports {alias.name}"
