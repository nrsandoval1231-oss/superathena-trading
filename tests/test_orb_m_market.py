"""Point-in-time features. True range must account for gaps."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from athena_trading.orb_m.market import (
    Bar, average_true_range, gap_percent, premarket_context, relative_volume,
    session_vwap, true_range,
)

BASE = datetime(2026, 3, 2, 14, 30, tzinfo=UTC)


def bar(minute, o, h, low, c, volume=1000.0):
    return Bar(BASE + timedelta(minutes=minute), minute, o, h, low, c, volume)


def test_bar_rejects_naive_timestamps():
    with pytest.raises(ValueError, match="timezone-aware"):
        Bar(datetime(2026, 3, 2, 9, 30), 0, 100, 101, 99, 100, 1000)


def test_bar_rejects_high_low_not_containing_the_body():
    with pytest.raises(ValueError, match="do not contain"):
        bar(0, 100.0, 100.5, 99.0, 101.0)


def test_true_range_without_a_prior_close_is_the_bar_span():
    assert true_range(bar(0, 100, 101, 99, 100), None) == pytest.approx(2.0)


def test_true_range_captures_a_gap_up():
    # Span is 2, but the gap from the prior close of 90 makes the true range 11.
    assert true_range(bar(0, 100, 101, 99, 100), 90.0) == pytest.approx(11.0)


def test_true_range_captures_a_gap_down():
    assert true_range(bar(0, 100, 101, 99, 100), 110.0) == pytest.approx(11.0)


def test_average_true_range_exceeds_average_span_when_sessions_gap():
    # Every session spans 2 but each opens 10 above the last close.
    daily = [(100 + 10 * i, 98 + 10 * i, 99 + 10 * i) for i in range(15)]
    atr = average_true_range(daily, periods=14)
    spans = sum(h - low for h, low, _ in daily[-14:]) / 14
    assert spans == pytest.approx(2.0)
    assert atr > spans, "ATR must exceed mean span when sessions gap"


def test_average_true_range_requires_enough_history():
    with pytest.raises(ValueError, match="ATR needs 15 sessions"):
        average_true_range([(10, 9, 9.5)] * 5, periods=14)


def test_session_vwap_is_volume_weighted():
    bars = [bar(0, 100, 100, 100, 100, volume=1.0), bar(1, 200, 200, 200, 200, volume=3.0)]
    assert session_vwap(bars) == pytest.approx(175.0)


def test_session_vwap_is_none_without_volume():
    assert session_vwap([bar(0, 100, 100, 100, 100, volume=0.0)]) is None


def test_premarket_context_uses_only_pre_open_bars():
    bars = [bar(-30, 99, 105, 98, 100), bar(0, 100, 101, 99, 100)]
    context = premarket_context(bars)
    assert (context.high, context.low) == (105.0, 98.0)


def test_absent_premarket_is_not_an_error():
    context = premarket_context([bar(0, 100, 101, 99, 100)])
    assert context.high is None and context.volume == 0.0


def test_gap_percent_signs_correctly():
    assert gap_percent(102.0, 100.0) == pytest.approx(2.0)
    assert gap_percent(98.0, 100.0) == pytest.approx(-2.0)


def test_relative_volume_ratio():
    assert relative_volume(3000.0, 1500.0) == pytest.approx(2.0)
    with pytest.raises(ValueError, match="average opening volume"):
        relative_volume(100.0, 0.0)
