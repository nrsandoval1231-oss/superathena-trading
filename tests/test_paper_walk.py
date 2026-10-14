"""Bar-walking paper session: act as each completed bar arrives."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from athena_trading.execution.authority import ExecutionAuthority
from athena_trading.orb_m.session import SessionRiskState
from athena_trading.paper.bars import load_bar_session
from athena_trading.paper.demo import (
    DEMO_CONSTITUTION, DEMO_EQUITY, DEMO_PARAMETERS, DEMO_PRIOR, DEMO_SYMBOL, demo_bars,
)
from athena_trading.paper.fixture import FixtureBroker
from athena_trading.paper.walk import run_walk_fixture, walk_paper_session

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_orb_m_paper.py"
FIXTURE = (
    Path(__file__).resolve().parents[1] / "configs" / "fixtures" / "orb_m_paper_bars_v1.json"
)


def _script():
    spec = importlib.util.spec_from_file_location("run_orb_m_paper", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_walk_sends_a_long_entry_on_the_signal_bar_without_later_bars():
    prefix = tuple(bar for bar in demo_bars() if bar.minute <= 15)
    broker = FixtureBroker()
    result = walk_paper_session(
        prefix, DEMO_PRIOR,
        symbol=DEMO_SYMBOL,
        constitution=DEMO_CONSTITUTION,
        parameters=DEMO_PARAMETERS,
        broker=broker,
        authority=ExecutionAuthority.PAPER,
        equity=DEMO_EQUITY,
    )
    assert result.mode == "walk"
    assert result.halt_reason is None
    assert len(broker.submissions) == 1
    intent = broker.submissions[0]
    assert intent.side == "BUY"
    assert intent.signal.direction == "LONG"
    assert intent.signal.signal_minute == 15
    assert result.actions[0].bar_minute == 15
    assert result.bars_processed == len(prefix)


def test_walk_halt_blocks_the_send_before_the_broker():
    broker = FixtureBroker()
    result = walk_paper_session(
        demo_bars(), DEMO_PRIOR,
        symbol=DEMO_SYMBOL,
        constitution=DEMO_CONSTITUTION,
        parameters=DEMO_PARAMETERS,
        broker=broker,
        authority=ExecutionAuthority.PAPER,
        equity=DEMO_EQUITY,
        risk=SessionRiskState(
            realized_r=-DEMO_CONSTITUTION.max_daily_loss_r,
            peak_realized_r=0.0,
        ),
    )
    assert result.halt_reason == "MAX_DAILY_LOSS"
    assert broker.submissions == []
    assert result.submitted == ()
    assert result.blocked


def test_walk_absent_authority_does_not_send():
    broker = FixtureBroker()
    result = walk_paper_session(
        demo_bars(), DEMO_PRIOR,
        symbol=DEMO_SYMBOL,
        constitution=DEMO_CONSTITUTION,
        parameters=DEMO_PARAMETERS,
        broker=broker,
        authority=ExecutionAuthority.ABSENT,
        equity=DEMO_EQUITY,
    )
    assert result.halt_reason == "AUTHORITY_ABSENT"
    assert broker.submissions == []
    assert result.submitted == ()
    assert result.blocked


def test_shipped_fixture_matches_demo_bars_and_walks():
    recorded = load_bar_session(FIXTURE)
    assert recorded.symbol == "AAPL"
    assert recorded.bars == demo_bars()
    broker = FixtureBroker()
    result = run_walk_fixture(broker=broker, session=recorded)
    assert result.mode == "walk"
    assert result.submitted
    assert broker.submissions[0].signal.direction == "LONG"


def test_naive_bar_timestamp_fails_closed(tmp_path):
    path = tmp_path / "bars.json"
    path.write_text(json.dumps({
        "schema_version": "athena-orb-m-paper-bars-v1",
        "symbol": "AAPL",
        "prior": {
            "previous_close": 100.0, "atr14": 2.0,
            "average_daily_volume": 1.0, "average_opening_volume": 1.0,
        },
        "bars": [{
            "event_at": "2026-03-02T14:30:00",
            "minute": 0, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1,
        }],
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="timezone-aware"):
        load_bar_session(path)


def test_documented_walk_bars_command(capsys):
    code = _script().main(["--walk-bars"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["walk_bars"] is True
    assert payload["mode"] == "walk"
    assert payload["broker"] == "fixture"
    assert payload["live_trading"] is False
    assert payload["submitted"] >= 1
    assert payload["bars_processed"] >= 16


def test_walk_bars_halt_demo_command(capsys):
    code = _script().main(["--walk-bars", "--halt-demo"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["halt_reason"] == "MAX_DAILY_LOSS"
    assert payload["submitted"] == 0


def test_walk_bars_alpaca_without_keys_fails_closed(monkeypatch, capsys):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
    code = _script().main(["--broker", "alpaca", "--authority", "PAPER"])
    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "ALPACA" in payload["error"]
