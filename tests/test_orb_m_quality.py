"""Breakout Quality Score — equal-weighted components, fail closed."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from athena_trading.orb_m.constitution import BreakoutAction, ManagementParameters
from athena_trading.orb_m.entry import OpeningRange
from athena_trading.orb_m.market import Bar, PremarketContext
from athena_trading.orb_m.quality import (
    COMPONENT_NAMES, BreakoutQualityInputs, score_breakout,
)

BASE = datetime(2026, 3, 2, 14, 30, tzinfo=UTC)
PARAMS = ManagementParameters()
RANGE = OpeningRange(high=101.0, low=99.0, volume=20_000.0, frozen_at_minute=15)


def bar(minute, o, h, low, c, volume=2000.0):
    return Bar(BASE + timedelta(minutes=minute), minute, o, h, low, c, volume)


def inputs(**overrides):
    signal = bar(16, 101.1, 101.8, 101.0, 101.6, volume=5000.0)
    base = dict(
        direction="LONG",
        opening_range=RANGE,
        signal_bar=signal,
        atr14=2.0,
        opening_volume=30_000.0,
        average_opening_volume=15_000.0,
        session_vwap=100.5,
        previous_close=100.0,
        first_open=100.2,
        premarket=PremarketContext(100.4, 99.8, 5_000.0),
        market_alignment=0.4,
        sector_alignment=0.2,
    )
    base.update(overrides)
    return BreakoutQualityInputs(**base)


def test_nine_components_are_scored():
    result = score_breakout(inputs(), PARAMS)
    assert result.ok
    assert set(result.components) == set(COMPONENT_NAMES)
    assert 0.0 < result.confidence <= 1.0
    assert result.action is not BreakoutAction.PASS


def test_missing_inputs_fail_closed():
    result = score_breakout(None, PARAMS)
    assert not result.ok
    assert result.confidence == 0.0
    assert result.action is BreakoutAction.PASS
    assert result.reason == "INSUFFICIENT_INPUTS"


def test_weak_extension_and_volume_pull_confidence_down():
    strong = score_breakout(inputs(), PARAMS).confidence
    weak = score_breakout(inputs(
        opening_volume=1_000.0,
        average_opening_volume=20_000.0,
        signal_bar=bar(16, 101.1, 104.5, 101.0, 104.4),  # extended
        session_vwap=104.0,
    ), PARAMS).confidence
    assert weak < strong


def test_short_side_scores_without_raising():
    signal = bar(16, 98.9, 99.0, 98.2, 98.4)
    result = score_breakout(inputs(direction="SHORT", signal_bar=signal,
                                   session_vwap=99.5), PARAMS)
    assert result.ok
    assert result.components["momentum"] > 0.0


def test_optional_alignment_defaults_to_neutral_component():
    with_align = score_breakout(inputs(market_alignment=1.0), PARAMS)
    without = score_breakout(inputs(market_alignment=None, sector_alignment=None), PARAMS)
    assert without.ok
    assert without.components["market_alignment"] == pytest.approx(0.5)
    assert with_align.components["market_alignment"] > without.components["market_alignment"]
