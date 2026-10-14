"""Compatibility shim over the ORB-M engine.

This module predates ``athena_trading.orb_m`` and originally carried its own
copy of the trigger, stop and retracement rules.  Two implementations of the
same specification is exactly how a strategy quietly diverges from itself, so
the logic now lives in ``orb_m`` and this module only adapts to it.

Prefer ``athena_trading.orb_m`` directly in new code.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ..orb_m.entry import BreakoutSignal, OpeningRange, build_risk_frame
from ..orb_m.constitution import Constitution


class Side(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass(frozen=True)
class OrbLevels:
    high: float
    low: float

    def __post_init__(self) -> None:
        if self.high <= self.low:
            raise ValueError("opening-range high must exceed low")

    def as_opening_range(self, *, frozen_at_minute: int = 15) -> OpeningRange:
        return OpeningRange(self.high, self.low, 0.0, frozen_at_minute)


def close_breakout(*, close: float, levels: OrbLevels) -> Side | None:
    """V1 trigger: a completed 1-minute close outside the frozen 15-minute range."""
    if close > levels.high:
        return Side.LONG
    if close < levels.low:
        return Side.SHORT
    return None


def initial_stop(*, side: Side, entry: float, atr: float, levels: OrbLevels,
                 min_distance: float) -> float:
    """Freeze initial R using the tighter of OR structure and 1x ATR.

    Delegates to the engine so both paths cannot drift apart.  ``min_distance``
    is an absolute price distance here; the engine expresses the same floor as a
    fraction of ATR, so it is converted rather than reimplemented.
    """
    if atr <= 0 or min_distance <= 0:
        raise ValueError("atr and min_distance must be positive")
    constitution = Constitution(min_stop_atr_fraction=min_distance / atr)
    signal = BreakoutSignal(side.value, constitution.opening_minutes, entry,
                            levels.as_opening_range(
                                frozen_at_minute=constitution.opening_minutes))
    return build_risk_frame(signal, entry, atr, constitution).stop_price


def retracement_fraction(*, side: Side, entry: float, peak: float,
                         current: float) -> float:
    """Retracement is measured from actual entry to peak favorable excursion."""
    impulse = (peak - entry) if side is Side.LONG else (entry - peak)
    if impulse <= 0:
        raise ValueError("peak must represent positive favorable excursion")
    giveback = (peak - current) if side is Side.LONG else (current - peak)
    return max(0.0, giveback / impulse)
