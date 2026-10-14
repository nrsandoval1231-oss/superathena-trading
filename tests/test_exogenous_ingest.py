import json
from datetime import UTC, datetime, timedelta

import pytest

from athena_trading.exogenous import (
    ExogenousRecord,
    IngestError,
    assert_stable_availability,
    load_record_store,
    normalize,
    write_record_store,
)

DECISION = datetime(2026, 2, 3, 14, 45, tzinfo=UTC)


def _record(*, minutes_before=60, external_id="n1", source="news", symbol="ABC"):
    available = DECISION - timedelta(minutes=minutes_before)
    return ExogenousRecord(
        source=source, symbol=symbol, event_at=available - timedelta(minutes=5),
        available_at=available, payload={"external_id": external_id, "headline": "x"},
    )


def _store(tmp_path, records, name="store"):
    rows = tmp_path / f"{name}.jsonl"
    receipt = tmp_path / f"{name}-receipt.json"
    return write_record_store(records, rows, receipt), rows, receipt


def test_store_round_trips(tmp_path):
    records = [_record(minutes_before=m, external_id=f"n{m}") for m in (10, 90)]
    receipt, _, receipt_path = _store(tmp_path, records)
    assert receipt["row_count"] == 2
    assert receipt["source_counts"]["news"] == 2
    assert receipt["execution_authority"] == "ABSENT"
    assert receipt["contains_outcomes"] is False
    loaded_receipt, loaded = load_record_store(receipt_path)
    assert loaded_receipt["store_hash"] == receipt["store_hash"]
    assert set(loaded) == set(records)


def test_mutated_rows_are_detected(tmp_path):
    _, rows, receipt_path = _store(tmp_path, [_record()])
    rows.write_text(rows.read_text(encoding="utf-8").replace("ABC", "XYZ"), encoding="utf-8")
    with pytest.raises(IngestError):
        load_record_store(receipt_path)


def test_a_tampered_receipt_is_detected(tmp_path):
    _, _, receipt_path = _store(tmp_path, [_record()])
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["row_count"] = 99
    receipt_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(IngestError):
        load_record_store(receipt_path)


def test_store_refuses_to_overwrite(tmp_path):
    _store(tmp_path, [_record()])
    with pytest.raises(IngestError):
        _store(tmp_path, [_record()])


def test_backfilled_availability_is_rejected():
    original = _record(minutes_before=120, external_id="story-1")
    retimestamped = _record(minutes_before=10, external_id="story-1")
    with pytest.raises(IngestError):
        assert_stable_availability([original, retimestamped])


def test_availability_drift_against_a_previous_pull_is_rejected(tmp_path):
    _, rows, _ = _store(tmp_path, [_record(minutes_before=120, external_id="story-1")])
    with pytest.raises(IngestError):
        write_record_store(
            [_record(minutes_before=10, external_id="story-1")],
            tmp_path / "second.jsonl", tmp_path / "second-receipt.json",
            previous_rows_path=rows,
        )


def test_records_without_an_external_id_pass_unchecked():
    anonymous = ExogenousRecord(
        source="news", symbol="ABC", event_at=DECISION - timedelta(hours=2),
        available_at=DECISION - timedelta(hours=1), payload={"headline": "x"},
    )
    assert_stable_availability([anonymous, anonymous])


def test_identical_facts_are_deduplicated(tmp_path):
    receipt, _, _ = _store(tmp_path, [_record(), _record()])
    assert receipt["row_count"] == 1


def test_revisions_are_stored_and_counted_but_stay_auditable(tmp_path):
    original = _record(external_id="f1")
    revision = ExogenousRecord(
        source="news", symbol="ABC", event_at=original.event_at,
        available_at=original.available_at, payload={"external_id": "f1", "headline": "y"},
        revision_of=original.record_id,
    )
    receipt, _, _ = _store(tmp_path, [original, revision])
    assert receipt["row_count"] == 2
    assert receipt["revision_count"] == 1


def test_normalize_rejects_a_source_mismatch():
    with pytest.raises(IngestError):
        normalize([_record().as_row()], source="macro")


def test_normalize_reports_the_offending_row():
    bad = _record().as_row()
    bad["available_at"] = "not-a-timestamp"
    with pytest.raises(IngestError, match="row 0"):
        normalize([bad], source="news")
