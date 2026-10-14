"""Order intent is derived from an ORB-M decision, not a second strategy."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from athena_trading.execution.authority import AuthorityError, ExecutionAuthority, parse_authority
from athena_trading.execution.intent import (
    OrderIntent, PaperDecision, order_intent_from_decision, size_shares,
)
from athena_trading.orb_m.constitution import BreakoutAction, Constitution, ManagementParameters
from athena_trading.orb_m.market import Bar, PriorSession
from athena_trading.orb_m.session import run_symbol_session

BASE = datetime(2026, 3, 2, 14, 30, tzinfo=UTC)
PARAMS = ManagementParameters(
    pass_below=0.10, standard_above=0.20, high_conviction_above=0.90,
)
PRIOR = PriorSession(
    previous_close=100.0, atr14=2.0,
    average_daily_volume=5_000_000.0,
    average_opening_volume=20_000.0,
)


def bar(minute, o, h, low, c, volume=2000.0):
    return Bar(BASE + timedelta(minutes=minute), minute, o, h, low, c, volume)


def opening_range_bars():
    bars = []
    for minute in range(15):
        bars.append(bar(minute, 100.0, 101.0 if minute == 3 else 100.5,
                        99.0 if minute == 4 else 99.5, 100.2))
    return bars


def long_breakout_session():
    bars = opening_range_bars()
    bars.append(bar(15, 100.5, 101.2, 100.4, 101.1))
    bars.append(bar(16, 101.2, 101.4, 101.1, 101.3))
    bars.append(bar(17, 101.3, 101.5, 98.0, 98.5))
    return bars


def _taken_decision():
    result = run_symbol_session(
        long_breakout_session(), PRIOR, Constitution(slippage_bps=0.0), PARAMS,
    )
    taken = [ep for ep in result.episodes if ep.result is not None]
    assert taken, "ORB-M should take the long fixture"
    episode = taken[0]
    return PaperDecision(
        "AAPL", episode.signal, episode.quality, PRIOR.atr14, episode.result.entry_price,
    )


def test_live_authority_is_not_a_value():
    with pytest.raises(AuthorityError, match="LIVE"):
        parse_authority("LIVE")


def test_order_intent_from_an_orb_m_long_decision():
    decision = _taken_decision()
    intent = order_intent_from_decision(
        decision, Constitution(slippage_bps=0.0), PARAMS,
        equity=100_000.0, authority=ExecutionAuthority.PAPER,
    )
    assert intent.symbol == "AAPL"
    assert intent.side == "BUY"
    assert intent.quantity >= 1
    assert intent.order_type == "MARKET"
    assert intent.time_in_force == "DAY"
    assert intent.authority is ExecutionAuthority.PAPER
    assert intent.signal.direction == "LONG"
    assert intent.risk_frame.direction == "LONG"
    assert intent.risk_frame.stop_price < intent.risk_frame.entry_price
    assert intent.action is not BreakoutAction.PASS
    assert intent.client_order_id.startswith("orbm-AAPL-L-")


def test_intent_requires_paper_authority():
    decision = _taken_decision()
    with pytest.raises(AuthorityError, match="ABSENT"):
        order_intent_from_decision(
            decision, Constitution(slippage_bps=0.0), PARAMS,
            equity=100_000.0, authority=ExecutionAuthority.ABSENT,
        )


def test_pass_is_not_a_sendable_intent():
    decision = _taken_decision()
    from athena_trading.orb_m.quality import BreakoutQualityResult
    blocked = PaperDecision(
        decision.symbol, decision.signal,
        BreakoutQualityResult(True, 0.0, BreakoutAction.PASS, {}),
        decision.atr14, decision.entry_price,
    )
    assert not blocked.sendable
    with pytest.raises(ValueError, match="not sendable"):
        order_intent_from_decision(
            blocked, Constitution(), PARAMS,
            equity=100_000.0, authority=ExecutionAuthority.PAPER,
        )


def test_sizing_respects_the_constitutional_risk_cap():
    shares = size_shares(
        equity=100_000.0,
        action=BreakoutAction.STANDARD,
        risk_per_share=2.0,
        entry_price=100.0,
        constitution=Constitution(),
        parameters=ManagementParameters(),
    )
    # 0.005 * 100000 / 2.0 = 250, under the 0.01 cap and 0.75 notional cap.
    assert shares == 250


def test_intent_rejects_a_side_that_disagrees_with_the_signal():
    decision = _taken_decision()
    intent = order_intent_from_decision(
        decision, Constitution(slippage_bps=0.0), PARAMS,
        equity=100_000.0, authority=ExecutionAuthority.PAPER,
    )
    with pytest.raises(ValueError, match="side must match"):
        OrderIntent(
            symbol=intent.symbol, side="SELL", quantity=intent.quantity,
            order_type="MARKET", time_in_force="DAY",
            client_order_id=intent.client_order_id,
            authority=ExecutionAuthority.PAPER,
            signal=intent.signal, risk_frame=intent.risk_frame,
            action=intent.action,
        )
