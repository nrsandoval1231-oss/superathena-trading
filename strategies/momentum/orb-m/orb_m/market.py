"""Session bars and point-in-time features for ORB-M.

Every value here is computed from bars whose ``available_at`` is at or before
the moment it is used.  Nothing reads a future bar.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from statistics import fmean
from collections.abc import Sequence

MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)


@dataclass(frozen=True)
class Bar:
    """One completed minute. ``minute`` is minutes elapsed since 09:30 ET."""

    event_at: datetime
    minute: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float | None = None
    transactions: int | None = None

    def __post_init__(self) -> None:
        if self.event_at.tzinfo is None or self.event_at.utcoffset() is None:
            raise ValueError("bar timestamps must be timezone-aware")
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("bar prices must be positive")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("bar high/low do not contain open/close")
        if self.volume < 0:
            raise ValueError("bar volume cannot be negative")

    @property
    def is_regular_hours(self) -> bool:
        return 0 <= self.minute < 390

    @property
    def typical_price(self) -> float:
        return (self.high + self.low + self.close) / 3


def true_range(bar: Bar, previous_close: float | None) -> float:
    """Wilder true range. Falls back to the bar range when no prior close exists.

    The distinction matters for an opening-range strategy: overnight gaps are
    exactly the volatility a plain high-minus-low average discards.
    """
    span = bar.high - bar.low
    if previous_close is None:
        return span
    return max(span, abs(bar.high - previous_close), abs(bar.low - previous_close))


def average_true_range(daily: Sequence[tuple[float, float, float]], periods: int = 14) -> float:
    """ATR over (high, low, close) daily tuples, most recent last."""
    if len(daily) < periods + 1:
        raise ValueError(f"ATR needs {periods + 1} sessions, received {len(daily)}")
    ranges = []
    for index in range(len(daily) - periods, len(daily)):
        high, low, close = daily[index]
        previous_close = daily[index - 1][2]
        ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    return fmean(ranges)


def session_vwap(bars: Sequence[Bar]) -> float | None:
    """Volume-weighted average price over the bars supplied, and only those."""
    volume = sum(bar.volume for bar in bars)
    if volume <= 0:
        return None
    return sum(bar.typical_price * bar.volume for bar in bars) / volume


@dataclass(frozen=True)
class PriorSession:
    """Point-in-time context known before the open."""

    previous_close: float
    atr14: float
    average_daily_volume: float
    average_opening_volume: float

    def __post_init__(self) -> None:
        if self.previous_close <= 0 or self.atr14 <= 0:
            raise ValueError("prior session context must be positive")
        if self.average_daily_volume <= 0 or self.average_opening_volume <= 0:
            raise ValueError("prior volume averages must be positive")


@dataclass(frozen=True)
class PremarketContext:
    high: float | None
    low: float | None
    volume: float


def premarket_context(bars: Sequence[Bar]) -> PremarketContext:
    """Summarize bars before 09:30. Absent premarket trade is not an error."""
    early = [bar for bar in bars if bar.minute < 0]
    if not early:
        return PremarketContext(None, None, 0.0)
    return PremarketContext(max(b.high for b in early), min(b.low for b in early),
                            sum(b.volume for b in early))


def gap_percent(first_open: float, previous_close: float) -> float:
    if previous_close <= 0:
        raise ValueError("previous close must be positive")
    return (first_open - previous_close) / previous_close * 100.0


def relative_volume(opening_volume: float, average_opening_volume: float) -> float:
    if average_opening_volume <= 0:
        raise ValueError("average opening volume must be positive")
    return opening_volume / average_opening_volume
