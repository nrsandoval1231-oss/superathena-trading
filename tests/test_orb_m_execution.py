"""Fill simulation. The ambiguous-bar cases are the ones that matter."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from athena_trading.orb_m.constitution import Constitution, ManagementParameters
from athena_trading.orb_m.entry import BreakoutSignal, OpeningRange
from athena_trading.orb_m.execution import run_position

BASE = datetime(2026, 3, 2, 14, 30, tzinfo=UTC)
RANGE = OpeningRange(high=101.0, low=99.0, volume=15000.0, frozen_at_minute=15)
SIGNAL = BreakoutSignal("LONG", 15, 101.2, RANGE)
# No slippage keeps the arithmetic legible; a dedicated test covers costs.
FRICTIONLESS = Constitution(slippage_bps=0.0)
PARAMS = ManagementParameters()


def bar(minute, o, h, low, c, volume=1000.0):
    from athena_trading.orb_m.market import Bar
    return Bar(BASE + timedelta(minutes=minute), minute, o, h, low, c, volume)


def run(bars, constitution=FRICTIONLESS, parameters=PARAMS, atr14=2.0, **kwargs):
    return run_position(SIGNAL, bars, atr14, constitution, parameters, **kwargs)


def test_entry_fills_on_the_bar_after_the_signal():
    # Filling at the signal bar's own close would be lookahead.
    result = run([bar(16, 101.5, 102.0, 101.4, 101.9), bar(17, 101.9, 102.0, 101.8, 101.9)])
    assert result.entry_minute == 16
    assert result.entry_price == pytest.approx(101.5)


def test_no_bars_after_the_signal_yields_no_position():
    assert run([bar(15, 101.0, 101.3, 100.9, 101.2)]) is None


def test_stop_exit_realizes_minus_one_r():
    # Entry 101.5, ATR 2.0 -> stop at max(ORL 99.0, entry - ATR 99.5) = 99.5, R = 2.0.
    bars = [bar(16, 101.5, 101.6, 101.4, 101.5), bar(17, 101.4, 101.5, 98.5, 98.8)]
    result = run(bars)
    assert result.exit_reason == "STOP"
    assert result.net_r == pytest.approx(-1.0)


def test_a_gap_through_the_stop_fills_at_the_open_not_the_stop():
    # The stop is 99.5 but the bar opens at 95.0: assuming 99.5 invents money.
    bars = [bar(16, 101.5, 101.6, 101.4, 101.5), bar(17, 95.0, 95.2, 94.0, 94.5)]
    result = run(bars)
    assert result.net_r < -1.0
    assert result.net_r == pytest.approx((95.0 - 101.5) / 2.0)


def test_ambiguous_bar_resolves_against_the_position_by_default():
    # This bar touches both the +1R harvest (103.5) and the stop (99.5).
    bars = [bar(16, 101.5, 101.6, 101.4, 101.5), bar(17, 101.5, 104.5, 98.5, 99.5)]
    result = run(bars)
    assert result.exit_reason == "STOP"
    assert result.net_r == pytest.approx(-1.0), "no harvest may be credited on a stopping bar"


def test_the_optimistic_ordering_changes_the_outcome():
    # Same bar, favorable-first: the harvest fills before the stop. The gap
    # between this and the test above is the size of the assumption.
    bars = [bar(16, 101.5, 101.6, 101.4, 101.5), bar(17, 101.5, 104.5, 98.5, 99.5)]
    result = run(bars, constitution=Constitution(slippage_bps=0.0,
                                                 intrabar_resolution="FAVORABLE_FIRST"))
    assert result.net_r > -1.0
    assert any(fill["reason"] == "FIRST_HARVEST" for fill in result.position.fills)


def test_first_harvest_banks_a_quarter_and_the_runner_continues():
    bars = [bar(16, 101.5, 101.6, 101.4, 101.5),
            bar(17, 101.5, 104.2, 101.4, 104.0),
            bar(18, 104.0, 104.1, 103.9, 104.0)]
    result = run(bars)
    fills = [fill["reason"] for fill in result.position.fills]
    assert "FIRST_HARVEST" in fills
    assert result.position.fills[0]["fraction"] == pytest.approx(0.25)


def test_momentum_harvest_adds_a_second_partial_inside_the_impulse():
    bars = [bar(16, 101.5, 101.6, 101.4, 101.5),
            bar(17, 101.5, 105.5, 101.4, 105.3),
            bar(18, 105.3, 105.4, 105.2, 105.3)]
    result = run(bars)
    reasons = [fill["reason"] for fill in result.position.fills]
    assert "FIRST_HARVEST" in reasons and "MOMENTUM_HARVEST" in reasons
    harvested = sum(f["fraction"] for f in result.position.fills
                    if f["reason"].endswith("HARVEST"))
    assert harvested == pytest.approx(0.5)


def test_position_is_flat_before_the_close():
    bars = [bar(16, 101.5, 101.6, 101.4, 101.5)] + [
        bar(m, 101.5, 101.6, 101.4, 101.5) for m in range(17, 392)]
    result = run(bars)
    assert result.exit_reason in {"SESSION_DEADLINE", "HARD_FLAT"}
    assert result.position.remaining == 0.0


def test_deterioration_pressure_can_close_the_position():
    bars = [bar(16, 101.5, 101.6, 101.4, 101.5), bar(17, 101.5, 102.0, 101.4, 101.9),
            bar(18, 101.9, 102.0, 101.8, 101.9)]
    result = run(bars, deterioration={17: 3.0})
    assert result.exit_reason == "DETERIORATION"


def test_pressure_below_the_threshold_does_not_exit():
    bars = [bar(16, 101.5, 101.6, 101.4, 101.5), bar(17, 101.5, 102.0, 101.4, 101.9),
            bar(18, 101.9, 102.0, 101.8, 101.9)]
    assert run(bars, deterioration={17: 1.0}).exit_reason != "DETERIORATION"


def test_slippage_is_charged_against_the_position_on_both_sides():
    bars = [bar(16, 101.5, 101.6, 101.4, 101.5), bar(17, 101.4, 101.5, 98.5, 98.8)]
    frictionless = run(bars).net_r
    costed = run(bars, constitution=Constitution(slippage_bps=10.0)).net_r
    assert costed < frictionless


def test_a_ratcheted_stop_exits_above_the_original_invalidation():
    # Peak 3R arms retention at 1.95R, so the pullback exits well in profit.
    bars = [bar(16, 101.5, 101.6, 101.4, 101.5),
            bar(17, 101.5, 109.0, 101.4, 108.9),
            bar(18, 108.9, 109.0, 101.0, 101.2)]
    result = run(bars)
    assert result.peak_r >= 3.0
    assert result.net_r > 0.0
    assert result.exit_reason == "STOP"


def test_commission_per_share_is_charged_against_the_position():
    bars = [bar(16, 101.5, 101.6, 101.4, 101.5), bar(17, 101.4, 101.5, 98.5, 98.8)]
    frictionless = run(bars).net_r
    costed = run(bars, constitution=Constitution(slippage_bps=0.0,
                                                commission_per_share=0.05)).net_r
    assert costed < frictionless
