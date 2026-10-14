import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from athena_trading.aat_v2.opportunities import OpportunityIndexError, build_opportunity_index


def _bar(symbol, stamp, close, *, high=None, low=None):
    event = stamp.replace(tzinfo=UTC)
    return {
        "symbol": symbol,
        "event_at": event.isoformat(),
        "available_at": (event + timedelta(minutes=1)).isoformat(),
        "open": close,
        "high": high if high is not None else close + 0.1,
        "low": low if low is not None else close - 0.1,
        "close": close,
        "volume": 1000,
    }


def _session(symbol, day, direction=None):
    start = datetime.fromisoformat(f"{day}T14:30:00")
    rows = []
    for minute in range(15):
        rows.append(_bar(symbol, start + timedelta(minutes=minute), 100, high=101, low=99))
    close = 102 if direction == "LONG" else 98 if direction == "SHORT" else 100
    rows.append(_bar(symbol, start + timedelta(minutes=15), close))
    return rows


def _write(path: Path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_builds_first_long_and_short_close_through(tmp_path):
    source = tmp_path / "bars.jsonl"
    _write(source, _session("AAPL", "2024-01-02", "LONG") + _session("AAPL", "2024-01-03", "SHORT"))
    rows = tmp_path / "opportunities.jsonl"
    receipt = tmp_path / "opportunities.receipt.json"

    result = build_opportunity_index([source], rows, receipt)

    output = [json.loads(line) for line in rows.read_text().splitlines()]
    assert result["row_count"] == 2
    assert [item["features"]["direction"] for item in output] == ["LONG", "SHORT"]
    assert all("outcome" not in item for item in output)
    assert result["contains_outcomes"] is False
    assert result["execution_authority"] == "ABSENT"


def test_uses_first_close_through_only(tmp_path):
    source = tmp_path / "bars.jsonl"
    rows = _session("AAPL", "2024-01-02", "LONG")
    start = datetime.fromisoformat("2024-01-02T14:30:00")
    rows.insert(16, _bar("AAPL", start + timedelta(minutes=16), 103))
    _write(source, rows)
    output = tmp_path / "opportunities.jsonl"
    receipt = tmp_path / "receipt.json"

    build_opportunity_index([source], output, receipt)

    item = json.loads(output.read_text().splitlines()[0])
    assert item["features"]["signal_minute"] == 15


def test_no_signal_is_not_an_error_but_empty_index_is_rejected(tmp_path):
    source = tmp_path / "bars.jsonl"
    _write(source, _session("AAPL", "2024-01-02"))
    with pytest.raises(OpportunityIndexError, match="no opportunities"):
        build_opportunity_index([source], tmp_path / "rows.jsonl", tmp_path / "receipt.json")
