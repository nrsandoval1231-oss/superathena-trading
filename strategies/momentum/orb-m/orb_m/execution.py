"""Deterministic bar-walking fill simulator.

The load-bearing assumption is intra-bar ordering.  Management fires at +0.5R
and +1R inside an eight-minute window, so on one-minute bars a single bar
routinely contains both a harvest level and the stop, and OHLC cannot say which
came first.  ``ADVERSE_FIRST`` resolves every such bar against the position.  It
cannot flatter a result; ``FAVORABLE_FIRST`` exists only to measure how far a
result depends on the ordering, and a result that survives only under it is not
a result.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .constitution import Constitution, ManagementParameters
from .entry import BreakoutSignal, RiskFrame, build_risk_frame
from .management import PositionState
from .market import Bar


def fill_price(raw: float, direction: str, *, is_entry: bool,
               constitution: Constitution) -> float:
    """Apply slippage and per-share commission against the position.

    Both costs are adverse on entry and exit.  Commission is a fixed currency
    offset per share; slippage remains a proportional haircut.
    """
    adverse = 1 if (direction == "LONG") == is_entry else -1
    slipped = raw * (1 + adverse * constitution.slippage_bps / 10_000)
    return slipped + adverse * constitution.commission_per_share


def _touches_stop(bar: Bar, direction: str, stop: float) -> bool:
    return bar.low <= stop if direction == "LONG" else bar.high >= stop


def _stop_fill(bar: Bar, direction: str, stop: float) -> float:
    """A gap through the stop fills at the open, not at the stop.

    Assuming the stop price is always achievable is the most common way a
    backtest invents money it could not have kept.
    """
    if direction == "LONG":
        return min(bar.open, stop)
    return max(bar.open, stop)


def favorable_r(bar: Bar, frame: RiskFrame) -> float:
    return frame.r_multiple(bar.high if frame.direction == "LONG" else bar.low)


def adverse_r(bar: Bar, frame: RiskFrame) -> float:
    return frame.r_multiple(bar.low if frame.direction == "LONG" else bar.high)


@dataclass(frozen=True)
class ExecutionResult:
    position: PositionState
    entry_minute: int
    entry_price: float
    net_r: float
    peak_r: float
    trough_r: float
    exit_reason: str
    bars_held: int


def run_position(signal: BreakoutSignal, bars: Sequence[Bar], atr14: float,
                 constitution: Constitution, parameters: ManagementParameters,
                 *, deterioration: dict[int, float] | None = None) -> ExecutionResult | None:
    """Walk bars from the signal to the exit and return the realized outcome.

    Entry fills at the open of the bar *after* the signal bar: the signal is a
    completed close, and that close is not tradeable from inside its own bar.
    ``deterioration`` optionally supplies precomputed exit pressure per minute.
    """
    ordered = sorted((b for b in bars if b.minute > signal.signal_minute),
                     key=lambda item: item.minute)
    if not ordered:
        return None

    entry_bar = ordered[0]
    entry = fill_price(entry_bar.open, signal.direction, is_entry=True,
                       constitution=constitution)
    frame = build_risk_frame(signal, entry, atr14, constitution)
    position = PositionState(frame, entry_bar.minute, constitution, parameters)
    position.set_atr_in_r(atr14 / frame.risk_per_share)
    pressure = deterioration or {}
    adverse_first = constitution.intrabar_resolution == "ADVERSE_FIRST"

    for bar in ordered:
        if not position.is_open:
            break
        if bar.minute >= constitution.hard_flat_minute:
            _exit_at(position, bar.open, bar.minute, "HARD_FLAT", constitution)
            break

        stop = position.stop_price
        stop_hit = _touches_stop(bar, frame.direction, stop)
        harvests = position.due_harvests(favorable_r(bar, frame), bar.minute)

        # Resolve the ambiguous bar before recording excursions, so a bar that
        # stops the position out cannot first credit it with a harvest.
        if stop_hit and (adverse_first or not harvests):
            _exit_at(position, _stop_fill(bar, frame.direction, stop), bar.minute,
                     "STOP", constitution)
            break

        for reason, fraction in harvests:
            price = frame.price_at_r(
                parameters.first_harvest_r if reason == "FIRST_HARVEST"
                else parameters.momentum_harvest_velocity_r)
            filled = fill_price(price, frame.direction, is_entry=False,
                                constitution=constitution)
            position.reduce(fraction, frame.r_multiple(filled), bar.minute, reason)

        if stop_hit and position.is_open:
            _exit_at(position, _stop_fill(bar, frame.direction, stop), bar.minute,
                     "STOP", constitution)
            break

        position.observe(favorable_r(bar, frame), adverse_r(bar, frame))

        if pressure.get(bar.minute, 0.0) >= parameters.exit_pressure_threshold:
            _exit_at(position, bar.close, bar.minute, "DETERIORATION", constitution)
            break
        if bar.minute >= constitution.session_deadline_minute:
            _exit_at(position, bar.close, bar.minute, "SESSION_DEADLINE", constitution)
            break
    else:
        if position.is_open:
            _exit_at(position, ordered[-1].close, ordered[-1].minute, "DATA_EXHAUSTED",
                     constitution)

    return ExecutionResult(position, entry_bar.minute, entry, position.realized_r,
                           position.peak_r, position.trough_r,
                           position.closed_reason or "OPEN",
                           position.fills[-1]["minute"] - entry_bar.minute
                           if position.fills else 0)


def _exit_at(position: PositionState, raw: float, minute: int, reason: str,
             constitution: Constitution) -> None:
    price = fill_price(raw, position.risk_frame.direction, is_entry=False,
                       constitution=constitution)
    position.close(position.risk_frame.r_multiple(price), minute, reason)
