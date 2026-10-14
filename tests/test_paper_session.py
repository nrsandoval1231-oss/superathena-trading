"""Paper session wires ORB-M decisions through the halt gate to a broker."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from athena_trading.execution.authority import AuthorityError, ExecutionAuthority
from athena_trading.execution.broker import OrderStatus
from athena_trading.paper.fixture import FixtureBroker
from athena_trading.paper.session import (
    load_paper_config, result_as_dict, run_dry_run, run_orb_m_paper_session,
)
from athena_trading.paper.demo import (
    DEMO_CONSTITUTION, DEMO_EQUITY, DEMO_PARAMETERS, DEMO_PRIOR, DEMO_SYMBOL, demo_bars,
)
from athena_trading.paper.alpaca import MissingCredentialsError

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_orb_m_paper.py"


def _script():
    spec = importlib.util.spec_from_file_location("run_orb_m_paper", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dry_run_submits_an_orb_m_entry_through_the_fixture():
    broker = FixtureBroker()
    result = run_dry_run(authority=ExecutionAuthority.PAPER, broker=broker)
    assert result.halt_reason is None
    assert len(result.submitted) >= 1
    assert broker.submissions
    assert broker.submissions[0].signal.direction == "LONG"
    assert result.submitted[0].status is OrderStatus.NEW
    receipt = result_as_dict(result)
    assert receipt["live_trading"] is False
    assert receipt["execution_authority"] == "PAPER"


def test_halt_demo_blocks_before_any_fixture_submit():
    broker = FixtureBroker()
    result = run_dry_run(
        authority=ExecutionAuthority.PAPER, halt_demo=True, broker=broker,
    )
    assert result.halt_reason == "MAX_DAILY_LOSS"
    assert broker.submissions == []
    assert result.submitted == ()


def test_orb_m_paper_session_reuses_the_engine_on_demo_bars():
    broker = FixtureBroker()
    result = run_orb_m_paper_session(
        demo_bars(), DEMO_PRIOR,
        symbol=DEMO_SYMBOL,
        constitution=DEMO_CONSTITUTION,
        parameters=DEMO_PARAMETERS,
        broker=broker,
        authority=ExecutionAuthority.PAPER,
        equity=DEMO_EQUITY,
    )
    assert result.submitted
    assert all(order.symbol == "AAPL" for order in result.submitted)


def test_config_stays_absent_and_rejects_live(tmp_path):
    config = load_paper_config(
        Path(__file__).resolve().parents[1] / "configs" / "orb_m_paper_session_v1.json",
    )
    assert config["execution_authority"] == "ABSENT"
    assert config["environment"] == "PAPER"
    live = tmp_path / "live.json"
    live.write_text(json.dumps({
        "schema_version": "athena-orb-m-paper-session-v1",
        "environment": "PAPER",
        "execution_authority": "LIVE",
        "equity": 100000.0,
    }), encoding="utf-8")
    with pytest.raises(AuthorityError, match="LIVE"):
        load_paper_config(live)


def test_documented_dry_run_command(capsys):
    code = _script().main(["--dry-run"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["broker"] == "fixture"
    assert payload["live_trading"] is False
    assert payload["submitted"] >= 1
    assert payload["dry_run"] is True


def test_script_alpaca_path_fails_closed_without_keys(monkeypatch, capsys):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
    code = _script().main(["--broker", "alpaca", "--authority", "PAPER"])
    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "ALPACA" in payload["error"]
    assert payload["live_trading"] is False


def test_legacy_demo_cannot_send_real_broker_orders(monkeypatch):
    script = _script()

    def forbidden():
        raise AssertionError("legacy submission must stop before broker access")

    monkeypatch.setattr(script.AlpacaPaperBroker, "from_env", forbidden)
    with pytest.raises(SystemExit) as exc:
        script.main(["--broker", "alpaca", "--authority", "PAPER", "--submit-demo"])
    assert exc.value.code == 2


def test_script_without_flags_does_not_send(capsys):
    code = _script().main([])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["execution_authority"] == "ABSENT"
    assert payload["submitted"] == 0
    assert payload["halt_reason"] == "AUTHORITY_ABSENT"
    assert payload["dry_run"] is False


def test_missing_credentials_error_is_the_fail_closed_type():
    assert issubclass(MissingCredentialsError, Exception)
