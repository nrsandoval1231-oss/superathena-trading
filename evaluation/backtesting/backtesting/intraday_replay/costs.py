"""paper-cost-scenario-v1 applied to raw fills.

Slippage is 2 bps adverse on each side, with a floor of $0.01 per share.
The unobserved spread is charged once on entry. The regulatory scenario is
$0.01 per share per side. Commission in the scenario is $0.
"""

from __future__ import annotations

from collections.abc import Sequence

from .constants import (
    REGULATORY_PER_SHARE_PER_SIDE,
    SLIPPAGE_BPS,
    SLIPPAGE_FLOOR_PER_SHARE,
    SPREAD_BPS,
    SPREAD_FLOOR_PER_SHARE,
)
from .types import ReplayRefusal


def slippage_per_share(price: float) -> float:
    """Adverse slippage for one share at ``price``, including the one-cent floor."""
    if price <= 0:
        raise ValueError("slippage price must be positive")
    return max(SLIPPAGE_FLOOR_PER_SHARE, price * SLIPPAGE_BPS / 10_000.0)


def spread_per_share(decision_price: float) -> float:
    """Unobserved-spread charge for one share, taken from the decision price."""
    if decision_price <= 0:
        raise ValueError("decision price must be positive")
    return max(SPREAD_FLOOR_PER_SHARE, decision_price * SPREAD_BPS / 10_000.0)


def scenario_cost(
    *,
    entry: float,
    exit_price: float,
    decision_price: float,
    shares: int = 1,
) -> float:
    """Full scenario for one raw entry and one raw exit."""
    if shares != 1:
        raise ValueError("replay quantity is one share")
    return _fixed_charges(decision_price, shares) + (
        slippage_per_share(entry) + slippage_per_share(exit_price)
    ) * shares


def scenario_cost_legs(
    *,
    entry: float,
    exits: Sequence[tuple[float, float]],
    decision_price: float,
    shares: int = 1,
) -> float:
    """Full scenario when the exit is several raw legs ``(price, fraction)``."""
    if shares != 1:
        raise ValueError("replay quantity is one share")
    if not exits:
        raise ValueError("an exit leg is required")
    fraction_total = sum(fraction for _, fraction in exits)
    if abs(fraction_total - 1.0) > 1e-6:
        raise ValueError("exit fractions must sum to one share")
    cost = _fixed_charges(decision_price, shares)
    cost += slippage_per_share(entry) * shares
    for price, fraction in exits:
        if fraction <= 0 or price <= 0:
            raise ValueError("exit legs must be positive")
        cost += slippage_per_share(price) * fraction * shares
    return cost


def _fixed_charges(decision_price: float, shares: int) -> float:
    spread = spread_per_share(decision_price) * shares
    regulatory = REGULATORY_PER_SHARE_PER_SIDE * shares * 2
    return spread + regulatory


def unslip(
    slipped: float,
    direction: str,
    *,
    is_entry: bool,
    slippage_bps: float,
    commission_per_share: float,
) -> float:
    """Invert the constitution fill haircut. The scenario then applies its own floor."""
    if direction not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG or SHORT")
    adverse = 1.0 if (direction == "LONG") == is_entry else -1.0
    factor = 1.0 + adverse * slippage_bps / 10_000.0
    if factor <= 0:
        raise ReplayRefusal("slippage factor is not invertible")
    return (slipped - adverse * commission_per_share) / factor


def constitution_scenario_extra(
    *,
    direction: str,
    slipped_entry: float,
    exit_legs: Sequence[tuple[float, float]],
    decision_price: float,
    slippage_bps: float,
    commission_per_share: float,
    shares: int = 1,
) -> float:
    """Charges that sit on top of the constitution's 2 bps haircut.

    The simulator already subtracted proportional slippage. This adds the
    one-cent floor when 2 bps is smaller than that floor, plus the spread and
    the regulatory cent. It does not charge 2 bps a second time.
    """
    if shares != 1:
        raise ValueError("replay quantity is one share")
    raw_entry = unslip(
        slipped_entry, direction, is_entry=True, slippage_bps=slippage_bps,
        commission_per_share=commission_per_share,
    )
    raw_exits: list[tuple[float, float]] = []
    for slipped_exit, fraction in exit_legs:
        raw_exit = unslip(
            slipped_exit, direction, is_entry=False, slippage_bps=slippage_bps,
            commission_per_share=commission_per_share,
        )
        raw_exits.append((raw_exit, fraction))
    full = scenario_cost_legs(
        entry=raw_entry, exits=raw_exits, decision_price=decision_price, shares=shares,
    )
    already = _proportional_slippage_dollars(
        raw_entry, raw_exits, slippage_bps, commission_per_share, shares,
    )
    extra = full - already
    if extra < -1e-9:
        raise ReplayRefusal("constitution haircut exceeded the cost scenario")
    return max(0.0, extra)


def _proportional_slippage_dollars(
    raw_entry: float,
    raw_exits: Sequence[tuple[float, float]],
    slippage_bps: float,
    commission_per_share: float,
    shares: int,
) -> float:
    """Dollars the constitution haircut already removed, without the scenario floor."""
    entry_haircut = (raw_entry * slippage_bps / 10_000.0 + commission_per_share) * shares
    exit_haircut = 0.0
    for price, fraction in raw_exits:
        exit_haircut += (price * slippage_bps / 10_000.0 + commission_per_share) * fraction * shares
    return entry_haircut + exit_haircut
