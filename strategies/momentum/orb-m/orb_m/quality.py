"""Breakout Quality Score (BQS) — nine-component confidence for qualification.

``action_for`` already maps a confidence onto PASS / REDUCED / STANDARD /
HIGH_CONVICTION.  This module is the missing producer of that confidence.

The score is intentionally equal-weighted and uncalibrated: real feature
distributions are not yet measured against campaign data, so inventing a
sophisticated weighting would dress a guess as knowledge.  Equal weights are
the honest starting point; Athena may adapt component emphasis later on the
adaptive surface once evidence exists.

Fail closed: if any required input is missing or inconsistent, the result is
``ok=False`` with confidence 0.0 and action PASS.  A trade must not proceed on
an incomplete picture.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ..athena_adapter.contracts import canonical_hash
from .constitution import BreakoutAction, ManagementParameters
from .entry import OpeningRange
from .management import action_for
from .market import Bar, PremarketContext, gap_percent, relative_volume


#: Nine components named in ORB-Momentum v1.0 qualification.
COMPONENT_NAMES: tuple[str, ...] = (
    "structure",
    "relative_volume",
    "momentum",
    "vwap",
    "gap_premarket",
    "market_alignment",
    "volatility_quality",
    "extension_risk",
    "false_breakout_risk",
)


@dataclass(frozen=True)
class BreakoutQualityInputs:
    """Point-in-time inputs known at the signal bar's close.

    ``market_alignment`` and ``sector_alignment`` are optional signed scores in
    ``[-1, 1]`` (positive favors the trade).  When omitted they contribute a
    neutral 0.5 rather than failing the whole score — they often arrive from a
    separate feed.  Everything else is required; absence fails closed.
    """

    direction: str
    opening_range: OpeningRange
    signal_bar: Bar
    atr14: float
    opening_volume: float
    average_opening_volume: float
    session_vwap: float
    previous_close: float
    first_open: float
    premarket: PremarketContext | None = None
    market_alignment: float | None = None
    sector_alignment: float | None = None

    def __post_init__(self) -> None:
        if self.direction not in {"LONG", "SHORT"}:
            raise ValueError("direction must be LONG or SHORT")
        if self.atr14 <= 0:
            raise ValueError("ATR must be positive")
        if self.opening_volume < 0 or self.average_opening_volume <= 0:
            raise ValueError("opening volume inputs are invalid")
        if self.session_vwap <= 0 or self.previous_close <= 0 or self.first_open <= 0:
            raise ValueError("price context must be positive")
        if self.market_alignment is not None and not -1.0 <= self.market_alignment <= 1.0:
            raise ValueError("market_alignment must be within [-1, 1]")
        if self.sector_alignment is not None and not -1.0 <= self.sector_alignment <= 1.0:
            raise ValueError("sector_alignment must be within [-1, 1]")


@dataclass(frozen=True)
class BreakoutQualityResult:
    """Outcome of scoring.  ``ok`` is False when inputs were insufficient."""

    ok: bool
    confidence: float
    action: BreakoutAction
    components: Mapping[str, float]
    reason: str | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be within [0, 1]")
        object.__setattr__(self, "components", dict(self.components))

    @property
    def identity_hash(self) -> str:
        return canonical_hash({
            "ok": self.ok,
            "confidence": self.confidence,
            "action": self.action.value,
            "components": dict(sorted(self.components.items())),
            "reason": self.reason,
        })


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _structure(width: float, atr14: float) -> float:
    """Prefer an opening range that is neither noise nor a multi-ATR canyon."""
    ratio = width / atr14
    if ratio < 0.25:
        return 0.15
    if ratio < 0.5:
        return 0.45
    if ratio <= 2.0:
        return 0.85
    if ratio <= 3.0:
        return 0.55
    return 0.25


def _relative_volume_score(rvol: float) -> float:
    if rvol < 1.0:
        return _clamp01(0.35 * rvol)
    return _clamp01(0.55 + 0.225 * min(rvol - 1.0, 2.0))


def _momentum(bar: Bar, direction: str) -> float:
    span = bar.high - bar.low
    if span <= 0:
        return 0.0
    body = bar.close - bar.open
    signed = body if direction == "LONG" else -body
    close_loc = ((bar.close - bar.low) / span if direction == "LONG"
                 else (bar.high - bar.close) / span)
    return _clamp01(0.5 * _clamp01(0.5 + signed / span) + 0.5 * close_loc)


def _vwap_score(close: float, vwap: float, direction: str, atr14: float) -> float:
    separation = (close - vwap) if direction == "LONG" else (vwap - close)
    if separation <= 0:
        return _clamp01(0.35 + separation / atr14)
    return _clamp01(0.65 + 0.2 * min(separation / atr14, 1.5))


def _gap_premarket(direction: str, first_open: float, previous_close: float,
                   premarket: PremarketContext | None) -> float:
    gap = gap_percent(first_open, previous_close)
    aligned = gap if direction == "LONG" else -gap
    base = _clamp01(0.5 + aligned / 4.0)  # ~2% gap -> strong alignment
    if premarket is None or premarket.high is None or premarket.low is None:
        return base
    pm_mid = (premarket.high + premarket.low) / 2.0
    pm_bias = (pm_mid - previous_close) / previous_close * 100.0
    pm_aligned = pm_bias if direction == "LONG" else -pm_bias
    return _clamp01(0.6 * base + 0.4 * _clamp01(0.5 + pm_aligned / 4.0))


def _alignment(value: float | None) -> float:
    if value is None:
        return 0.5
    return _clamp01(0.5 + 0.5 * value)


def _volatility_quality(atr14: float, price: float) -> float:
    """ATR as a fraction of price: tradable but not chaotic."""
    frac = atr14 / price
    if frac < 0.005:
        return 0.25
    if frac < 0.01:
        return 0.55
    if frac <= 0.04:
        return 0.85
    if frac <= 0.06:
        return 0.55
    return 0.25


def _extension_risk(direction: str, close: float, opening_range: OpeningRange,
                    atr14: float) -> float:
    """Penalize entries that are already extended far beyond the range."""
    if direction == "LONG":
        extension = close - opening_range.high
    else:
        extension = opening_range.low - close
    if extension <= 0:
        return 0.4
    multiples = extension / atr14
    if multiples <= 0.25:
        return 0.9
    if multiples <= 0.75:
        return 0.7
    if multiples <= 1.25:
        return 0.4
    return 0.15


def _false_breakout_risk(bar: Bar, direction: str) -> float:
    """A close near the extreme of the signal bar is cleaner than a weak poke."""
    span = bar.high - bar.low
    if span <= 0:
        return 0.0
    if direction == "LONG":
        return _clamp01((bar.close - bar.low) / span)
    return _clamp01((bar.high - bar.close) / span)


def score_breakout(inputs: BreakoutQualityInputs | None,
                   parameters: ManagementParameters) -> BreakoutQualityResult:
    """Compute BQS.  ``None`` inputs, or any failure to assemble components,
    fail closed to PASS.
    """
    if inputs is None:
        return BreakoutQualityResult(
            False, 0.0, BreakoutAction.PASS, {}, reason="INSUFFICIENT_INPUTS")
    try:
        rvol = relative_volume(inputs.opening_volume, inputs.average_opening_volume)
        # market + sector share the market_alignment slot in the nine-name list:
        # sector is folded into the same component when present.
        market = _alignment(inputs.market_alignment)
        if inputs.sector_alignment is not None:
            market = 0.5 * market + 0.5 * _alignment(inputs.sector_alignment)
        components = {
            "structure": _structure(inputs.opening_range.width, inputs.atr14),
            "relative_volume": _relative_volume_score(rvol),
            "momentum": _momentum(inputs.signal_bar, inputs.direction),
            "vwap": _vwap_score(inputs.signal_bar.close, inputs.session_vwap,
                                inputs.direction, inputs.atr14),
            "gap_premarket": _gap_premarket(
                inputs.direction, inputs.first_open, inputs.previous_close,
                inputs.premarket),
            "market_alignment": market,
            "volatility_quality": _volatility_quality(
                inputs.atr14, inputs.signal_bar.close),
            "extension_risk": _extension_risk(
                inputs.direction, inputs.signal_bar.close, inputs.opening_range,
                inputs.atr14),
            "false_breakout_risk": _false_breakout_risk(
                inputs.signal_bar, inputs.direction),
        }
    except (TypeError, ValueError, ZeroDivisionError):
        return BreakoutQualityResult(
            False, 0.0, BreakoutAction.PASS, {}, reason="INSUFFICIENT_INPUTS")

    if set(components) != set(COMPONENT_NAMES):
        return BreakoutQualityResult(
            False, 0.0, BreakoutAction.PASS, {}, reason="INSUFFICIENT_INPUTS")
    if any(value != value or not 0.0 <= value <= 1.0 for value in components.values()):
        return BreakoutQualityResult(
            False, 0.0, BreakoutAction.PASS, {}, reason="INSUFFICIENT_INPUTS")

    confidence = sum(components.values()) / len(components)
    return BreakoutQualityResult(
        True, confidence, action_for(confidence, parameters), components)
