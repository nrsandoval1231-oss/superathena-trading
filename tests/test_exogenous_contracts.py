import json
from datetime import UTC, datetime, timedelta

import pytest

from athena_trading.exogenous import (
    ExogenousContractError,
    ExogenousLeakageError,
    ExogenousRecord,
    assert_no_lookahead,
    parse_record,
    visible_records,
)

DECISION = datetime(2026, 2, 3, 14, 45, tzinfo=UTC)  # 09:45 ET


def _record(**overrides):
    base = {
        "source": "news",
        "symbol": "ABC",
        "available_at": DECISION - timedelta(hours=1),
        "payload": {"headline": "x", "external_id": "n1"},
    }
    base.update(overrides)
    # Publication lag defaults to an hour behind whatever availability the test
    # asked for, so moving availability alone never trips the ordering guard.
    base.setdefault("event_at", base["available_at"] - timedelta(hours=1))
    return ExogenousRecord(**base)


def test_available_at_may_not_precede_event_at():
    with pytest.raises(ExogenousContractError):
        _record(event_at=DECISION, available_at=DECISION - timedelta(minutes=1))


def test_naive_timestamps_are_rejected():
    with pytest.raises(ExogenousContractError):
        _record(available_at=datetime(2026, 2, 3, 9, 0))


def test_symbol_required_except_for_market_wide_sources():
    with pytest.raises(ExogenousContractError):
        _record(symbol=None)
    assert _record(source="macro", symbol=None, payload={"category": "inflation"}).symbol is None


def test_unknown_source_is_rejected():
    with pytest.raises(ExogenousContractError):
        _record(source="astrology")


def test_record_at_exactly_as_of_is_visible_and_one_microsecond_later_is_not():
    on_time = _record(available_at=DECISION)
    late = _record(available_at=DECISION + timedelta(microseconds=1), payload={"external_id": "n2"})
    visible = visible_records([on_time, late], as_of=DECISION)
    assert visible == (on_time,)


def test_revisions_are_never_visible_in_place_of_their_original():
    original = _record(payload={"value": 1, "external_id": "f1"})
    revision = _record(payload={"value": 2, "external_id": "f1"}, revision_of=original.record_id)
    assert visible_records([original, revision], as_of=DECISION) == (original,)


def test_symbol_filter_keeps_market_wide_records():
    named = _record()
    macro = _record(source="macro", symbol=None, payload={"category": "rates"})
    other = _record(symbol="XYZ", payload={"external_id": "n3"})
    visible = visible_records([named, macro, other], as_of=DECISION, symbol="ABC")
    assert set(visible) == {named, macro}


def test_visibility_order_is_independent_of_input_order():
    records = [
        _record(available_at=DECISION - timedelta(minutes=minute), payload={"external_id": f"n{minute}"})
        for minute in (5, 1, 30, 12)
    ]
    forward = visible_records(records, as_of=DECISION)
    backward = visible_records(list(reversed(records)), as_of=DECISION)
    assert forward == backward
    assert [item.available_at for item in forward] == sorted(item.available_at for item in forward)


def test_lookback_window_excludes_stale_evidence():
    fresh = _record(available_at=DECISION - timedelta(minutes=10))
    stale = _record(available_at=DECISION - timedelta(days=3), payload={"external_id": "n9"})
    assert visible_records([fresh, stale], as_of=DECISION, lookback_seconds=3600) == (fresh,)


def test_assert_no_lookahead_catches_a_leaked_set():
    leaked = _record(available_at=DECISION + timedelta(seconds=1))
    with pytest.raises(ExogenousLeakageError):
        assert_no_lookahead([leaked], as_of=DECISION)


def test_assert_no_lookahead_rejects_a_revision():
    revision = _record(revision_of="abc")
    with pytest.raises(ExogenousLeakageError):
        assert_no_lookahead([revision], as_of=DECISION)


def test_naive_as_of_is_refused():
    with pytest.raises(ExogenousLeakageError):
        visible_records([], as_of=datetime(2026, 2, 3, 9, 45))


def test_record_id_is_content_identity():
    assert _record().record_id == _record().record_id
    assert _record().record_id != _record(payload={"headline": "y"}).record_id


def test_parse_round_trips_through_json():
    record = _record()
    assert parse_record(json.loads(json.dumps(record.as_row()))) == record
