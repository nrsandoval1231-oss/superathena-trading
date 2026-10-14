"""Deterioration detectors — produce the signal names ``exit_pressure`` weighs.

``management.exit_pressure`` and ``execution.run_position`` already consume
weighted pressure.  This module walks completed bars after entry and emits the
named signals registered in ``ManagementParameters.deterioration_weights``.

Detectors are deliberately conservative: a single noisy bar should not fire
every name.  Market/sector context is optional; those signals only appear when
the caller supplies a signed alignment series.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .entry import OpeningRange
from .management import exit_pressure
from .constitution import ManagementParameters
from .market import Bar, session_vwap


@dataclass(frozen=True)
class DeteriorationContext:
    """Position identity the detectors need beyond the bar window itself."""

    direction: str
    entry_minute: int
    entry_price: float
    opening_range: OpeningRange
    #: Optional minute -> signed alignment in [-1, 1], positive with the trade.
    market_alignment_by_minute: Mapping[int, float] | None = None
    sector_alignment_by_minute: Mapping[int, float] | None = None

    def __post_init__(self) -> None:
        if self.direction not in {"LONG", "SHORT"}:
            raise ValueError("direction must be LONG or SHORT")
        if self.entry_price <= 0:
            raise ValueError("entry price must be positive")


def _is_adverse(bar: Bar, direction: str) -> bool:
    body = bar.close - bar.open
    return body < 0 if direction == "LONG" else body > 0


def _declining_volume(window: Sequence[Bar]) -> bool:
    if len(window) < 6:
        return False
    early = window[-6:-3]
    late = window[-3:]
    early_avg = sum(bar.volume for bar in early) / 3.0
    late_avg = sum(bar.volume for bar in late) / 3.0
    return early_avg > 0 and late_avg < 0.6 * early_avg


def _failed_new_high(window: Sequence[Bar], direction: str) -> bool:
    if len(window) < 4:
        return False
    prior, recent = window[:-2], window[-2:]
    if direction == "LONG":
        return max(bar.high for bar in recent) < max(bar.high for bar in prior)
    return min(bar.low for bar in recent) > min(bar.low for bar in prior)


def _lower_high(window: Sequence[Bar], direction: str) -> bool:
    if len(window) < 5:
        return False
    highs = [bar.high for bar in window[-5:]]
    lows = [bar.low for bar in window[-5:]]
    if direction == "LONG":
        return highs[-1] < highs[-3] < highs[-5]
    return lows[-1] > lows[-3] > lows[-5]


def _vwap_loss(window: Sequence[Bar], direction: str) -> bool:
    vwap = session_vwap(window)
    if vwap is None:
        return False
    close = window[-1].close
    return close < vwap if direction == "LONG" else close > vwap


def _momentum_deceleration(window: Sequence[Bar], direction: str) -> bool:
    if len(window) < 3:
        return False
    moves = []
    for bar in window[-3:]:
        delta = bar.close - bar.open
        moves.append(delta if direction == "LONG" else -delta)
    return moves[0] > moves[1] > moves[2] and moves[0] > 0


def _adverse_candle(window: Sequence[Bar], direction: str) -> bool:
    if len(window) < 4:
        return False
    current = window[-1]
    if not _is_adverse(current, direction):
        return False
    prior = window[-4:-1]
    avg_range = sum(bar.high - bar.low for bar in prior) / 3.0
    if avg_range <= 0:
        return False
    return (current.high - current.low) >= 1.5 * avg_range


def _volatility_regime_shift(window: Sequence[Bar]) -> bool:
    if len(window) < 8:
        return False
    early = sum(bar.high - bar.low for bar in window[-8:-4]) / 4.0
    late = sum(bar.high - bar.low for bar in window[-4:]) / 4.0
    return early > 0 and late >= 2.0 * early


def _failed_retest(bar: Bar, direction: str, opening_range: OpeningRange) -> bool:
    if direction == "LONG":
        return bar.close < opening_range.high
    return bar.close > opening_range.low


def _alignment_flip(value: float | None, *, adverse_below: float = -0.25) -> bool:
    return value is not None and value <= adverse_below


def detect_signals(bars: Sequence[Bar], context: DeteriorationContext) -> list[str]:
    """Named deterioration signals active on the latest bar in ``bars``.

    ``bars`` must be the post-entry window through the bar under evaluation,
    oldest first.  Bars at or before entry are ignored.
    """
    window = [bar for bar in bars if bar.minute >= context.entry_minute]
    if not window:
        return []
    current = window[-1]
    signals: list[str] = []

    if _declining_volume(window):
        signals.append("declining_volume")
    if _failed_new_high(window, context.direction):
        signals.append("failed_new_high")
    if _lower_high(window, context.direction):
        signals.append("lower_high")
    if _vwap_loss(window, context.direction):
        signals.append("vwap_loss")
    if _momentum_deceleration(window, context.direction):
        signals.append("momentum_deceleration")
    if _adverse_candle(window, context.direction):
        signals.append("adverse_candle")
    if _volatility_regime_shift(window):
        signals.append("volatility_regime_shift")
    if _failed_retest(current, context.direction, context.opening_range):
        signals.append("failed_retest")

    if context.market_alignment_by_minute is not None:
        if _alignment_flip(context.market_alignment_by_minute.get(current.minute)):
            signals.append("market_reversal")
    if context.sector_alignment_by_minute is not None:
        if _alignment_flip(context.sector_alignment_by_minute.get(current.minute)):
            signals.append("sector_divergence")

    return signals


def pressure_by_minute(bars: Sequence[Bar], context: DeteriorationContext,
                       parameters: ManagementParameters) -> dict[int, float]:
    """Build the ``deterioration`` map ``run_position`` already accepts.

    Each minute's pressure is the weighted total of signals active on that bar,
    computed from the entry window through that minute only — no lookahead.
    """
    ordered = sorted((bar for bar in bars if bar.minute >= context.entry_minute),
                     key=lambda item: item.minute)
    pressure: dict[int, float] = {}
    history: list[Bar] = []
    for bar in ordered:
        history.append(bar)
        signals = detect_signals(history, context)
        if signals:
            pressure[bar.minute] = exit_pressure(signals, parameters)
    return pressure
