"""Frozen strategy constitution and the bounded surface Athena may adapt.

The constitution is the part of ORB-M that Athena must not change: the opening
range, the session boundaries, the risk ceilings, and the execution semantics.
``ManagementParameters`` is the part it may change, one dimension at a time,
under Gauntlet evidence gates.

Separating the two is the whole experiment.  A run that mutates a constitution
field is not an ORB-M run and its evidence does not transfer.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any
from collections.abc import Mapping

from ..athena_adapter.contracts import canonical_hash


class BreakoutAction(StrEnum):
    PASS = "PASS"
    REDUCED = "REDUCED"
    STANDARD = "STANDARD"
    HIGH_CONVICTION = "HIGH_CONVICTION"


class TrailStage(StrEnum):
    """Ratchet stages. The stop moves toward profit only, never backward."""

    RISK = "RISK"              # pre-confirmation: original structural stop
    PROTECT = "PROTECT"        # >= protect_r: reduce allowable loss
    FREE_TRADE = "FREE_TRADE"  # >= free_trade_r: stop at breakeven / structure
    PROFIT_LOCK = "PROFIT_LOCK"  # >= profit_lock_r: protect realized-equivalent profit
    TREND_RIDE = "TREND_RIDE"  # >= trend_ride_r: structure + ATR + VWAP trail


@dataclass(frozen=True)
class Constitution:
    """Immutable. Changing any field defines a different strategy."""

    # --- Opening range -----------------------------------------------------
    opening_minutes: int = 15          # 09:30-09:45 ET, frozen at 09:45
    session_open_minute: int = 0       # minutes after 09:30
    session_deadline_minute: int = 375  # 15:45 ET; flat before the close
    hard_flat_minute: int = 389        # 15:59 ET; no overnight position, ever

    # --- Universe qualification -------------------------------------------
    price_min: float = 5.0
    adv_min: int = 1_000_000
    atr14_min: float = 0.50
    opening_rvol_min: float = 1.0
    rank_limit: int = 20

    # --- Risk ceilings (hard vetoes; Athena may only reduce) ---------------
    max_open_positions: int = 3
    max_daily_loss_r: float = 3.0
    max_drawdown_r: float = 5.0
    max_risk_per_trade_fraction: float = 0.01   # of account equity
    max_notional_fraction: float = 0.75         # of account equity, single name
    # A narrow opening range can place the structural stop within noise of the
    # entry.  A tiny R denominator inflates size and makes R-multiples
    # meaningless, so risk-per-share is floored at a fraction of ATR.
    min_stop_atr_fraction: float = 0.15

    # --- Execution semantics ----------------------------------------------
    slippage_bps: float = 2.0
    commission_per_share: float = 0.0
    # When one bar contains both a favorable and an adverse level, assume the
    # adverse level filled first.  This cannot flatter a result; the optimistic
    # alternative exists only to measure how much a result depends on the
    # assumption.
    intrabar_resolution: str = "ADVERSE_FIRST"

    # One initial attempt per direction plus one continuation re-entry per
    # direction: enough to produce failed-breakout and reversal episodes
    # without unlimited whipsaw retries.
    max_initial_attempts_per_direction: int = 1
    max_reentries_per_direction: int = 1

    version: str = "athena-orb-m-v1.0"

    def __post_init__(self) -> None:
        if self.opening_minutes < 1:
            raise ValueError("opening range must span at least one minute")
        if not self.session_open_minute < self.opening_minutes <= self.session_deadline_minute:
            raise ValueError("opening range must close before the session deadline")
        if not self.session_deadline_minute <= self.hard_flat_minute:
            raise ValueError("hard flat must not precede the session deadline")
        if min(self.price_min, self.atr14_min, self.opening_rvol_min) <= 0 or self.adv_min < 1:
            raise ValueError("universe filters must be positive")
        if self.rank_limit < 1 or self.max_open_positions < 1:
            raise ValueError("rank and position limits must be positive")
        if min(self.max_daily_loss_r, self.max_drawdown_r) <= 0:
            raise ValueError("loss ceilings must be positive")
        if not 0 < self.max_risk_per_trade_fraction <= 0.05:
            raise ValueError("per-trade risk fraction must be in (0, 0.05]")
        if not 0 < self.max_notional_fraction <= 1:
            raise ValueError("notional fraction must be in (0, 1]")
        if self.slippage_bps < 0 or self.commission_per_share < 0:
            raise ValueError("costs cannot be negative")
        if not 0 < self.min_stop_atr_fraction < 1:
            raise ValueError("minimum stop fraction must be within (0, 1)")
        if self.max_initial_attempts_per_direction < 1 or self.max_reentries_per_direction < 0:
            raise ValueError("attempt budget must permit at least one initial attempt")
        if self.intrabar_resolution not in {"ADVERSE_FIRST", "FAVORABLE_FIRST"}:
            raise ValueError("intrabar resolution must be ADVERSE_FIRST or FAVORABLE_FIRST")

    @property
    def identity_hash(self) -> str:
        return canonical_hash(self)


@dataclass(frozen=True)
class ManagementParameters:
    """The bounded surface Athena may adapt. Every field is a hypothesis.

    Defaults reconstruct the ORB-M v1.0 baseline.  They are starting points to
    be measured, not targets to be reproduced -- notably ``peak_retention``,
    which is a recollected figure and must be fitted rather than assumed.
    """

    # --- Breakout qualification thresholds --------------------------------
    pass_below: float = 0.55
    standard_above: float = 0.70
    high_conviction_above: float = 0.85

    # --- Impulse window ----------------------------------------------------
    explore_minutes: int = 8           # measurement window after entry
    protect_r: float = 0.5             # EXPLORE -> PROTECT
    free_trade_r: float = 1.0          # stop to breakeven / structure
    profit_lock_r: float = 1.5
    trend_ride_r: float = 2.0

    # Stop floor conceded at each stage, in R. The live stop is the highest
    # applicable floor and ratchets toward profit only.
    risk_stop_r: float = -1.0
    protect_stop_r: float = -0.5
    free_trade_stop_r: float = 0.0
    profit_lock_stop_r: float = 0.5

    # --- Harvest -----------------------------------------------------------
    first_harvest_r: float = 1.0
    first_harvest_fraction: float = 0.25       # 20-30% band midpoint
    momentum_harvest_fraction: float = 0.25    # additional, impulse-window only
    momentum_harvest_velocity_r: float = 1.5   # R within explore window to trigger

    # --- Runner protection -------------------------------------------------
    peak_retention: float = 0.65               # FITTED, not a target
    peak_retention_arms_at_r: float = 2.0      # below this, staircase alone governs
    atr_trail_multiple: float = 1.5

    # --- Deterioration -----------------------------------------------------
    exit_pressure_threshold: float = 2.0       # weighted signals required to exit
    deterioration_weights: Mapping[str, float] = None  # set in __post_init__

    # --- Re-entry ----------------------------------------------------------
    reentry_enabled: bool = True
    strong_setup_retracement_max: float = 0.20  # shallow reset tolerated
    moderate_setup_retracement_min: float = 0.38  # deeper reset required

    # --- Sizing ------------------------------------------------------------
    base_risk_fraction: float = 0.005          # of equity, before modifiers
    confidence_multiplier_max: float = 2.0
    regime_multiplier_max: float = 1.5

    def __post_init__(self) -> None:
        if self.deterioration_weights is None:
            object.__setattr__(self, "deterioration_weights", _DEFAULT_DETERIORATION_WEIGHTS)
        object.__setattr__(self, "deterioration_weights", dict(self.deterioration_weights))
        if not 0 < self.pass_below < self.standard_above < self.high_conviction_above < 1:
            raise ValueError("confidence thresholds must be increasing within (0, 1)")
        if self.explore_minutes < 1:
            raise ValueError("explore window must be at least one minute")
        stages = (self.protect_r, self.free_trade_r, self.profit_lock_r, self.trend_ride_r)
        if not all(a < b for a, b in zip(stages, stages[1:], strict=False)):
            raise ValueError("trail stages must be strictly increasing in R")
        if self.protect_r <= 0:
            raise ValueError("protect stage must trigger above entry")
        floors = (self.risk_stop_r, self.protect_stop_r, self.free_trade_stop_r,
                  self.profit_lock_stop_r)
        if not all(a < b for a, b in zip(floors, floors[1:], strict=False)):
            raise ValueError("stage stop floors must ratchet strictly toward profit")
        if self.risk_stop_r >= 0:
            raise ValueError("the initial stop must sit below entry")
        harvested = self.first_harvest_fraction + self.momentum_harvest_fraction
        if not 0 < self.first_harvest_fraction < 1 or not 0 <= self.momentum_harvest_fraction < 1:
            raise ValueError("harvest fractions must be within (0, 1)")
        if harvested >= 1:
            raise ValueError("harvests must leave a runner")
        if not 0 < self.peak_retention < 1:
            raise ValueError("peak retention must be within (0, 1)")
        if self.peak_retention_arms_at_r <= 0 or self.atr_trail_multiple <= 0:
            raise ValueError("retention arming and ATR multiple must be positive")
        if self.exit_pressure_threshold <= 0:
            raise ValueError("exit pressure threshold must be positive")
        if not 0 < self.strong_setup_retracement_max < self.moderate_setup_retracement_min < 1:
            raise ValueError("retracement bands must be increasing within (0, 1)")
        if not 0 < self.base_risk_fraction <= 0.02:
            raise ValueError("base risk fraction must be in (0, 0.02]")
        if self.confidence_multiplier_max < 1 or self.regime_multiplier_max < 1:
            raise ValueError("multipliers must be at least 1.0")
        if any(weight < 0 for weight in self.deterioration_weights.values()):
            raise ValueError("deterioration weights cannot be negative")

    @property
    def identity_hash(self) -> str:
        return canonical_hash({**self.__dict__, "deterioration_weights":
                               dict(sorted(self.deterioration_weights.items()))})

    def evolve(self, **changes: Any) -> ManagementParameters:
        """Produce a mutated copy, rejecting any key outside the adaptive surface."""
        unknown = set(changes) - ADAPTIVE_SURFACE
        if unknown:
            raise ValueError(f"not on the adaptive surface: {sorted(unknown)}")
        return replace(self, **changes)


_DEFAULT_DETERIORATION_WEIGHTS: Mapping[str, float] = {
    "declining_volume": 1.0,
    "failed_new_high": 1.0,
    "lower_high": 1.0,
    "vwap_loss": 1.5,
    "momentum_deceleration": 1.0,
    "sector_divergence": 0.5,
    "market_reversal": 1.0,
    "adverse_candle": 1.5,
    "volatility_regime_shift": 0.5,
    "failed_retest": 1.5,
}

#: Every field Athena is permitted to change. Anything absent is constitutional.
ADAPTIVE_SURFACE: frozenset[str] = frozenset({
    "pass_below", "standard_above", "high_conviction_above",
    "explore_minutes", "protect_r", "free_trade_r", "profit_lock_r", "trend_ride_r",
    "risk_stop_r", "protect_stop_r", "free_trade_stop_r", "profit_lock_stop_r",
    "first_harvest_r", "first_harvest_fraction", "momentum_harvest_fraction",
    "momentum_harvest_velocity_r",
    "peak_retention", "peak_retention_arms_at_r", "atr_trail_multiple",
    "exit_pressure_threshold", "deterioration_weights",
    "reentry_enabled", "strong_setup_retracement_max", "moderate_setup_retracement_min",
    "base_risk_fraction", "confidence_multiplier_max", "regime_multiplier_max",
})
