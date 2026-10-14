import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta

from athena_trading.exogenous import ExogenousRecord, write_record_store

DECISION = datetime(2026, 2, 3, 14, 45, tzinfo=UTC)
PRIOR_CLOSE = datetime(2026, 2, 2, 21, 0, tzinfo=UTC)
SCRIPT = "scripts/measure_exogenous_coverage.py"


def _fixture(tmp_path, symbols_with_news):
    records = [
        ExogenousRecord(
            source="news", symbol=symbol, event_at=DECISION - timedelta(hours=2),
            available_at=DECISION - timedelta(hours=1),
            payload={"external_id": f"n-{symbol}"},
        )
        for symbol in symbols_with_news
    ]
    store_receipt = tmp_path / "store-receipt.json"
    write_record_store(records, tmp_path / "store.jsonl", store_receipt)
    index = tmp_path / "opportunities.jsonl"
    index.write_text("".join(
        json.dumps({
            "opportunity_id": f"op-{symbol}", "symbol": symbol,
            "decision_at": DECISION.isoformat(), "prior_close_at": PRIOR_CLOSE.isoformat(),
        }) + "\n" for symbol in ("ABC", "XYZ")
    ), encoding="utf-8")
    return index, store_receipt


def _run(tmp_path, index, store_receipt, *extra):
    return subprocess.run(
        [sys.executable, SCRIPT, "--opportunity-index", str(index),
         "--store-receipt", str(store_receipt), *extra],
        capture_output=True, text=True, env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"},
    )


def test_report_states_the_coverage_rate(tmp_path):
    index, store = _fixture(tmp_path, ["ABC"])
    result = _run(tmp_path, index, store)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["opportunity_count"] == 2
    assert report["coverage_rates"]["news"] == 0.5
    assert report["execution_authority"] == "ABSENT"


def test_floor_failure_is_reported_by_exit_code(tmp_path):
    index, store = _fixture(tmp_path, ["ABC"])
    assert _run(tmp_path, index, store, "--floor", "0.9").returncode == 1
    assert _run(tmp_path, index, store, "--floor", "0.4").returncode == 1  # sentiment is 0.0


def test_report_is_written_when_requested(tmp_path):
    index, store = _fixture(tmp_path, ["ABC", "XYZ"])
    output = tmp_path / "coverage.json"
    assert _run(tmp_path, index, store, "--output", str(output)).returncode == 0
    assert json.loads(output.read_text(encoding="utf-8"))["coverage_rates"]["news"] == 1.0
