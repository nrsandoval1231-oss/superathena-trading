"""Session runners — AAT full-session contract and campaign symbol session."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from athena_trading.orb_m.constitution import Constitution, ManagementParameters
from athena_trading.orb_m.entry import OpeningRange
from athena_trading.orb_m.market import Bar, PriorSession
from athena_trading.orb_m.session import (
    SessionRiskState,
    deterioration_by_minute,
    run_full_session,
    run_symbol_session,
)

BASE = datetime(2026, 3, 2, 14, 30, tzinfo=UTC)
PARAMS = ManagementParameters(
    pass_below=0.10, standard_above=0.20, high_conviction_above=0.90,
)
PRIOR = PriorSession(
    previous_close=100.0, atr14=2.0,
    average_daily_volume=5_000_000.0,
    average_opening_volume=20_000.0,
)


def _bar(minute, open_, high, low, close, volume=1000):
    return Bar(BASE + timedelta(minutes=minute), minute, open_, high, low, close, volume)


def bar(minute, o, h, low, c, volume=2000.0):
    return Bar(BASE + timedelta(minutes=minute), minute, o, h, low, c, volume)


def _session():
    bars = [_bar(minute, 100, 100.5, 99.5, 100) for minute in range(15)]
    bars += [
        _bar(15, 100.5, 102.2, 100.4, 102.0),
        _bar(16, 102.0, 102.2, 101.8, 102.0),
        _bar(17, 102.0, 102.1, 98.5, 99.0),
        _bar(18, 99.0, 99.2, 97.8, 98.0),
        _bar(19, 98.0, 98.2, 97.5, 98.0),
    ]
    bars += [_bar(minute, 98, 98.2, 97.8, 98) for minute in range(20, 390)]
    return bars


def test_deterioration_is_prefix_stable():
    opening = OpeningRange(101, 99, 15000, 15)
    parameters = ManagementParameters()
    bars = _session()
    before = deterioration_by_minute(bars[:18], "LONG", opening, parameters)[17]
    after = deterioration_by_minute(bars, "LONG", opening, parameters)[17]
    assert before == after


def test_full_session_keeps_both_directions_live():
    result = run_full_session(
        OpeningRange(101, 99, 15000, 15), _session(), 2.0,
        Constitution(), ManagementParameters(),
    )
    assert {episode.direction for episode in result.episodes} == {"LONG", "SHORT"}
    assert result.initial_attempts == 2
    assert result.reentries <= 2
    assert all(
        episode.result.exit_reason not in {"OPEN", "DATA_EXHAUSTED"}
        for episode in result.episodes
    )


def opening_range_bars():
    bars = []
    for m in range(15):
        bars.append(bar(m, 100.0, 101.0 if m == 3 else 100.5,
                        99.0 if m == 4 else 99.5, 100.2, volume=2000))
    return bars


def long_breakout_session():
    bars = opening_range_bars()
    bars.append(bar(15, 100.5, 101.2, 100.4, 101.1))
    bars.append(bar(16, 101.2, 101.4, 101.1, 101.3))
    bars.append(bar(17, 101.3, 101.5, 98.0, 98.5))
    return bars


def test_session_runs_a_long_episode_to_a_stop():
    result = run_symbol_session(
        long_breakout_session(), PRIOR, Constitution(slippage_bps=0.0), PARAMS,
    )
    taken = [ep for ep in result.episodes if ep.result is not None]
    assert taken
    assert taken[0].signal.direction == "LONG"
    assert taken[0].result.exit_reason == "STOP"


def test_max_daily_loss_halts_further_entries():
    risk = SessionRiskState(realized_r=-3.0, peak_realized_r=0.0)
    result = run_symbol_session(
        long_breakout_session(), PRIOR, Constitution(slippage_bps=0.0), PARAMS, risk=risk,
    )
    assert result.halt_reason == "MAX_DAILY_LOSS"
    assert all(ep.result is None for ep in result.episodes)


def test_max_open_positions_is_enforced_before_entry():
    risk = SessionRiskState(open_positions=3)
    result = run_symbol_session(
        long_breakout_session(), PRIOR, Constitution(slippage_bps=0.0), PARAMS, risk=risk,
    )
    assert result.halt_reason == "MAX_OPEN_POSITIONS"


def test_both_sides_can_attempt_independently():
    bars = opening_range_bars()
    bars += [
        bar(15, 100.5, 101.2, 100.4, 101.1),
        bar(16, 101.2, 101.4, 101.1, 101.3),
        bar(17, 101.3, 101.5, 98.5, 98.8),
        bar(18, 98.8, 98.9, 98.0, 98.2),
        bar(19, 98.2, 98.3, 98.0, 98.1),
        bar(20, 98.1, 100.5, 98.0, 100.2),
    ]
    result = run_symbol_session(bars, PRIOR, Constitution(slippage_bps=0.0), PARAMS)
    directions = [ep.signal.direction for ep in result.episodes if ep.result is not None]
    assert "LONG" in directions and "SHORT" in directions


def test_excluded_retracement_does_not_end_the_reentry_scan():
    """A retracement inside the open band is skipped. A later valid reset still runs."""
    bars = opening_range_bars()
    bars += [
        bar(15, 100.5, 101.2, 100.4, 101.1),
        bar(16, 101.2, 102.2, 101.0, 101.5),
        bar(17, 101.0, 101.2, 98.8, 99.4),
        bar(18, 101.4, 102.0, 101.2, 101.90),
        bar(19, 100.2, 100.6, 99.8, 100.2),
        bar(20, 100.1, 100.4, 99.6, 100.0),
        bar(22, 101.2, 101.6, 101.1, 101.50),
    ]
    result = run_symbol_session(bars, PRIOR, Constitution(slippage_bps=0.0), PARAMS)
    reentries = [
        episode for episode in result.episodes
        if episode.signal.direction == "LONG" and episode.signal.is_reentry
    ]
    assert [episode.signal.signal_minute for episode in reentries] == [22]
    assert all(episode.signal.signal_minute != 18 for episode in result.episodes)


def test_attempt_budget_blocks_a_second_initial_long():
    bars = opening_range_bars()
    bars += [
        bar(15, 100.5, 101.2, 100.4, 101.1),
        bar(16, 101.2, 101.4, 101.1, 101.3),
        bar(17, 101.3, 101.5, 98.5, 98.8),
        bar(30, 100.0, 101.5, 99.5, 101.2),
        bar(31, 101.2, 101.4, 101.0, 101.3),
        bar(32, 101.3, 101.4, 98.5, 98.8),
    ]
    params = ManagementParameters(
        pass_below=0.10, standard_above=0.20,
        high_conviction_above=0.90, reentry_enabled=False,
    )
    result = run_symbol_session(bars, PRIOR, Constitution(slippage_bps=0.0), params)
    longs = [
        ep for ep in result.episodes
        if ep.signal.direction == "LONG" and ep.result is not None
    ]
    assert len(longs) == 1
    assert all(not ep.signal.is_reentry for ep in longs)
