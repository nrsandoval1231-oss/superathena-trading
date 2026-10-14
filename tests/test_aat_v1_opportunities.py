import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from athena_trading.aat_v1 import (
    OpportunityCompileError,
    compile_holdout_opportunities,
    compile_training_opportunities,
)


def _source(tmp_path, *, breakout=True, sealed=False):
    rows = tmp_path / "training.jsonl"
    start = datetime(2026, 2, 2, 14, 30, tzinfo=UTC)
    payload = []
    for minute in range(17):
        close = 10.5 if breakout and minute == 16 else 10.0
        payload.append({
            "symbol": "ABC", "event_at": (start + timedelta(minutes=minute)).isoformat(),
            "available_at": (start + timedelta(minutes=minute + 1)).isoformat(),
            "open": 10.0, "high": max(10.1, close), "low": 9.9, "close": close,
            "volume": 100 + minute, "adjusted": False,
        })
    rows.write_text("".join(json.dumps(row) + "\n" for row in payload), encoding="utf-8")
    receipt = tmp_path / "training-projection.json"
    receipt.write_text(json.dumps({
        "schema_version": "athena-aat-v1-training-projection-v1",
        "capability": "TRAINING_ONLY", "contains_sealed_holdout": sealed,
        "execution_authority": "ABSENT", "dataset_hash": "d" * 64,
        "assignment_hash": "a" * 64, "protocol_hash": "p" * 64,
        "projection_hash": "x" * 64,
        "training_row_count": len(payload),
        "training_rows_sha256": hashlib.sha256(rows.read_bytes()).hexdigest(),
    }), encoding="utf-8")
    return receipt, rows


def _multi_session_source(tmp_path):
    rows = tmp_path / "training-history.jsonl"
    payload = []
    start = datetime(2026, 2, 2, 14, 30, tzinfo=UTC)
    for session_index in range(16):
        session_start = start + timedelta(days=session_index)
        for minute in range(390):
            close = 10.5 if session_index == 15 and minute == 16 else 10.0
            payload.append({
                "symbol": "ABC", "event_at": (session_start + timedelta(minutes=minute)).isoformat(),
                "available_at": (session_start + timedelta(minutes=minute + 1)).isoformat(),
                "open": 10.0, "high": max(10.1, close), "low": 9.9, "close": close,
                "volume": 100, "adjusted": False,
            })
    rows.write_text("".join(json.dumps(row) + "\n" for row in payload), encoding="utf-8")
    receipt = tmp_path / "history-receipt.json"
    receipt.write_text(json.dumps({
        "schema_version": "athena-aat-v1-training-projection-v1", "capability": "TRAINING_ONLY",
        "contains_sealed_holdout": False, "execution_authority": "ABSENT",
        "dataset_hash": "d" * 64, "assignment_hash": "a" * 64,
        "protocol_hash": "p" * 64, "projection_hash": "x" * 64,
        "training_row_count": len(payload), "training_rows_sha256": hashlib.sha256(rows.read_bytes()).hexdigest(),
    }), encoding="utf-8")
    return receipt, rows


def test_compiles_first_close_breakout_without_outcome_or_symbol(tmp_path):
    receipt, rows = _source(tmp_path)
    output_rows = tmp_path / "opportunities.jsonl"
    output_receipt = tmp_path / "opportunities.json"
    result = compile_training_opportunities(
        receipt, rows, output_rows, output_receipt, maximum_opportunities=10)
    opportunity = json.loads(output_rows.read_text(encoding="utf-8"))
    assert result["row_count"] == 1
    assert result["contains_outcomes"] is False
    assert result["execution_authority"] == "ABSENT"
    assert opportunity["features"]["direction"] == "LONG"
    assert opportunity["features"]["signal_minute"] == 16
    assert "symbol" not in json.dumps(opportunity).lower()
    assert "outcome" not in json.dumps(opportunity).lower()
    assert "available_at" not in json.dumps(opportunity).lower()


