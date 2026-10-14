"""Constitutional halt refuses a send before the broker is called."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from athena_trading.execution.authority import ExecutionAuthority
from athena_trading.execution.intent import PaperDecision, order_intent_from_decision
from athena_trading.orb_m.constitution import Constitution, ManagementParameters
from athena_trading.orb_m.market import Bar, PriorSession
from athena_trading.orb_m.session import SessionRiskState, run_symbol_session
from athena_trading.paper.fixture import FixtureBroker
from athena_trading.paper.session import run_paper_session
from athena_trading.risk.halt import RiskHaltGate, send_gated

BASE = datetime(2026, 3, 2, 14, 30, tzinfo=UTC)
PARAMS = ManagementParameters(
    pass_below=0.10, standard_above=0.20, high_conviction_above=0.90,
)
PRIOR = PriorSession(
    previous_close=100.0, atr14=2.0,
    average_daily_volume=5_000_000.0,
    average_opening_volume=20_000.0,
)
CONSTITUTION = Constitution(slippage_bps=0.0)


def bar(minute, o, h, low, c, volume=2000.0):
    return Bar(BASE + timedelta(minutes=minute), minute, o, h, low, c, volume)


def long_breakout_session():
    bars = []
    for minute in range(15):
        bars.append(bar(minute, 100.0, 101.0 if minute == 3 else 100.5,
                        99.0 if minute == 4 else 99.5, 100.2))
    bars.append(bar(15, 100.5, 101.2, 100.4, 101.1))
    bars.append(bar(16, 101.2, 101.4, 101.1, 101.3))
    bars.append(bar(17, 101.3, 101.5, 98.0, 98.5))
    return bars


def sendable_decision() -> PaperDecision:
    result = run_symbol_session(long_breakout_session(), PRIOR, CONSTITUTION, PARAMS)
    taken = [ep for ep in result.episodes if ep.result is not None]
    assert taken
    episode = taken[0]
    return PaperDecision(
        "AAPL", episode.signal, episode.quality, PRIOR.atr14, episode.result.entry_price,
    )


def test_max_daily_loss_blocks_the_send_and_the_broker_is_not_called():
    decision = sendable_decision()
    broker = FixtureBroker()
    risk = SessionRiskState(realized_r=-CONSTITUTION.max_daily_loss_r, peak_realized_r=0.0)
    result = run_paper_session(
        [decision],
        constitution=CONSTITUTION,
        parameters=PARAMS,
        broker=broker,
        authority=ExecutionAuthority.PAPER,
        equity=100_000.0,
        risk=risk,
    )
    assert result.halt_reason == "MAX_DAILY_LOSS"
    assert result.submitted == ()
    assert broker.submissions == []


def test_send_gated_does_not_call_submit_when_halted():
    decision = sendable_decision()
    intent = order_intent_from_decision(
        decision, CONSTITUTION, PARAMS,
        equity=100_000.0, authority=ExecutionAuthority.PAPER,
    )
    broker = FixtureBroker()
    gate = RiskHaltGate(CONSTITUTION, SessionRiskState(open_positions=3))
    halt, order = send_gated(intent, gate, broker)
    assert not halt.allowed
    assert halt.reason == "MAX_OPEN_POSITIONS"
    assert order is None
    assert broker.submissions == []


def test_max_drawdown_blocks_before_send():
    decision = sendable_decision()
    broker = FixtureBroker()
    risk = SessionRiskState(realized_r=0.0, peak_realized_r=CONSTITUTION.max_drawdown_r)
    result = run_paper_session(
        [decision],
        constitution=CONSTITUTION,
        parameters=PARAMS,
        broker=broker,
        authority=ExecutionAuthority.PAPER,
        equity=100_000.0,
        risk=risk,
    )
    assert result.halt_reason == "MAX_DRAWDOWN"
    assert broker.submissions == []


def test_absent_authority_sends_nothing():
    decision = sendable_decision()
    broker = FixtureBroker()
    result = run_paper_session(
        [decision],
        constitution=CONSTITUTION,
        parameters=PARAMS,
        broker=broker,
        authority=ExecutionAuthority.ABSENT,
        equity=100_000.0,
    )
    assert result.halt_reason == "AUTHORITY_ABSENT"
    assert broker.submissions == []
    assert result.actions == ()
