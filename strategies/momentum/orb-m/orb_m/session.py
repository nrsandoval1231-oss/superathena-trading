"""ORB-M session runners.

Two public entry points coexist on purpose:

* ``run_full_session`` — frozen AAT / TRAINING evaluator contract. Signature and
  ``SessionResult`` shape must stay stable for ``aat_v1.outcomes``.
* ``run_symbol_session`` — campaign path with BQS qualification, named
  deterioration detectors, attempt budget, and constitutional portfolio ceilings.

``run_position`` manages a single episode. Portfolio ceilings
(``max_open_positions``, ``max_daily_loss_r``, ``max_drawdown_r``) are
constitutional and are not enforced there; ``run_symbol_session`` is where they
bite. The V1 full-session evaluator uses only completed bars from the same
instrument; no sector or market proxy is inferred when one is unavailable.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from statistics import fmean

from .constitution import BreakoutAction, Constitution, ManagementParameters
from .deterioration import DeteriorationContext, pressure_by_minute
from .entry import (
    AttemptBudget, BreakoutSignal, OpeningRange, detect_breakout,
    freeze_opening_range,
)
from .execution import ExecutionResult, run_position
from .management import exit_pressure
from .market import Bar, PriorSession, premarket_context, session_vwap
from .quality import BreakoutQualityInputs, BreakoutQualityResult, score_breakout


# ---------------------------------------------------------------------------
# Frozen AAT / TRAINING evaluator contract (do not rename or reshape lightly)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionEpisode:
    direction: str
    is_reentry: bool
    signal_minute: int
    result: ExecutionResult


@dataclass(frozen=True)
class SessionResult:
    episodes: tuple[SessionEpisode, ...]
    net_r: float
    initial_attempts: int
    reentries: int


def deterioration_by_minute(
    bars: Sequence[Bar], direction: str, opening: OpeningRange,
    parameters: ManagementParameters,
) -> dict[int, float]:
    """Compute only same-instrument, completed-bar deterioration signals."""
    ordered = sorted(
        (bar for bar in bars if bar.minute >= opening.frozen_at_minute),
        key=lambda bar: bar.minute,
    )
    pressure: dict[int, float] = {}
    seen: list[Bar] = []
    peak = None
    for bar in ordered:
        signals: list[str] = []
        prior = seen[-1] if seen else None
        prior5 = seen[-5:]
        if len(seen) >= 6 and fmean(x.volume for x in seen[-3:]) < fmean(
            x.volume for x in seen[-6:-3]
        ):
            signals.append("declining_volume")
        if prior is not None:
            if direction == "LONG" and bar.high < prior.high:
                signals.append("lower_high")
            if direction == "SHORT" and bar.low > prior.low:
                signals.append("lower_high")
            current_move = abs(bar.close - bar.open)
            prior_move = abs(prior.close - prior.open)
            if prior_move > 0 and current_move < prior_move * 0.5:
                signals.append("momentum_deceleration")
            if (direction == "LONG" and bar.close < bar.open) or (
                direction == "SHORT" and bar.close > bar.open
            ):
                signals.append("adverse_candle")
        vwap = session_vwap([item for item in bars if 0 <= item.minute <= bar.minute])
        if vwap is not None and (
            (direction == "LONG" and bar.close < vwap)
            or (direction == "SHORT" and bar.close > vwap)
        ):
            signals.append("vwap_loss")
        favorable = bar.high if direction == "LONG" else -bar.low
        if peak is not None and favorable <= peak:
            signals.append("failed_new_high")
        peak = favorable if peak is None else max(peak, favorable)
        if prior5 and (bar.high - bar.low) > 2 * fmean(x.high - x.low for x in prior5):
            signals.append("volatility_regime_shift")
        if (direction == "LONG" and bar.close < opening.high) or (
            direction == "SHORT" and bar.close > opening.low
        ):
            signals.append("failed_retest")
        pressure[bar.minute] = exit_pressure(signals, parameters)
        seen.append(bar)
    return pressure


def _exit_minute(result: ExecutionResult) -> int:
    return result.entry_minute + result.bars_held


def _reentry_signal(
    bars: Sequence[Bar], prior: SessionEpisode, opening: OpeningRange,
    parameters: ManagementParameters, constitution: Constitution,
) -> BreakoutSignal | None:
    result = prior.result
    frame = result.position.risk_frame
    peak_price = frame.price_at_r(max(0.0, result.peak_r))
    denominator = abs(peak_price - result.entry_price)
    if denominator <= 0:
        return None
    reset_seen = False
    for bar in sorted(bars, key=lambda item: item.minute):
        if bar.minute <= _exit_minute(result) or bar.minute >= constitution.session_deadline_minute:
            continue
        retracement = (
            (peak_price - bar.low) / denominator if prior.direction == "LONG"
            else (bar.high - peak_price) / denominator
        )
        if retracement >= parameters.moderate_setup_retracement_min:
            reset_seen = True
        if not reset_seen:
            continue
        if prior.direction == "LONG" and bar.close > opening.high:
            return BreakoutSignal("LONG", bar.minute, bar.close, opening, True)
        if prior.direction == "SHORT" and bar.close < opening.low:
            return BreakoutSignal("SHORT", bar.minute, bar.close, opening, True)
    return None


def run_full_session(
    opening: OpeningRange, bars: Sequence[Bar], atr14: float,
    constitution: Constitution, parameters: ManagementParameters,
) -> SessionResult:
    """Run both directions sequentially, including one qualified re-entry each.

    Public AAT contract — keep signature and ``SessionResult`` fields stable.
    """
    budget = AttemptBudget(constitution)
    episodes: list[SessionEpisode] = []
    cursor = opening.frozen_at_minute
    while len(episodes) < 4:
        candidates: list[BreakoutSignal] = []
        for direction in ("LONG", "SHORT"):
            prior = next(
                (episode for episode in reversed(episodes) if episode.direction == direction),
                None,
            )
            if prior is None and budget.may_attempt(direction, is_reentry=False):
                signal = detect_breakout(
                    bars, opening, constitution, after_minute=cursor, direction=direction,
                )
            elif (
                prior is not None
                and not prior.is_reentry
                and parameters.reentry_enabled
                and budget.may_attempt(direction, is_reentry=True)
            ):
                signal = _reentry_signal(bars, prior, opening, parameters, constitution)
                if signal is not None and signal.signal_minute < cursor:
                    signal = None
            else:
                signal = None
            if signal is not None:
                candidates.append(signal)
        if not candidates:
            break
        signal = min(candidates, key=lambda item: (item.signal_minute, item.direction))
        budget.record(signal.direction, is_reentry=signal.is_reentry)
        result = run_position(
            signal, bars, atr14, constitution, parameters,
            deterioration=deterioration_by_minute(bars, signal.direction, opening, parameters),
        )
        if result is None:
            break
        episode = SessionEpisode(signal.direction, signal.is_reentry, signal.signal_minute, result)
        episodes.append(episode)
        cursor = _exit_minute(result) + 1
        if cursor >= constitution.session_deadline_minute:
            break
    return SessionResult(
        tuple(episodes), sum(episode.result.net_r for episode in episodes),
        sum(not episode.is_reentry for episode in episodes),
        sum(episode.is_reentry for episode in episodes),
    )


# ---------------------------------------------------------------------------
# Campaign path — BQS, named deterioration, portfolio ceilings
# ---------------------------------------------------------------------------


@dataclass
class SessionRiskState:
    """Shared ledger for constitutional portfolio ceilings across symbols.

    Drawdown is measured from the session's peak realized R, not from zero: a
    green morning does not license an unbounded giveback.
    """

    open_positions: int = 0
    realized_r: float = 0.0
    peak_realized_r: float = 0.0

    @property
    def drawdown_r(self) -> float:
        return max(0.0, self.peak_realized_r - self.realized_r)

    def veto_reason(self, constitution: Constitution) -> str | None:
        if self.open_positions >= constitution.max_open_positions:
            return "MAX_OPEN_POSITIONS"
        if self.realized_r <= -constitution.max_daily_loss_r:
            return "MAX_DAILY_LOSS"
        if self.drawdown_r >= constitution.max_drawdown_r:
            return "MAX_DRAWDOWN"
        return None

    def register_open(self) -> None:
        self.open_positions += 1

    def register_close(self, net_r: float) -> None:
        if self.open_positions > 0:
            self.open_positions -= 1
        self.realized_r += net_r
        self.peak_realized_r = max(self.peak_realized_r, self.realized_r)


@dataclass(frozen=True)
class EpisodeRecord:
    signal: BreakoutSignal
    quality: BreakoutQualityResult
    result: ExecutionResult | None
    skipped_reason: str | None = None


@dataclass
class SymbolSessionResult:
    opening_range: OpeningRange
    episodes: list[EpisodeRecord] = field(default_factory=list)
    halt_reason: str | None = None

    @property
    def realized_r(self) -> float:
        return sum(
            episode.result.net_r for episode in self.episodes
            if episode.result is not None
        )


def _retracement_fraction(
    *, direction: str, entry: float, peak_r: float,
    risk_per_share: float, current_price: float,
) -> float:
    """Retracement of post-entry impulse, matching the frozen re-entry reference."""
    if peak_r <= 0 or risk_per_share <= 0:
        return 1.0
    if direction == "LONG":
        peak_price = entry + peak_r * risk_per_share
        impulse = peak_price - entry
        giveback = peak_price - current_price
    else:
        peak_price = entry - peak_r * risk_per_share
        impulse = entry - peak_price
        giveback = current_price - peak_price
    if impulse <= 0:
        return 1.0
    return max(0.0, giveback / impulse)


def _reentry_retracement_allowed(
    fraction: float, parameters: ManagementParameters,
) -> bool:
    """Strong setups tolerate a shallow reset; moderate setups need a deeper one.

    The open interval between the two bands is intentionally not tradeable —
    that mushy middle is where whipsaw re-entries concentrate.
    """
    if fraction <= parameters.strong_setup_retracement_max:
        return True
    return fraction >= parameters.moderate_setup_retracement_min


def _regular_bars(bars: Sequence[Bar]) -> list[Bar]:
    return sorted((bar for bar in bars if bar.minute >= 0), key=lambda item: item.minute)


def _opening_volume(bars: Sequence[Bar], constitution: Constitution) -> float:
    return sum(
        bar.volume for bar in bars if 0 <= bar.minute < constitution.opening_minutes
    )


def _first_open(bars: Sequence[Bar]) -> float | None:
    regular = [bar for bar in bars if bar.minute == 0]
    if not regular:
        ordered = _regular_bars(bars)
        return ordered[0].open if ordered else None
    return min(regular, key=lambda item: item.event_at).open


def quality_for(
    signal: BreakoutSignal, bars: Sequence[Bar], prior: PriorSession,
    constitution: Constitution, parameters: ManagementParameters, *,
    market_alignment: float | None = None,
    sector_alignment: float | None = None,
) -> BreakoutQualityResult:
    signal_bars = [bar for bar in bars if bar.minute == signal.signal_minute]
    if not signal_bars:
        return score_breakout(None, parameters)
    signal_bar = signal_bars[-1]
    through_signal = [bar for bar in bars if 0 <= bar.minute <= signal.signal_minute]
    vwap = session_vwap(through_signal)
    first_open = _first_open(bars)
    if vwap is None or first_open is None:
        return score_breakout(None, parameters)
    try:
        inputs = BreakoutQualityInputs(
            direction=signal.direction,
            opening_range=signal.opening_range,
            signal_bar=signal_bar,
            atr14=prior.atr14,
            opening_volume=_opening_volume(bars, constitution),
            average_opening_volume=prior.average_opening_volume,
            session_vwap=vwap,
            previous_close=prior.previous_close,
            first_open=first_open,
            premarket=premarket_context(bars),
            market_alignment=market_alignment,
            sector_alignment=sector_alignment,
        )
    except ValueError:
        return score_breakout(None, parameters)
    return score_breakout(inputs, parameters)


def _next_signal(
    bars: Sequence[Bar], opening_range: OpeningRange,
    constitution: Constitution, budget: AttemptBudget, *,
    direction: str, after_minute: int,
    is_reentry: bool,
) -> BreakoutSignal | None:
    if not budget.may_attempt(direction, is_reentry=is_reentry):
        return None
    found = detect_breakout(
        bars, opening_range, constitution,
        after_minute=after_minute, direction=direction,
    )
    if found is None:
        return None
    if is_reentry:
        return BreakoutSignal(
            found.direction, found.signal_minute, found.signal_close,
            found.opening_range, is_reentry=True,
        )
    return found


def run_symbol_session(
    bars: Sequence[Bar],
    prior: PriorSession,
    constitution: Constitution,
    parameters: ManagementParameters,
    *,
    risk: SessionRiskState | None = None,
    market_alignment: float | None = None,
    sector_alignment: float | None = None,
    market_alignment_by_minute: dict[int, float] | None = None,
    sector_alignment_by_minute: dict[int, float] | None = None,
) -> SymbolSessionResult:
    """Run one symbol through one session under constitutional ceilings.

    Both directions stay live and share the attempt budget. A failed long does
    not spend the short budget, and vice versa. This runner never grants
    live-money authority — it only simulates episodes against supplied bars.
    """
    ledger = risk if risk is not None else SessionRiskState()
    opening_range = freeze_opening_range(bars, constitution)
    result = SymbolSessionResult(opening_range=opening_range)
    budget = AttemptBudget(constitution)
    cursor = {
        "LONG": opening_range.frozen_at_minute,
        "SHORT": opening_range.frozen_at_minute,
    }
    last_episode: dict[str, EpisodeRecord] = {}

    while True:
        veto = ledger.veto_reason(constitution)
        if veto is not None:
            result.halt_reason = veto
            break

        candidates: list[BreakoutSignal] = []
        rejected_reentry = False
        for direction in ("LONG", "SHORT"):
            initial = _next_signal(
                bars, opening_range, constitution, budget, direction=direction,
                after_minute=cursor[direction], is_reentry=False,
            )
            if initial is not None:
                candidates.append(initial)

            if not parameters.reentry_enabled or direction not in last_episode:
                continue
            prior_episode = last_episode[direction]
            if prior_episode.result is None or prior_episode.skipped_reason:
                continue
            if not budget.may_attempt(direction, is_reentry=True):
                continue
            exit_minute = prior_episode.result.position.fills[-1]["minute"]
            reentry = _next_signal(
                bars, opening_range, constitution, budget, direction=direction,
                after_minute=max(cursor[direction], exit_minute + 1),
                is_reentry=True,
            )
            if reentry is None:
                continue
            frame = prior_episode.result.position.risk_frame
            frac = _retracement_fraction(
                direction=direction,
                entry=prior_episode.result.entry_price,
                peak_r=prior_episode.result.peak_r,
                risk_per_share=frame.risk_per_share,
                current_price=reentry.signal_close,
            )
            if not _reentry_retracement_allowed(frac, parameters):
                cursor[direction] = reentry.signal_minute + 1
                rejected_reentry = True
                continue
            candidates.append(reentry)

        if not candidates:
            if rejected_reentry:
                continue
            break

        signal = min(candidates, key=lambda item: (item.signal_minute, item.direction))
        cursor[signal.direction] = signal.signal_minute + 1

        quality = quality_for(
            signal, bars, prior, constitution, parameters,
            market_alignment=market_alignment, sector_alignment=sector_alignment,
        )

        if not quality.ok or quality.action is BreakoutAction.PASS:
            record = EpisodeRecord(
                signal, quality, None,
                skipped_reason=quality.reason or "PASS",
            )
            result.episodes.append(record)
            if budget.may_attempt(signal.direction, is_reentry=signal.is_reentry):
                budget.record(signal.direction, is_reentry=signal.is_reentry)
            last_episode[signal.direction] = record
            continue

        veto = ledger.veto_reason(constitution)
        if veto is not None:
            result.halt_reason = veto
            result.episodes.append(
                EpisodeRecord(signal, quality, None, skipped_reason=veto)
            )
            break

        if not budget.may_attempt(signal.direction, is_reentry=signal.is_reentry):
            result.episodes.append(EpisodeRecord(
                signal, quality, None, skipped_reason="ATTEMPT_BUDGET",
            ))
            break

        budget.record(signal.direction, is_reentry=signal.is_reentry)
        ledger.register_open()

        det_context = DeteriorationContext(
            direction=signal.direction,
            entry_minute=signal.signal_minute + 1,
            entry_price=signal.signal_close,
            opening_range=opening_range,
            market_alignment_by_minute=market_alignment_by_minute,
            sector_alignment_by_minute=sector_alignment_by_minute,
        )
        pressure = pressure_by_minute(bars, det_context, parameters)
        execution = run_position(
            signal, bars, prior.atr14, constitution, parameters,
            deterioration=pressure,
        )

        if execution is None:
            ledger.register_close(0.0)
            record = EpisodeRecord(signal, quality, None, skipped_reason="NO_FILL")
            result.episodes.append(record)
            last_episode[signal.direction] = record
            continue

        ledger.register_close(execution.net_r)
        record = EpisodeRecord(signal, quality, execution)
        result.episodes.append(record)
        last_episode[signal.direction] = record
        cursor[signal.direction] = max(
            cursor[signal.direction],
            execution.position.fills[-1]["minute"] + 1 if execution.position.fills
            else signal.signal_minute + 1,
        )

    return result
