"""Opening range, close-based trigger, and the frozen R denominator."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from athena_trading.orb_m.constitution import Constitution
from athena_trading.orb_m.entry import (
    AttemptBudget, BreakoutSignal, OpeningRange, build_risk_frame, detect_breakout,
    freeze_opening_range,
)
from athena_trading.orb_m.market import Bar

BASE = datetime(2026, 3, 2, 14, 30, tzinfo=UTC)  # 09:30 ET


def bar(minute, o, h, low, c, volume=1000.0):
    return Bar(BASE + timedelta(minutes=minute), minute, o, h, low, c, volume)


def opening_window(high=101.0, low=99.0):
    """Fifteen bars spanning [low, high]."""
    bars = [bar(m, 100.0, 100.2, 99.8, 100.0) for m in range(15)]
    bars[3] = bar(3, 100.0, high, 99.8, 100.0)
    bars[7] = bar(7, 100.0, 100.2, low, 100.0)
    return bars


def test_range_freezes_over_the_full_fifteen_minute_window():
    opening = freeze_opening_range(opening_window(), Constitution())
    assert (opening.high, opening.low, opening.frozen_at_minute) == (101.0, 99.0, 15)


def test_partial_opening_window_is_rejected():
    with pytest.raises(ValueError, match="opening window needs 15 bars"):
        freeze_opening_range(opening_window()[:10], Constitution())


def test_a_wick_through_the_high_is_not_a_breakout():
    opening = freeze_opening_range(opening_window(), Constitution())
    # High pierces 101.5 but the bar closes back inside the range.
    bars = opening_window() + [bar(15, 100.5, 101.5, 100.4, 100.9)]
    assert detect_breakout(bars, opening, Constitution()) is None


def test_a_close_beyond_the_high_is_a_long_breakout():
    opening = freeze_opening_range(opening_window(), Constitution())
    bars = opening_window() + [bar(15, 100.5, 101.5, 100.4, 101.2)]
    signal = detect_breakout(bars, opening, Constitution())
    assert (signal.direction, signal.signal_minute) == ("LONG", 15)


def test_a_close_below_the_low_is_a_short_breakout():
    opening = freeze_opening_range(opening_window(), Constitution())
    bars = opening_window() + [bar(15, 99.5, 99.6, 98.4, 98.7)]
    assert detect_breakout(bars, opening, Constitution()).direction == "SHORT"


def test_breakout_search_can_be_restricted_to_one_direction():
    opening = freeze_opening_range(opening_window(), Constitution())
    bars = opening_window() + [bar(15, 100.5, 101.5, 100.4, 101.2)]
    assert detect_breakout(bars, opening, Constitution(), direction="SHORT") is None


def test_a_breakout_after_the_deadline_is_ignored():
    constitution = Constitution()
    opening = freeze_opening_range(opening_window(), constitution)
    late = bar(constitution.session_deadline_minute, 100.5, 101.5, 100.4, 101.2)
    assert detect_breakout(opening_window() + [late], opening, constitution) is None


# --- the stop formulation -------------------------------------------------

def test_wide_range_uses_volatility_not_structure_for_a_long():
    # ORL 90 is far below; ATR 1.0 gives the nearer stop, capping R.
    opening = freeze_opening_range(opening_window(101.0, 90.0), Constitution())
    frame = build_risk_frame(BreakoutSignal("LONG", 15, 101.2, opening), 101.2, 1.0, Constitution())
    assert frame.stop_basis == "VOLATILITY"
    assert frame.stop_price == pytest.approx(100.2)


def test_moderate_range_uses_structure_for_a_long():
    opening = freeze_opening_range(opening_window(101.0, 99.0), Constitution())
    frame = build_risk_frame(BreakoutSignal("LONG", 15, 101.2, opening), 101.2, 5.0, Constitution())
    assert frame.stop_basis == "STRUCTURE"
    assert frame.stop_price == pytest.approx(99.0)


def test_narrow_range_is_floored_so_r_cannot_collapse():
    # A one-cent range: the structural stop sits inside the noise, so without
    # the floor R would be 0.01 and every R-multiple downstream would be noise.
    opening = OpeningRange(high=101.19, low=101.18, volume=15000.0, frozen_at_minute=15)
    frame = build_risk_frame(BreakoutSignal("LONG", 15, 101.2, opening), 101.2, 2.0, Constitution())
    assert frame.stop_basis == "ATR_FLOOR"
    assert frame.risk_per_share == pytest.approx(0.30)  # 0.15 * ATR 2.0


def test_short_stop_mirrors_the_long_formulation():
    opening = freeze_opening_range(opening_window(110.0, 99.0), Constitution())
    frame = build_risk_frame(BreakoutSignal("SHORT", 15, 98.8, opening), 98.8, 1.0, Constitution())
    assert frame.stop_basis == "VOLATILITY"
    assert frame.stop_price == pytest.approx(99.8)


def test_r_denominator_is_frozen_and_thresholds_follow_it():
    opening = freeze_opening_range(opening_window(101.0, 99.0), Constitution())
    frame = build_risk_frame(BreakoutSignal("LONG", 15, 101.0, opening), 101.0, 5.0, Constitution())
    assert frame.risk_per_share == pytest.approx(2.0)
    assert frame.r_multiple(103.0) == pytest.approx(1.0)
    assert frame.price_at_r(0.5) == pytest.approx(102.0)


def test_short_r_multiple_is_positive_when_price_falls():
    opening = freeze_opening_range(opening_window(101.0, 99.0), Constitution())
    frame = build_risk_frame(BreakoutSignal("SHORT", 15, 99.0, opening), 99.0, 5.0, Constitution())
    assert frame.r_multiple(97.0) == pytest.approx(1.0)


# --- attempt budget --------------------------------------------------------

def test_one_initial_attempt_and_one_reentry_per_direction():
    budget = AttemptBudget(Constitution())
    budget.record("LONG", is_reentry=False)
    assert not budget.may_attempt("LONG", is_reentry=False)
    assert budget.may_attempt("LONG", is_reentry=True)
    # A failed long leaves the short side untouched.
    assert budget.may_attempt("SHORT", is_reentry=False)
    budget.record("LONG", is_reentry=True)
    assert not budget.may_attempt("LONG", is_reentry=True)


def test_exhausted_budget_raises():
    budget = AttemptBudget(Constitution())
    budget.record("SHORT", is_reentry=False)
    with pytest.raises(ValueError, match="budget exhausted"):
        budget.record("SHORT", is_reentry=False)
