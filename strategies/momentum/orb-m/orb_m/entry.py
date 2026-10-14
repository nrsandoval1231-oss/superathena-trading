"""Opening range, breakout trigger, and frozen risk denominator.

Three rules govern this module:

1. The range freezes when the opening window closes and never moves.
2. A breakout requires a completed one-minute *close* beyond the range.  A wick
   through the level is not a signal.
3. R is fixed at entry.  Later ratcheting moves the live stop; it never
   restates the denominator that every downstream threshold is quoted in.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..athena_adapter.contracts import canonical_hash
from .constitution import Constitution
from .market import Bar


@dataclass(frozen=True)
class OpeningRange:
    high: float
    low: float
    volume: float
    frozen_at_minute: int

    def __post_init__(self) -> None:
        if self.high <= 0 or self.low <= 0 or self.high < self.low:
            raise ValueError("opening range must be positive and ordered")

    @property
    def width(self) -> float:
        return self.high - self.low

    @property
    def identity_hash(self) -> str:
        return canonical_hash(self)


def freeze_opening_range(bars: Sequence[Bar], constitution: Constitution) -> OpeningRange:
    """Build the range from the opening window, then seal it.

    Requires the window to be complete.  A partial window would silently
    understate the range and shift every level derived from it.
    """
    window = [bar for bar in bars if 0 <= bar.minute < constitution.opening_minutes]
    if len(window) != constitution.opening_minutes:
        raise ValueError(
            f"opening window needs {constitution.opening_minutes} bars, found {len(window)}")
    return OpeningRange(max(b.high for b in window), min(b.low for b in window),
                        sum(b.volume for b in window), constitution.opening_minutes)


@dataclass(frozen=True)
class BreakoutSignal:
    """A completed close beyond the range. Not yet a trade -- quality gates it."""

    direction: str
    signal_minute: int
    signal_close: float
    opening_range: OpeningRange
    is_reentry: bool = False

    def __post_init__(self) -> None:
        if self.direction not in {"LONG", "SHORT"}:
            raise ValueError("direction must be LONG or SHORT")
        if self.signal_minute < self.opening_range.frozen_at_minute:
            raise ValueError("a breakout cannot precede the frozen range")

    @property
    def identity_hash(self) -> str:
        return canonical_hash(self)


def detect_breakout(bars: Sequence[Bar], opening_range: OpeningRange,
                    constitution: Constitution, *, after_minute: int | None = None,
                    direction: str | None = None) -> BreakoutSignal | None:
    """First completed close beyond the range, at or after the search origin.

    ``direction`` restricts the search to one side, which is how a failed long
    and a later short remain independent attempts on the same session.
    """
    origin = opening_range.frozen_at_minute if after_minute is None else after_minute
    for bar in sorted(bars, key=lambda item: item.minute):
        if bar.minute < origin or bar.minute >= constitution.session_deadline_minute:
            continue
        if bar.close > opening_range.high and direction in (None, "LONG"):
            return BreakoutSignal("LONG", bar.minute, bar.close, opening_range)
        if bar.close < opening_range.low and direction in (None, "SHORT"):
            return BreakoutSignal("SHORT", bar.minute, bar.close, opening_range)
    return None


@dataclass(frozen=True)
class RiskFrame:
    """Entry, invalidation, and the R denominator, all fixed at entry."""

    direction: str
    entry_price: float
    stop_price: float
    risk_per_share: float
    stop_basis: str

    def __post_init__(self) -> None:
        if self.risk_per_share <= 0:
            raise ValueError("risk per share must be positive")
        if self.direction == "LONG" and self.stop_price >= self.entry_price:
            raise ValueError("a long stop must sit below entry")
        if self.direction == "SHORT" and self.stop_price <= self.entry_price:
            raise ValueError("a short stop must sit above entry")

    def r_multiple(self, price: float) -> float:
        """Signed R at ``price``, in the frozen denominator."""
        move = (price - self.entry_price) if self.direction == "LONG" else (
            self.entry_price - price)
        return move / self.risk_per_share

    def price_at_r(self, r: float) -> float:
        offset = r * self.risk_per_share
        return self.entry_price + offset if self.direction == "LONG" else (
            self.entry_price - offset)

    @property
    def identity_hash(self) -> str:
        return canonical_hash(self)


def build_risk_frame(signal: BreakoutSignal, entry_price: float, atr14: float,
                     constitution: Constitution) -> RiskFrame:
    """Place the stop at the nearer of structural and volatility invalidation.

    For a long that is ``max(ORL, entry - ATR)``: structure is respected, but a
    very wide opening range cannot manufacture an enormous R denominator.  A
    very *narrow* range has the opposite failure -- a stop inside the noise --
    so risk per share is floored at a fraction of ATR.
    """
    if atr14 <= 0:
        raise ValueError("ATR must be positive")
    floor = constitution.min_stop_atr_fraction * atr14
    if signal.direction == "LONG":
        structural, volatility = signal.opening_range.low, entry_price - atr14
        raw = max(structural, volatility)
        basis = "STRUCTURE" if raw == structural else "VOLATILITY"
        stop = min(raw, entry_price - floor)
    else:
        structural, volatility = signal.opening_range.high, entry_price + atr14
        raw = min(structural, volatility)
        basis = "STRUCTURE" if raw == structural else "VOLATILITY"
        stop = max(raw, entry_price + floor)
    if stop != raw:
        basis = "ATR_FLOOR"
    return RiskFrame(signal.direction, entry_price, stop, abs(entry_price - stop), basis)


@dataclass
class AttemptBudget:
    """One initial attempt per direction plus one continuation re-entry each.

    Enough to produce failed-breakout and reversal episodes without letting a
    chopping session generate unlimited whipsaw retries.
    """

    constitution: Constitution
    _initial: dict[str, int] = None
    _reentry: dict[str, int] = None

    def __post_init__(self) -> None:
        self._initial = {"LONG": 0, "SHORT": 0}
        self._reentry = {"LONG": 0, "SHORT": 0}

    def may_attempt(self, direction: str, *, is_reentry: bool) -> bool:
        if is_reentry:
            return self._reentry[direction] < self.constitution.max_reentries_per_direction
        return self._initial[direction] < self.constitution.max_initial_attempts_per_direction

    def record(self, direction: str, *, is_reentry: bool) -> None:
        if not self.may_attempt(direction, is_reentry=is_reentry):
            raise ValueError(f"attempt budget exhausted for {direction}")
        ledger = self._reentry if is_reentry else self._initial
        ledger[direction] += 1