def test_rejects_source_that_does_not_deny_sealed_content(tmp_path):
    receipt, rows = _source(tmp_path, sealed=True)
    with pytest.raises(OpportunityCompileError, match="sealed holdout"):
        compile_training_opportunities(
            receipt, rows, tmp_path / "out.jsonl", tmp_path / "out.json",
            maximum_opportunities=1)


def test_rejects_tampered_source_rows(tmp_path):
    receipt, rows = _source(tmp_path)
    rows.write_text(rows.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")
    with pytest.raises(OpportunityCompileError, match="hash mismatch"):
        compile_training_opportunities(
            receipt, rows, tmp_path / "out.jsonl", tmp_path / "out.json",
            maximum_opportunities=1)


def test_refuses_to_invent_opportunity_without_breakout(tmp_path):
    receipt, rows = _source(tmp_path, breakout=False)
    with pytest.raises(OpportunityCompileError, match="no complete breakout"):
        compile_training_opportunities(
            receipt, rows, tmp_path / "out.jsonl", tmp_path / "out.json",
            maximum_opportunities=1)


def test_rejects_source_row_count_mismatch(tmp_path):
    receipt, rows = _source(tmp_path)
    value = json.loads(receipt.read_text(encoding="utf-8"))
    value["training_row_count"] += 1
    receipt.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(OpportunityCompileError, match="row count mismatch"):
        compile_training_opportunities(
            receipt, rows, tmp_path / "out.jsonl", tmp_path / "out.json",
            maximum_opportunities=1)


def test_atr14_mode_requires_only_complete_prior_sessions(tmp_path):
    receipt, rows = _multi_session_source(tmp_path)
    output_rows = tmp_path / "outcome-ready.jsonl"
    output_receipt = tmp_path / "outcome-ready.json"
    result = compile_training_opportunities(
        receipt, rows, output_rows, output_receipt,
        maximum_opportunities=1, require_atr14=True,
    )
    opportunity = json.loads(output_rows.read_text(encoding="utf-8"))
    assert result["compiler"] == "ORB_M_FIRST_CLOSE_BREAKOUT_V2_ATR14"
    assert result["requires_15_complete_prior_sessions"] is True
    assert opportunity["features"]["atr14"] == pytest.approx(0.2)


def test_resolved_session_mode_requires_atr14(tmp_path):
    receipt, rows = _source(tmp_path)
    with pytest.raises(OpportunityCompileError, match="requires ATR14"):
        compile_training_opportunities(
            receipt, rows, tmp_path / "out.jsonl", tmp_path / "out.json",
            maximum_opportunities=1, require_resolved_session=True,
        )


def test_holdout_compiler_preserves_semantics_but_requires_holdout_capability(tmp_path):
    receipt, rows = _source(tmp_path)
    value = json.loads(receipt.read_text(encoding="utf-8"))
    value.update({
        "schema_version": "athena-aat-v1-sealed-holdout-projection-v1",
        "capability": "ONE_TIME_SEALED_HOLDOUT_EVALUATION",
        "contains_sealed_holdout": True,
        "holdout_row_count": value.pop("training_row_count"),
        "holdout_rows_sha256": value.pop("training_rows_sha256"),
    })
    receipt.write_text(json.dumps(value), encoding="utf-8")
    result = compile_holdout_opportunities(
        receipt, rows, tmp_path / "holdout-opportunities.jsonl",
        tmp_path / "holdout-opportunities.json", maximum_opportunities=1,
    )
    assert result["partition"] == "SEALED_HOLDOUT"
    assert result["contains_sealed_holdout"] is True
    with pytest.raises(OpportunityCompileError, match="holdout paths are forbidden"):
        compile_training_opportunities(
            receipt, rows, tmp_path / "training-out.jsonl", tmp_path / "training-out.json",
            maximum_opportunities=1,
        )
