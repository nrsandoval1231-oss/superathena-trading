"""Causal paper session: walk completed bars and act.

Each bar is appended to a prefix and only that prefix is shown to ORB-M.
When a sendable close-through fires on the bar that just completed, the
existing paper path (OrderIntent, RiskHaltGate, BrokerAdapter) submits an
entry. Harvests, trails, and flatten stay engine-side: ``run_position`` is
consulted on the arrived prefix so the halt ledger can register a close, but
those exits are not sent to the broker. ``DATA_EXHAUSTED`` on a live prefix
is ignored — the engine-side position is still open.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..execution.authority import ExecutionAuthority
from ..execution.broker import BrokerAdapter
from ..execution.intent import PaperDecision, order_intent_from_decision
from ..orb_m.constitution import BreakoutAction, Constitution, ManagementParameters
from ..orb_m.deterioration import DeteriorationContext, pressure_by_minute
from ..orb_m.entry import AttemptBudget, BreakoutSignal, OpeningRange, freeze_opening_range
from ..orb_m.execution import run_position
from ..orb_m.market import Bar, PriorSession
from ..orb_m.quality import BreakoutQualityResult
from ..orb_m.session import (
    EpisodeRecord, SessionRiskState, _next_signal, _reentry_retracement_allowed,
    _retracement_fraction, quality_for,
)
from ..risk.halt import HaltDecision, RiskHaltGate, send_gated
from .bars import DEFAULT_BARS_PATH, BarSession, load_bar_session
from .demo import DEMO_CONSTITUTION, DEMO_EQUITY, DEMO_PARAMETERS
from .fixture import FixtureBroker
from .session import PaperAction, PaperSessionResult, _cancel_working

_STILL_OPEN = frozenset({"DATA_EXHAUSTED", "OPEN"})


@dataclass
class _Shadow:
    signal: BreakoutSignal
    quality: BreakoutQualityResult


def walk_paper_session(
    bars: Sequence[Bar],
    prior: PriorSession,
    *,
    symbol: str,
    constitution: Constitution,
    parameters: ManagementParameters,
    broker: BrokerAdapter,
    authority: ExecutionAuthority,
    equity: float,
    risk: SessionRiskState | None = None,
) -> PaperSessionResult:
    """Walk ``bars`` in minute order and submit entries as signals complete."""
    if equity <= 0:
        raise ValueError("equity must be positive")
    ticker = symbol.strip().upper()
    ordered = sorted(bars, key=lambda bar: (bar.minute, bar.event_at))
    ledger = risk if risk is not None else SessionRiskState()
    gate = RiskHaltGate(constitution, ledger)
    budget = AttemptBudget(constitution)
    actions: list[PaperAction] = []
    shadows: dict[str, _Shadow] = {}
    last_episode: dict[str, EpisodeRecord] = {}
    opening = None
    cursor = {"LONG": 0, "SHORT": 0}

    for index, bar in enumerate(ordered):
        prefix = ordered[: index + 1]
        if opening is None:
            window = [
                item for item in prefix
                if 0 <= item.minute < constitution.opening_minutes
            ]
            if len(window) < constitution.opening_minutes:
                continue
            opening = freeze_opening_range(prefix, constitution)
            cursor = {
                "LONG": opening.frozen_at_minute,
                "SHORT": opening.frozen_at_minute,
            }

        _resolve_shadows(
            prefix, prior, constitution, parameters, opening, ledger, shadows,
            last_episode,
        )

        if bar.minute < opening.frozen_at_minute:
            continue
        if bar.minute >= constitution.session_deadline_minute:
            break

        candidates: list[BreakoutSignal] = []
        for direction in ("LONG", "SHORT"):
            if direction in shadows:
                continue
            initial = _next_signal(
                prefix, opening, constitution, budget, direction=direction,
                after_minute=cursor[direction], is_reentry=False,
            )
            if initial is not None and initial.signal_minute <= bar.minute:
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
                prefix, opening, constitution, budget, direction=direction,
                after_minute=max(cursor[direction], exit_minute + 1),
                is_reentry=True,
            )
            if reentry is None or reentry.signal_minute > bar.minute:
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
                continue
            candidates.append(reentry)

        if not candidates:
            continue

        signal = min(candidates, key=lambda item: (item.signal_minute, item.direction))
        cursor[signal.direction] = signal.signal_minute + 1
        quality = quality_for(signal, prefix, prior, constitution, parameters)
        decision = PaperDecision(
            ticker, signal, quality, prior.atr14, signal.signal_close,
        )

        if not quality.ok or quality.action is BreakoutAction.PASS:
            record = EpisodeRecord(
                signal, quality, None, skipped_reason=quality.reason or "PASS",
            )
            if budget.may_attempt(signal.direction, is_reentry=signal.is_reentry):
                budget.record(signal.direction, is_reentry=signal.is_reentry)
            last_episode[signal.direction] = record
            continue

        if authority is not ExecutionAuthority.PAPER:
            halt = HaltDecision(False, "AUTHORITY_ABSENT")
            actions.append(PaperAction(decision, None, halt, None, bar.minute))
            return PaperSessionResult(
                tuple(actions), "AUTHORITY_ABSENT", authority,
                bars_processed=index + 1, mode="walk",
            )

        halt = gate.inspect()
        if not halt.allowed:
            actions.append(PaperAction(decision, None, halt, None, bar.minute))
            _cancel_working(broker, actions)
            return PaperSessionResult(
                tuple(actions), halt.reason, authority,
                bars_processed=index + 1, mode="walk",
            )

        if not budget.may_attempt(signal.direction, is_reentry=signal.is_reentry):
            actions.append(PaperAction(
                decision, None, HaltDecision(False, "ATTEMPT_BUDGET"), None, bar.minute,
            ))
            return PaperSessionResult(
                tuple(actions), "ATTEMPT_BUDGET", authority,
                bars_processed=index + 1, mode="walk",
            )

        try:
            intent = order_intent_from_decision(
                decision, constitution, parameters,
                equity=equity, authority=authority,
            )
        except ValueError:
            actions.append(PaperAction(
                decision, None, HaltDecision(False, "UNSIZED"), None, bar.minute,
            ))
            _cancel_working(broker, actions)
            return PaperSessionResult(
                tuple(actions), "UNSIZED", authority,
                bars_processed=index + 1, mode="walk",
            )

        halt, order = send_gated(intent, gate, broker)
        if order is None:
            actions.append(PaperAction(decision, intent, halt, None, bar.minute))
            _cancel_working(broker, actions)
            return PaperSessionResult(
                tuple(actions), halt.reason, authority,
                bars_processed=index + 1, mode="walk",
            )

        budget.record(signal.direction, is_reentry=signal.is_reentry)
        ledger.register_open()
        shadows[signal.direction] = _Shadow(signal, quality)
        last_episode[signal.direction] = EpisodeRecord(signal, quality, None)
        actions.append(PaperAction(decision, intent, halt, order, bar.minute))

    return PaperSessionResult(
        tuple(actions), None, authority,
        bars_processed=len(ordered), mode="walk",
    )


def _resolve_shadows(
    prefix: Sequence[Bar],
    prior: PriorSession,
    constitution: Constitution,
    parameters: ManagementParameters,
    opening: OpeningRange,
    ledger: SessionRiskState,
    shadows: dict[str, _Shadow],
    last_episode: dict[str, EpisodeRecord],
) -> None:
    """Apply engine-side exits that are already visible on the prefix.

    Broker-side stops are not placed. A prefix that has not yet reached an
    engine exit leaves the shadow open.
    """
    closed: list[str] = []
    for direction, shadow in shadows.items():
        context = DeteriorationContext(
            direction=shadow.signal.direction,
            entry_minute=shadow.signal.signal_minute + 1,
            entry_price=shadow.signal.signal_close,
            opening_range=opening,
        )
        pressure = pressure_by_minute(prefix, context, parameters)
        execution = run_position(
            shadow.signal, prefix, prior.atr14, constitution, parameters,
            deterioration=pressure,
        )
        if execution is None or execution.exit_reason in _STILL_OPEN:
            continue
        ledger.register_close(execution.net_r)
        last_episode[direction] = EpisodeRecord(
            shadow.signal, shadow.quality, execution,
        )
        closed.append(direction)
    for direction in closed:
        del shadows[direction]


def run_walk_fixture(
    *,
    authority: ExecutionAuthority = ExecutionAuthority.PAPER,
    halt_demo: bool = False,
    broker: BrokerAdapter | None = None,
    session: BarSession | None = None,
) -> PaperSessionResult:
    """Walk the shipped (or supplied) fixture bars. No network, no API keys."""
    recorded = session if session is not None else load_bar_session(DEFAULT_BARS_PATH)
    paper_broker = broker if broker is not None else FixtureBroker()
    risk = SessionRiskState()
    if halt_demo:
        risk = SessionRiskState(
            realized_r=-DEMO_CONSTITUTION.max_daily_loss_r,
            peak_realized_r=0.0,
        )
    return walk_paper_session(
        recorded.bars, recorded.prior,
        symbol=recorded.symbol,
        constitution=DEMO_CONSTITUTION,
        parameters=DEMO_PARAMETERS,
        broker=paper_broker,
        authority=authority,
        equity=DEMO_EQUITY,
        risk=risk,
    )
