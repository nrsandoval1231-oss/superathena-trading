"""Deterioration detectors feed the pressure map run_position already consumes."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from athena_trading.orb_m.constitution import ManagementParameters
from athena_trading.orb_m.deterioration import (
    DeteriorationContext, detect_signals, pressure_by_minute,
)
from athena_trading.orb_m.entry import OpeningRange
from athena_trading.orb_m.market import Bar

BASE = datetime(2026, 3, 2, 14, 30, tzinfo=UTC)
PARAMS = ManagementParameters()
RANGE = OpeningRange(high=101.0, low=99.0, volume=15_000.0, frozen_at_minute=15)


def bar(minute, o, h, low, c, volume=1000.0):
    return Bar(BASE + timedelta(minutes=minute), minute, o, h, low, c, volume)


def context(**overrides):
    base = dict(direction="LONG", entry_minute=16, entry_price=101.5,
                opening_range=RANGE)
    base.update(overrides)
    return DeteriorationContext(**base)


def test_failed_retest_fires_when_close_falls_back_into_the_range():
    bars = [bar(16, 101.5, 102.0, 101.4, 101.8),
            bar(17, 101.8, 101.9, 100.5, 100.8)]
    assert "failed_retest" in detect_signals(bars, context())


def test_declining_volume_requires_a_sustained_fade():
    bars = [
        bar(16, 101.5, 102.0, 101.4, 101.8, volume=5000),
        bar(17, 101.8, 102.2, 101.7, 102.0, volume=4800),
        bar(18, 102.0, 102.3, 101.9, 102.1, volume=4700),
        bar(19, 102.1, 102.2, 101.8, 101.9, volume=1000),
        bar(20, 101.9, 102.0, 101.7, 101.8, volume=900),
        bar(21, 101.8, 101.9, 101.6, 101.7, volume=800),
    ]
    assert "declining_volume" in detect_signals(bars, context())


def test_pressure_map_is_causal_and_feeds_exit_threshold():
    # Build a window that accumulates enough named signals to clear the threshold.
    bars = [
        bar(16, 101.5, 102.5, 101.4, 102.4, volume=5000),
        bar(17, 102.4, 103.0, 102.3, 102.9, volume=4800),
        bar(18, 102.9, 103.2, 102.8, 103.1, volume=4700),
        bar(19, 103.1, 103.2, 100.5, 100.6, volume=900),   # adverse + failed retest
        bar(20, 100.6, 100.7, 100.2, 100.3, volume=800),
        bar(21, 100.3, 100.4, 99.8, 99.9, volume=700),
    ]
    pressure = pressure_by_minute(bars, context(), PARAMS)
    assert pressure
    assert max(pressure.values()) >= PARAMS.exit_pressure_threshold


def test_market_reversal_only_when_alignment_series_is_supplied():
    bars = [bar(16, 101.5, 102.0, 101.4, 101.8), bar(17, 101.8, 101.9, 101.5, 101.6)]
    assert "market_reversal" not in detect_signals(bars, context())
    with_mkt = context(market_alignment_by_minute={17: -0.8})
    assert "market_reversal" in detect_signals(bars, with_mkt)
