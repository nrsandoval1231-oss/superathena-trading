"""Synthetic ORB-M session used by the no-network paper dry-run.

These bars are a wiring fixture, not market data. Massive remains the
historical provider; this module does not pull from it. Demo parameters lower
the PASS threshold so a sendable decision exists — that is not a retune of the
campaign constitution.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ..orb_m.constitution import Constitution, ManagementParameters
from ..orb_m.market import Bar, PriorSession

DEMO_SYMBOL = "AAPL"
DEMO_EQUITY = 100_000.0
DEMO_CONSTITUTION = Constitution(slippage_bps=0.0)
DEMO_PARAMETERS = ManagementParameters(
    pass_below=0.10, standard_above=0.20, high_conviction_above=0.90,
)
DEMO_PRIOR = PriorSession(
    previous_close=100.0, atr14=2.0,
    average_daily_volume=5_000_000.0,
    average_opening_volume=20_000.0,
)
_BASE = datetime(2026, 3, 2, 14, 30, tzinfo=UTC)


def _bar(minute: int, open_: float, high: float, low: float, close: float,
         volume: float = 2000.0) -> Bar:
    return Bar(_BASE + timedelta(minutes=minute), minute, open_, high, low, close, volume)


def demo_bars() -> tuple[Bar, ...]:
    """Opening range plus a long close-through that the engine will take."""
    bars = []
    for minute in range(15):
        bars.append(_bar(
            minute, 100.0,
            101.0 if minute == 3 else 100.5,
            99.0 if minute == 4 else 99.5,
            100.2,
        ))
    bars.append(_bar(15, 100.5, 101.2, 100.4, 101.1))
    bars.append(_bar(16, 101.2, 101.4, 101.1, 101.3))
    bars.append(_bar(17, 101.3, 101.5, 98.0, 98.5))
    return tuple(bars)
