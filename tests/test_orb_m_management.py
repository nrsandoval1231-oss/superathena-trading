"""Staircase, retention, harvests, and exit pressure -- no bars involved."""
from __future__ import annotations

import pytest

from athena_trading.orb_m.constitution import (
    BreakoutAction, Constitution, ManagementParameters, TrailStage,
)
from athena_trading.orb_m.entry import RiskFrame
from athena_trading.orb_m.management import (
    PositionState, action_for, exit_pressure, stage_for, trail_stop_r,
)

PARAMS = ManagementParameters()
FRAME = RiskFrame("LONG", 100.0, 98.0, 2.0, "STRUCTURE")


@pytest.mark.parametrize("peak_r,expected", [
    (0.0, TrailStage.RISK), (0.49, TrailStage.RISK),
    (0.5, TrailStage.PROTECT), (0.99, TrailStage.PROTECT),
    (1.0, TrailStage.FREE_TRADE), (1.5, TrailStage.PROFIT_LOCK),
    (2.0, TrailStage.TREND_RIDE), (5.0, TrailStage.TREND_RIDE),
])
def test_stages_advance_on_peak_excursion(peak_r, expected):
    assert stage_for(peak_r, PARAMS) is expected


def test_free_trade_puts_the_stop_at_breakeven():
    assert trail_stop_r(1.0, PARAMS) == pytest.approx(0.0)


def test_protect_stage_halves_the_allowable_loss():
    assert trail_stop_r(0.5, PARAMS) == pytest.approx(-0.5)


def test_peak_retention_arms_only_above_its_threshold():
    # At 1.9R retention is not yet armed, so the staircase governs.
    assert trail_stop_r(1.9, PARAMS) == pytest.approx(PARAMS.profit_lock_stop_r)
    # At 3R retention gives 1.95R, which exceeds every staircase floor.
    assert trail_stop_r(3.0, PARAMS) == pytest.approx(1.95)


def test_retention_protects_an_exceptional_winner_from_a_round_trip():
    # The spec's worked example: +3R peak must retain roughly 1.95R.
    assert trail_stop_r(3.0, PARAMS) == pytest.approx(3.0 * PARAMS.peak_retention)


def test_atr_trail_can_widen_protection_while_riding_a_trend():
    # A volatile name (ATR = 1R) trails further back than bare retention.
    loose = trail_stop_r(10.0, PARAMS, atr_in_r=1.0)
    assert loose == pytest.approx(max(10.0 * PARAMS.peak_retention, 10.0 - 1.5))


def test_the_stop_never_ratchets_backward():
    position = PositionState(FRAME, 20, Constitution(), PARAMS)
    position.observe(3.0, 0.0)
    protected = position.stop_r
    position.observe(0.1, -0.9)  # a deep pullback
    assert position.stop_r == protected


def test_stage_cannot_be_demoted_by_a_pullback():
    position = PositionState(FRAME, 20, Constitution(), PARAMS)
    position.observe(2.5, 0.0)
    position.observe(0.0, -0.5)
    assert position.stage is TrailStage.TREND_RIDE


# --- harvests --------------------------------------------------------------

def test_first_harvest_is_due_at_one_r():
    position = PositionState(FRAME, 20, Constitution(), PARAMS)
    assert position.due_harvests(0.99, 21) == []
    assert position.due_harvests(1.0, 21)[0][0] == "FIRST_HARVEST"


def test_momentum_harvest_only_inside_the_impulse_window():
    position = PositionState(FRAME, 20, Constitution(), PARAMS)
    inside = [name for name, _ in position.due_harvests(1.6, 20 + PARAMS.explore_minutes)]
    outside = [name for name, _ in position.due_harvests(1.6, 21 + PARAMS.explore_minutes)]
    assert "MOMENTUM_HARVEST" in inside
    assert "MOMENTUM_HARVEST" not in outside


def test_harvests_bank_r_weighted_by_fraction_and_leave_a_runner():
    position = PositionState(FRAME, 20, Constitution(), PARAMS)
    position.reduce(0.25, 1.0, 21, "FIRST_HARVEST")
    assert position.remaining == pytest.approx(0.75)
    assert position.realized_r == pytest.approx(0.25)
    assert position.is_open


def test_a_harvest_cannot_exceed_what_remains():
    position = PositionState(FRAME, 20, Constitution(), PARAMS)
    position.reduce(0.9, 1.0, 21, "FIRST_HARVEST")
    assert position.reduce(0.5, 2.0, 22, "MOMENTUM_HARVEST") == pytest.approx(0.1)
    assert position.remaining == 0.0


def test_closing_banks_the_runner_at_its_own_r():
    position = PositionState(FRAME, 20, Constitution(), PARAMS)
    position.reduce(0.25, 1.0, 21, "FIRST_HARVEST")
    position.close(3.0, 60, "SESSION_DEADLINE")
    # 0.25 at 1R plus 0.75 at 3R.
    assert position.realized_r == pytest.approx(0.25 * 1.0 + 0.75 * 3.0)
    assert not position.is_open


# --- actions and deterioration --------------------------------------------

@pytest.mark.parametrize("confidence,expected", [
    (0.30, BreakoutAction.PASS), (0.54, BreakoutAction.PASS),
    (0.55, BreakoutAction.REDUCED), (0.70, BreakoutAction.REDUCED),
    (0.71, BreakoutAction.STANDARD), (0.85, BreakoutAction.STANDARD),
    (0.86, BreakoutAction.HIGH_CONVICTION), (1.0, BreakoutAction.HIGH_CONVICTION),
])
def test_confidence_maps_to_the_four_actions(confidence, expected):
    assert action_for(confidence, PARAMS) is expected


def test_confidence_outside_the_unit_interval_is_rejected():
    with pytest.raises(ValueError, match="within"):
        action_for(1.5, PARAMS)


def test_one_weak_signal_does_not_exit_but_several_do():
    assert exit_pressure(["lower_high"], PARAMS) < PARAMS.exit_pressure_threshold
    assert exit_pressure(["vwap_loss", "adverse_candle"], PARAMS) >= \
        PARAMS.exit_pressure_threshold


def test_repeated_signals_are_counted_once():
    assert exit_pressure(["lower_high", "lower_high"], PARAMS) == pytest.approx(1.0)


def test_unweighted_signal_names_are_rejected():
    with pytest.raises(ValueError, match="unweighted deterioration"):
        exit_pressure(["astrology"], PARAMS)
