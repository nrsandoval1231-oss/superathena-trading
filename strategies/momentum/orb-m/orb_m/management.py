"""APDE state, the dynamic staircase trail, and deterioration pressure.

Pure decision logic: no bars are walked here, so every rule below can be tested
in isolation from fill simulation.

The trail is the maximum of every applicable floor, and it ratchets toward
profit only.  Combining the staircase with peak retention is deliberate -- a
bare retention rule ejects on ordinary noise, and a bare staircase surrenders
an exceptional winner's whole round trip.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from ..athena_adapter.contracts import canonical_hash
from .constitution import BreakoutAction, Constitution, ManagementParameters, TrailStage
from .entry import RiskFrame


def stage_for(peak_r: float, parameters: ManagementParameters) -> TrailStage:
    """Stages advance on peak favorable excursion, never on the current price.

    Using peak rather than current R is what makes the ratchet monotonic: a
    pullback cannot demote a trade to an earlier, looser stage.
    """
    if peak_r >= parameters.trend_ride_r:
        return TrailStage.TREND_RIDE
    if peak_r >= parameters.profit_lock_r:
        return TrailStage.PROFIT_LOCK
    if peak_r >= parameters.free_trade_r:
        return TrailStage.FREE_TRADE
    if peak_r >= parameters.protect_r:
        return TrailStage.PROTECT
    return TrailStage.RISK


_STAGE_FLOOR = {
    TrailStage.RISK: "risk_stop_r",
    TrailStage.PROTECT: "protect_stop_r",
    TrailStage.FREE_TRADE: "free_trade_stop_r",
    TrailStage.PROFIT_LOCK: "profit_lock_stop_r",
}


def trail_stop_r(peak_r: float, parameters: ManagementParameters, *,
                 atr_in_r: float | None = None) -> float:
    """Highest applicable stop floor, in R.

    Three floors compete: the staircase stage, peak retention once it arms, and
    an ATR-width trail while riding a trend.  The widest protection wins.
    """
    stage = stage_for(peak_r, parameters)
    if stage is TrailStage.TREND_RIDE:
        floor = parameters.profit_lock_stop_r
    else:
        floor = getattr(parameters, _STAGE_FLOOR[stage])
    floors = [floor]
    if peak_r >= parameters.peak_retention_arms_at_r:
        floors.append(peak_r * parameters.peak_retention)
    if stage is TrailStage.TREND_RIDE and atr_in_r is not None:
        floors.append(peak_r - parameters.atr_trail_multiple * atr_in_r)
    return max(floors)


def action_for(confidence: float, parameters: ManagementParameters) -> BreakoutAction:
    """Map a breakout quality score onto the four permitted actions."""
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be within [0, 1]")
    if confidence < parameters.pass_below:
        return BreakoutAction.PASS
    if confidence > parameters.high_conviction_above:
        return BreakoutAction.HIGH_CONVICTION
    if confidence > parameters.standard_above:
        return BreakoutAction.STANDARD
    return BreakoutAction.REDUCED


def exit_pressure(signals: Sequence[str], parameters: ManagementParameters) -> float:
    """Weighted deterioration total. Unknown signal names are rejected loudly."""
    weights: Mapping[str, float] = parameters.deterioration_weights
    unknown = set(signals) - set(weights)
    if unknown:
        raise ValueError(f"unweighted deterioration signals: {sorted(unknown)}")
    return sum(weights[name] for name in set(signals))


@dataclass
class PositionState:
    """Live position. ``remaining`` is the unharvested fraction of the original."""

    risk_frame: RiskFrame
    entry_minute: int
    constitution: Constitution
    parameters: ManagementParameters
    remaining: float = 1.0
    realized_r: float = 0.0
    peak_r: float = 0.0
    trough_r: float = 0.0
    stop_r: float = None
    first_harvest_done: bool = False
    momentum_harvest_done: bool = False
    closed_reason: str | None = None
    fills: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.stop_r is None:
            self.stop_r = self.parameters.risk_stop_r

    @property
    def stage(self) -> TrailStage:
        return stage_for(self.peak_r, self.parameters)

    @property
    def is_open(self) -> bool:
        return self.remaining > 0 and self.closed_reason is None

    @property
    def stop_price(self) -> float:
        return self.risk_frame.price_at_r(self.stop_r)

    def observe(self, favorable_r: float, adverse_r: float) -> None:
        """Record excursions for this bar, then ratchet the stop.

        The stop is never widened: an updated floor below the current stop is
        discarded rather than applied.
        """
        self.peak_r = max(self.peak_r, favorable_r)
        self.trough_r = min(self.trough_r, adverse_r)
        atr_in_r = getattr(self, "_atr_in_r", None)
        self.stop_r = max(self.stop_r, trail_stop_r(self.peak_r, self.parameters,
                                                    atr_in_r=atr_in_r))

    def set_atr_in_r(self, atr_in_r: float) -> None:
        """ATR expressed in the frozen R denominator, for the trend trail."""
        if atr_in_r <= 0:
            raise ValueError("ATR in R must be positive")
        self._atr_in_r = atr_in_r

    def due_harvests(self, current_r: float, minute: int) -> list[tuple[str, float]]:
        """Harvests earned at ``current_r``, most valuable first.

        The momentum harvest is available only inside the impulse window: its
        premise is unusual velocity during price discovery, not a second target.
        """
        due: list[tuple[str, float]] = []
        if not self.first_harvest_done and current_r >= self.parameters.first_harvest_r:
            due.append(("FIRST_HARVEST", self.parameters.first_harvest_fraction))
        within_impulse = minute <= self.entry_minute + self.parameters.explore_minutes
        if (not self.momentum_harvest_done and within_impulse
                and current_r >= self.parameters.momentum_harvest_velocity_r
                and self.parameters.momentum_harvest_fraction > 0):
            due.append(("MOMENTUM_HARVEST", self.parameters.momentum_harvest_fraction))
        return due

    def reduce(self, fraction: float, exit_r: float, minute: int, reason: str) -> float:
        """Close ``fraction`` of the original position and bank its R.

        Returns the fraction actually closed, which is clamped to what remains.
        """
        if fraction <= 0:
            raise ValueError("harvest fraction must be positive")
        closed = min(fraction, self.remaining)
        if closed <= 0:
            return 0.0
        self.remaining -= closed
        self.realized_r += closed * exit_r
        self.fills.append({"minute": minute, "fraction": closed, "exit_r": exit_r,
                           "reason": reason, "stage": self.stage.value})
        if reason == "FIRST_HARVEST":
            self.first_harvest_done = True
        elif reason == "MOMENTUM_HARVEST":
            self.momentum_harvest_done = True
        if self.remaining <= 1e-9:
            self.remaining = 0.0
            self.closed_reason = reason
        return closed

    def close(self, exit_r: float, minute: int, reason: str) -> None:
        if self.remaining > 0:
            self.reduce(self.remaining, exit_r, minute, reason)
        self.closed_reason = reason

    @property
    def identity_hash(self) -> str:
        return canonical_hash({
            "risk_frame": self.risk_frame.identity_hash,
            "entry_minute": self.entry_minute,
            "realized_r": self.realized_r,
            "peak_r": self.peak_r,
            "trough_r": self.trough_r,
            "closed_reason": self.closed_reason,
            "fills": tuple(tuple(sorted(fill.items())) for fill in self.fills),
        })
