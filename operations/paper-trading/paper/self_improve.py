"""Offline fixture lab: mutate one management knob, seal the holdout.

The loop is a toy. It walks synthetic bars, writes generation receipts, and
keeps ``execution_authority`` at ABSENT. It does not submit orders, call a
broker or model client, read the consumed AAT-V1 holdout, or change the
paper pilot.

Roles, and nothing more than roles:

* Sol proposes a ``MutationScope``: which scalar adaptive fields may move,
  and by how much.
* A local mutator stands in for DeepSeek and applies one scoped field
  through ``ManagementParameters.evolve``.
* An Astra-style gate returns PASS, FAIL, or UNKNOWN from a precommitted
  policy. The mutator does not edit that policy.
* The Athena paper walker is the market lab. It is invoked only under
  ABSENT authority. Simulated episode R comes from ``run_symbol_session``,
  the engine the walker already consults. ``FixtureBroker`` submissions
  stay at zero.

Search sees an early burn-in fold and a later selection fold. The holdout
partition is hashed first and opened once, after the generation receipts
exist. A holdout label is not a promotion.
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from datetime import UTC, datetime, timedelta
from math import isfinite
from pathlib import Path
from typing import Any

from ..athena_adapter.contracts import canonical_hash
from ..execution.authority import AuthorityError, ExecutionAuthority
from ..orb_m.constitution import ADAPTIVE_SURFACE, Constitution, ManagementParameters
from ..orb_m.market import Bar, PriorSession
from ..orb_m.session import run_symbol_session
from .fixture import FixtureBroker
from .walk import walk_paper_session

GENERATION_SCHEMA = "athena-fixture-self-improve-generation-v1"
HOLDOUT_SCHEMA = "athena-fixture-self-improve-holdout-v1"
SUMMARY_SCHEMA = "athena-fixture-self-improve-summary-v1"
SESSION_SCHEMA = "athena-fixture-self-improve-session-v1"

EXECUTION_AUTHORITY = "ABSENT"
LAB_EQUITY = 100_000.0
# Default CLI path. Each generation seeds from the best search survivor.
# The same sealed search partition is reused. The holdout stays shut until
# every generation receipt exists.
DEFAULT_GENERATIONS = 3
# Sealed when the synthetic catalog below was fixed. Changing a bar is a new
# catalog, not a quiet edit: update this hash in the same change.
BUILTIN_CATALOG_IDENTITY = (
    "dd6c45274e25cd4a06d127d8dd1176548338f8520710a8082917dc8784b321f1"
)

ROLES = {
    "scope": "sol",
    "mutator": "local-deepseek-stand-in",
    "gate": "astra-pass-fail-unknown",
    "market_lab": "athena-trading-paper-walker",
}

_OPEN = datetime(2026, 4, 6, 14, 30, tzinfo=UTC)


class HoldoutSealError(RuntimeError):
    """Search tried to read a session that belongs to the sealed holdout."""


@dataclass(frozen=True)
class LabSession:
    """One synthetic session. ``partition`` is assigned before any mutation."""

    session_id: str
    partition: str
    symbol: str
    prior: PriorSession
    bars: tuple[Bar, ...]

    def __post_init__(self) -> None:
        if self.partition not in {"SEARCH", "HOLDOUT"}:
            raise ValueError("partition must be SEARCH or HOLDOUT")
        if not self.session_id:
            raise ValueError("session_id is required")
        if not self.bars:
            raise ValueError("session needs bars")


@dataclass(frozen=True)
class FieldStep:
    """One Sol-scoped step. The mutator may apply it, not widen it."""

    field: str
    step: float


@dataclass(frozen=True)
class MutationScope:
    """Fields the local mutator is allowed to touch, one at a time."""

    steps: tuple[FieldStep, ...]

    def __post_init__(self) -> None:
        if not self.steps:
            raise ValueError("mutation scope must name at least one field")
        sample = ManagementParameters()
        seen: set[str] = set()
        for step in self.steps:
            if step.field in seen:
                raise ValueError(f"duplicate scope field: {step.field}")
            seen.add(step.field)
            if step.field not in ADAPTIVE_SURFACE:
                raise ValueError(f"not on the adaptive surface: {step.field}")
            if isinstance(step.step, bool) or not isinstance(step.step, int | float):
                raise ValueError("step must be a finite number")
            if not isfinite(float(step.step)) or float(step.step) <= 0:
                raise ValueError("step must be a positive finite number")
            current = getattr(sample, step.field)
            if isinstance(current, Mapping):
                raise ValueError(f"{step.field} is not a scalar step")


@dataclass(frozen=True)
class GatePolicy:
    """Kill/survive rules fixed before a run. Search does not edit them.

    Search PASS requires the selection-fold mean simulated R to clear the
    parent by ``improvement_floor_r``. Ties and regressions FAIL. A sample
    shorter than ``min_closed_episodes`` is UNKNOWN and does not survive.

    The holdout gate is separate and runs after search. A small move is
    UNKNOWN. Harm at least ``holdout_harm_tolerance_r`` is FAIL. Clearing
    ``holdout_confirmation_edge_r`` is PASS. None of those labels is written
    back into the paper pilot.
    """

    min_closed_episodes: int = 2
    improvement_floor_r: float = 0.05
    holdout_min_closed_episodes: int = 1
    holdout_confirmation_edge_r: float = 0.05
    holdout_harm_tolerance_r: float = 0.05

    def __post_init__(self) -> None:
        if self.min_closed_episodes < 1 or self.holdout_min_closed_episodes < 1:
            raise ValueError("evidence minimums must be positive")
        if self.improvement_floor_r <= 0 or self.holdout_confirmation_edge_r <= 0:
            raise ValueError("improvement floors must be positive")
        if self.holdout_harm_tolerance_r <= 0:
            raise ValueError("holdout harm tolerance must be positive")


PRECOMMITTED_GATES = GatePolicy()


@dataclass(frozen=True)
class SliceMetrics:
    """Simulated episode results for one fold. Not broker P&L."""

    closed_episodes: int
    mean_r: float | None
    sum_r: float
    worst_trough_r: float | None
    session_ids: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "closed_episodes": self.closed_episodes,
            "evidence": "SIMULATED_FIXTURE",
            "mean_r": self.mean_r,
            "session_ids": list(self.session_ids),
            "sum_r": self.sum_r,
            "worst_trough_r": self.worst_trough_r,
        }


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    field: str
    before: Any
    after: Any
    legal: bool
    failure: str | None
    parameters: ManagementParameters
    fields_changed: tuple[str, ...]
    lineage: tuple[dict[str, Any], ...]


class HoldoutSeal:
    """Holdout bars plus a one-shot opener. Search never receives this object."""

    def __init__(self, sessions: tuple[LabSession, ...]) -> None:
        if not sessions or any(session.partition != "HOLDOUT" for session in sessions):
            raise ValueError("holdout seal requires holdout sessions")
        self.identity = partition_identity(sessions)
        self._sessions = sessions
        self.accesses: list[str] = []

    def open_for_sealed_evaluation(self) -> tuple[LabSession, ...]:
        if self.accesses:
            raise HoldoutSealError("holdout was already opened")
        self.accesses.append("SEALED_EVALUATION")
        return self._sessions


def default_scope() -> MutationScope:
    """Sol's default proposal: management knobs, not qualification or size.

    Pass thresholds stay on the fixture parent so synthetic bars can form
    episodes. They are not in this scope, so the loop cannot "improve" by
    loosening the gate that lets a bar count as a trade. Risk fractions and
    constitution ceilings are absent too.
    """
    return MutationScope((
        FieldStep("peak_retention", 0.10),
        FieldStep("exit_pressure_threshold", 0.5),
        FieldStep("first_harvest_fraction", 0.05),
        FieldStep("atr_trail_multiple", 0.5),
        FieldStep("explore_minutes", 2),
    ))


def lab_parent() -> ManagementParameters:
    """Parent for synthetic bars. Qualification is loose; management is baseline.

    The lowered pass thresholds match the paper demo's fixture parent. They
    are not a retune of the campaign constitution, and the default scope does
    not include them.
    """
    return ManagementParameters(
        pass_below=0.10,
        standard_above=0.20,
        high_conviction_above=0.90,
    )


def lab_constitution() -> Constitution:
    """Fixture constitution. Slippage is zero so a knob is not mixed with cost.

    Costs stay constitutional: the mutator cannot edit them. Zero slippage is
    a measurement choice for this toy, not a claim that trading is free.
    """
    return Constitution(slippage_bps=0.0)


def _prior() -> PriorSession:
    return PriorSession(
        previous_close=100.0,
        atr14=2.0,
        average_daily_volume=5_000_000.0,
        average_opening_volume=20_000.0,
    )


def _bar(day: int, minute: int, open_: float, high: float, low: float, close: float,
         volume: float = 2000.0) -> Bar:
    return Bar(
        _OPEN + timedelta(days=day, minutes=minute),
        minute, open_, high, low, close, volume,
    )


def _opening(day: int) -> list[Bar]:
    bars: list[Bar] = []
    for minute in range(15):
        bars.append(_bar(
            day, minute, 100.0,
            101.0 if minute == 3 else 100.4,
            99.0 if minute == 4 else 99.6,
            100.2,
        ))
    return bars


def _spike(day: int) -> tuple[Bar, ...]:
    """Close-through that runs past 3R and then round-trips through the trail."""
    bars = _opening(day)
    bars.extend((
        _bar(day, 15, 100.6, 101.4, 100.5, 101.3),
        _bar(day, 16, 101.3, 103.5, 101.2, 103.2),
        _bar(day, 17, 103.2, 107.6, 103.0, 107.4),
        _bar(day, 18, 107.4, 107.5, 101.0, 101.2),
        _bar(day, 19, 101.2, 101.3, 99.0, 99.2),
    ))
    return tuple(bars)


def _slow_drift(day: int) -> tuple[Bar, ...]:
    """Early search fold: a failed long that deteriorates, then a short."""
    bars = _opening(day)
    bars.append(_bar(day, 15, 100.6, 101.4, 100.5, 101.3))
    bars.append(_bar(day, 16, 101.3, 102.0, 100.8, 101.0))
    price = 101.0
    for minute in range(17, 40):
        close = round(price - 0.15, 4)
        bars.append(_bar(
            day, minute, price, round(price + 0.05, 4), round(close - 0.05, 4), close,
            volume=500,
        ))
        price = close
    return tuple(bars)


def _holdout_path(day: int) -> tuple[Bar, ...]:
    """Later path: a pause that punishes a tight trail, then a further run.

    A higher peak-retention stop can exit in the pause. The baseline trail
    stays in the trade. Search spikes never show that pause.
    """
    bars = _opening(day)
    bars.extend((
        _bar(day, 15, 100.6, 101.4, 100.5, 101.3),
        _bar(day, 16, 101.3, 105.8, 101.2, 105.6),
        _bar(day, 17, 105.6, 105.7, 104.3, 105.4),
        _bar(day, 18, 105.4, 108.4, 105.2, 108.2),
        _bar(day, 19, 108.2, 108.3, 107.8, 108.0),
    ))
    return tuple(bars)


def _builtin_sessions() -> tuple[LabSession, ...]:
    prior = _prior()
    symbol = "FIXT"
    return (
        LabSession("search-001", "SEARCH", symbol, prior, _slow_drift(0)),
        LabSession("search-002", "SEARCH", symbol, prior, _spike(1)),
        LabSession("search-003", "SEARCH", symbol, prior, _spike(2)),
        LabSession("holdout-001", "HOLDOUT", symbol, prior, _holdout_path(10)),
    )


def builtin_catalog() -> tuple[LabSession, ...]:
    """Synthetic catalog. The holdout day is after every search day."""
    sessions = _builtin_sessions()
    identity = partition_identity(sessions)
    if identity != BUILTIN_CATALOG_IDENTITY:
        raise RuntimeError("builtin fixture catalog identity drifted from the sealed hash")
    return sessions


def session_payload(session: LabSession) -> dict[str, Any]:
    return {
        "bars": [
            {
                "close": bar.close,
                "event_at": bar.event_at.isoformat(),
                "high": bar.high,
                "low": bar.low,
                "minute": bar.minute,
                "open": bar.open,
                "volume": bar.volume,
            }
            for bar in session.bars
        ],
        "partition": session.partition,
        "prior": {
            "atr14": session.prior.atr14,
            "average_daily_volume": session.prior.average_daily_volume,
            "average_opening_volume": session.prior.average_opening_volume,
            "previous_close": session.prior.previous_close,
        },
        "schema_version": SESSION_SCHEMA,
        "session_id": session.session_id,
        "symbol": session.symbol,
    }


def partition_identity(sessions: Sequence[LabSession]) -> str:
    return canonical_hash([session_payload(session) for session in sessions])


def split_catalog(
    sessions: Sequence[LabSession],
) -> tuple[tuple[LabSession, ...], HoldoutSeal]:
    """Separate search from holdout. The seal is not part of the search tuple."""
    if not sessions:
        raise ValueError("catalog is empty")
    ids = [session.session_id for session in sessions]
    if len(ids) != len(set(ids)):
        raise ValueError("session ids must be unique")
    search = tuple(session for session in sessions if session.partition == "SEARCH")
    holdout = tuple(session for session in sessions if session.partition == "HOLDOUT")
    if not search or not holdout:
        raise ValueError("catalog needs a search partition and a holdout partition")
    _assert_chronological(search)
    _assert_chronological(holdout)
    if holdout[0].bars[0].event_at <= search[-1].bars[0].event_at:
        raise ValueError("holdout must start after the search partition")
    return search, HoldoutSeal(holdout)


def _assert_chronological(sessions: Sequence[LabSession]) -> None:
    times = [session.bars[0].event_at for session in sessions]
    if times != sorted(times):
        raise ValueError("sessions must be chronological")


def walk_forward_split(
    sessions: Sequence[LabSession],
) -> tuple[tuple[LabSession, ...], tuple[LabSession, ...]]:
    """Burn-in is the earliest slice. Selection is the later remainder.

    With the builtin catalog that is one drift session, then two spikes.
    The survive gate reads the spikes only.
    """
    if len(sessions) < 2:
        raise ValueError("walk-forward search needs a burn-in session and a later session")
    cut = max(1, len(sessions) // 3)
    if cut >= len(sessions):
        cut = len(sessions) - 1
    return tuple(sessions[:cut]), tuple(sessions[cut:])


def changed_fields(before: ManagementParameters, after: ManagementParameters) -> list[str]:
    changed: list[str] = []
    for name in sorted(ADAPTIVE_SURFACE):
        left = getattr(before, name)
        right = getattr(after, name)
        if isinstance(left, Mapping):
            if dict(left) != dict(right):
                changed.append(name)
        elif left != right:
            changed.append(name)
    return changed


def _apply_step(current: Any, delta: float) -> Any:
    if isinstance(current, bool):
        return not current
    if isinstance(current, int):
        return current + int(delta)
    if isinstance(current, float):
        return round(current + delta, 10)
    raise ValueError(f"cannot step a {type(current).__name__}")


def _format_number(value: float) -> str:
    text = f"{float(value):.10f}".rstrip("0").rstrip(".")
    return text or "0"


def propose_candidates(
    parent: ManagementParameters,
    scope: MutationScope,
    generation: int,
    lineage: Sequence[Mapping[str, Any]] = (),
) -> tuple[Candidate, ...]:
    """Local mutator. Each candidate is one ``evolve`` call, or a recorded failure.

    A rejected step is not retried on a different field.
    """
    if generation < 0:
        raise ValueError("generation must be non-negative")
    base_lineage = tuple({"field": str(step["field"]), "value": step["value"]} for step in lineage)
    proposals: list[Candidate] = []
    for step in scope.steps:
        current = getattr(parent, step.field)
        directions = (1,) if isinstance(current, bool) else (1, -1)
        for direction in directions:
            delta = float(step.step) * direction
            label = "flip" if isinstance(current, bool) else (
                f"{'+' if direction > 0 else '-'}{_format_number(step.step)}"
            )
            candidate_id = f"g{generation}-{step.field}-{label}"
            try:
                updated = _apply_step(current, delta)
                if updated == current:
                    raise ValueError("step did not change the field")
                child = parent.evolve(**{step.field: updated})
            except ValueError as exc:
                proposals.append(Candidate(
                    candidate_id, step.field, current, None, False, str(exc),
                    parent, (), base_lineage,
                ))
                continue
            changed = tuple(changed_fields(parent, child))
            if changed != (step.field,):
                raise RuntimeError(
                    f"mutator changed {changed}, not only {step.field}"
                )
            rebuilt = materialize((*base_lineage, {"field": step.field, "value": updated}))
            if rebuilt.identity_hash != child.identity_hash:
                raise RuntimeError("lineage does not rebuild the candidate")
            proposals.append(Candidate(
                candidate_id, step.field, current, updated, True, None, child, changed,
                (*base_lineage, {"field": step.field, "value": updated}),
            ))
    return tuple(proposals)


def materialize(lineage: Sequence[Mapping[str, Any]]) -> ManagementParameters:
    """Rebuild a candidate from the original parent, one field per step."""
    parameters = lab_parent()
    for step in lineage:
        field = str(step["field"])
        if field not in ADAPTIVE_SURFACE:
            raise ValueError(f"not on the adaptive surface: {field}")
        parameters = parameters.evolve(**{field: step["value"]})
    return parameters


def score_sessions(
    parameters: ManagementParameters,
    sessions: Sequence[LabSession],
    *,
    partition: str,
) -> SliceMetrics:
    """Simulated net R. ``partition`` must match every session or this raises."""
    if partition not in {"SEARCH", "HOLDOUT"}:
        raise ValueError("partition must be SEARCH or HOLDOUT")
    nets: list[float] = []
    troughs: list[float] = []
    for session in sessions:
        if session.partition != partition:
            raise HoldoutSealError(
                f"refusing to score {session.session_id} as {partition}"
            )
        result = run_symbol_session(
            session.bars, session.prior, lab_constitution(), parameters,
        )
        for episode in result.episodes:
            if episode.result is None:
                continue
            nets.append(episode.result.net_r)
            troughs.append(episode.result.trough_r)
    return SliceMetrics(
        closed_episodes=len(nets),
        mean_r=(sum(nets) / len(nets)) if nets else None,
        sum_r=sum(nets),
        worst_trough_r=min(troughs) if troughs else None,
        session_ids=tuple(session.session_id for session in sessions),
    )


def judge_search(
    selection: SliceMetrics, parent_selection: SliceMetrics, policy: GatePolicy,
) -> tuple[str, str]:
    """PASS, FAIL, or UNKNOWN for the selection fold only."""
    if selection.closed_episodes < policy.min_closed_episodes:
        return "UNKNOWN", "INSUFFICIENT_EVIDENCE"
    if selection.mean_r is None or parent_selection.mean_r is None:
        return "UNKNOWN", "INSUFFICIENT_EVIDENCE"
    delta = selection.mean_r - parent_selection.mean_r
    if delta >= policy.improvement_floor_r:
        return "PASS", "BEATS_PARENT"
    return "FAIL", "DOES_NOT_BEAT_PARENT"


def judge_holdout(
    holdout: SliceMetrics, parent_holdout: SliceMetrics, policy: GatePolicy,
) -> tuple[str, str]:
    """Sealed confirmation. Does not choose the next search parent."""
    if holdout.closed_episodes < policy.holdout_min_closed_episodes:
        return "UNKNOWN", "INSUFFICIENT_EVIDENCE"
    if holdout.mean_r is None or parent_holdout.mean_r is None:
        return "UNKNOWN", "INSUFFICIENT_EVIDENCE"
    delta = holdout.mean_r - parent_holdout.mean_r
    if delta >= policy.holdout_confirmation_edge_r:
        return "PASS", "HOLDOUT_CONFIRMED"
    if delta <= -policy.holdout_harm_tolerance_r:
        return "FAIL", "HOLDOUT_HARM"
    return "UNKNOWN", "HOLDOUT_INCONCLUSIVE"


def _assert_lab_authority() -> None:
    if EXECUTION_AUTHORITY != "ABSENT":
        raise AuthorityError("fixture self-improve execution_authority must stay ABSENT")
    if any(item.value == "LIVE" for item in ExecutionAuthority):
        raise AuthorityError("LIVE execution authority is not available")


def absent_walker_proof(session: LabSession, parameters: ManagementParameters) -> dict[str, Any]:
    """Walk one fixture under ABSENT authority. Any submission aborts the lab."""
    _assert_lab_authority()
    if session.partition == "HOLDOUT":
        raise HoldoutSealError("paper walker proof cannot use a holdout session")
    broker = FixtureBroker()
    result = walk_paper_session(
        session.bars, session.prior,
        symbol=session.symbol,
        constitution=lab_constitution(),
        parameters=parameters,
        broker=broker,
        authority=ExecutionAuthority.ABSENT,
        equity=LAB_EQUITY,
    )
    if result.authority is not ExecutionAuthority.ABSENT:
        raise AuthorityError("fixture lab lost ABSENT authority")
    if broker.submissions or result.submitted:
        raise AuthorityError("fixture lab submitted an order under ABSENT authority")
    return {
        "bars_processed": result.bars_processed,
        "broker_class": type(broker).__name__,
        "execution_authority": result.authority.value,
        "halt_reason": result.halt_reason,
        "submitted_count": len(broker.submissions),
    }


def _policy_payload(policy: GatePolicy) -> dict[str, Any]:
    return {item.name: getattr(policy, item.name) for item in fields(policy)}


def _delta(selection: SliceMetrics, parent: SliceMetrics) -> float | None:
    if selection.mean_r is None or parent.mean_r is None:
        return None
    return selection.mean_r - parent.mean_r


def _candidate_record(
    candidate: Candidate,
    *,
    burn_in: SliceMetrics | None,
    selection: SliceMetrics | None,
    parent_selection: SliceMetrics,
    verdict: str,
    reason: str,
    walker: dict[str, Any] | None,
) -> dict[str, Any]:
    delta = None if selection is None else _delta(selection, parent_selection)
    return {
        "after": candidate.after,
        "before": candidate.before,
        "burn_in": None if burn_in is None else burn_in.as_dict(),
        "candidate_id": candidate.candidate_id,
        "delta_r": delta,
        "failure": candidate.failure,
        "field": candidate.field,
        "fields_changed": list(candidate.fields_changed),
        "legal": candidate.legal,
        "lineage": [dict(step) for step in candidate.lineage],
        "paper_walker": walker,
        "parameter_identity": candidate.parameters.identity_hash,
        "selection": None if selection is None else selection.as_dict(),
        "verdict": verdict,
        "verdict_reason": reason,
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _prepare_out(out_dir: str | Path) -> Path:
    out = Path(out_dir)
    if out.exists() and any(out.glob("generation-*.json")):
        raise FileExistsError("refusing to overwrite generation receipts")
    out.mkdir(parents=True, exist_ok=True)
    return out


def run_search(
    search: Sequence[LabSession],
    *,
    holdout_identity: str,
    out_dir: str | Path,
    generations: int = 1,
    scope: MutationScope | None = None,
    policy: GatePolicy | None = None,
) -> tuple[dict[str, Any], ...]:
    """Mutate and gate on search bars. This function has no holdout sessions."""
    _assert_lab_authority()
    if not holdout_identity or set(holdout_identity) - set("0123456789abcdef"):
        raise ValueError("holdout identity must be a hex hash")
    if generations < 1:
        raise ValueError("generations must be positive")
    if any(session.partition != "SEARCH" for session in search):
        raise HoldoutSealError("search received a non-search session")
    chosen_scope = scope if scope is not None else default_scope()
    chosen_policy = policy if policy is not None else PRECOMMITTED_GATES
    burn_in, selection = walk_forward_split(search)
    out = _prepare_out(out_dir)
    parent = lab_parent()
    lineage: tuple[dict[str, Any], ...] = ()
    receipts: list[dict[str, Any]] = []
    constitution = lab_constitution()
    for generation in range(generations):
        if materialize(lineage).identity_hash != parent.identity_hash:
            raise RuntimeError("search parent drifted from its lineage")
        starting_lineage = [dict(step) for step in lineage]
        parent_burn = score_sessions(parent, burn_in, partition="SEARCH")
        parent_selection = score_sessions(parent, selection, partition="SEARCH")
        if parent_selection.closed_episodes < chosen_policy.min_closed_episodes:
            raise ValueError("search partition does not meet the precommitted evidence minimum")
        walker_session = selection[0]
        parent_walker = absent_walker_proof(walker_session, parent)
        records: list[dict[str, Any]] = []
        for candidate in propose_candidates(parent, chosen_scope, generation, lineage):
            if not candidate.legal:
                records.append(_candidate_record(
                    candidate, burn_in=None, selection=None,
                    parent_selection=parent_selection,
                    verdict="FAIL", reason="ILLEGAL_MUTATION", walker=None,
                ))
                continue
            candidate_burn = score_sessions(candidate.parameters, burn_in, partition="SEARCH")
            candidate_selection = score_sessions(
                candidate.parameters, selection, partition="SEARCH",
            )
            verdict, reason = judge_search(
                candidate_selection, parent_selection, chosen_policy,
            )
            records.append(_candidate_record(
                candidate,
                burn_in=candidate_burn,
                selection=candidate_selection,
                parent_selection=parent_selection,
                verdict=verdict,
                reason=reason,
                walker=absent_walker_proof(walker_session, candidate.parameters),
            ))
        survivors = [record for record in records if record["verdict"] == "PASS"]
        killed = [record for record in records if record["verdict"] == "FAIL"]
        unknown = [record for record in records if record["verdict"] == "UNKNOWN"]
        starting_identity = parent.identity_hash
        advanced = False
        next_parent_identity = starting_identity
        next_candidate = None
        if survivors:
            best = min(
                survivors,
                key=lambda record: (
                    -float(record["selection"]["mean_r"]), record["candidate_id"],
                ),
            )
            parent = materialize(best["lineage"])
            lineage = tuple(best["lineage"])
            next_parent_identity = parent.identity_hash
            next_candidate = best["candidate_id"]
            advanced = True
        receipt = {
            "aat_v1_holdout_consumed": False,
            "alpaca_called": False,
            "candidates": records,
            "constitution_identity": constitution.identity_hash,
            "execution_authority": EXECUTION_AUTHORITY,
            "gate_policy": _policy_payload(chosen_policy),
            "gate_policy_hash": canonical_hash(_policy_payload(chosen_policy)),
            "generation": generation,
            "holdout_identity": holdout_identity,
            "killed": [record["candidate_id"] for record in killed],
            "live_enabled": False,
            "mutator": "local",
            "network_calls": False,
            "next_search_parent_candidate": next_candidate,
            "next_search_parent_identity": next_parent_identity,
            "paper_walker": parent_walker,
            "parent_burn_in": parent_burn.as_dict(),
            "parent_identity": lab_parent().identity_hash,
            "parent_lineage": starting_lineage,
            "parent_parameter_identity": starting_identity,
            "parent_selection": parent_selection.as_dict(),
            "promoted_to_paper_pilot": False,
            "roles": dict(ROLES),
            "schema_version": GENERATION_SCHEMA,
            "sealed_holdout_accessed": False,
            "search_identity": partition_identity(tuple(search)),
            "search_parent_advanced": advanced,
            "search_partition_reused": generation > 0,
            "selection_uses_holdout": False,
            "survived": [record["candidate_id"] for record in survivors],
            "typesafe_called": False,
            "unknown": [record["candidate_id"] for record in unknown],
            "walk_forward": {
                "burn_in_session_ids": [session.session_id for session in burn_in],
                "rule": "earliest max(1, n//3) sessions are burn-in; later sessions are selection",
                "selection_session_ids": [session.session_id for session in selection],
            },
        }
        receipt["readable"] = render_generation(receipt)
        path = out / f"generation-{generation:03d}.json"
        _write_json(path, receipt)
        receipts.append(receipt)
    return tuple(receipts)


def _fmt_num(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        text = f"{value:.4f}".rstrip("0").rstrip(".")
        return text or "0"
    return str(value)


def _fmt_delta(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return "—"
    sign = "+" if value > 0 else ""
    return sign + _fmt_num(float(value))


_REASON_TEXT = {
    "BEATS_PARENT": "beats parent on the selection fold",
    "DOES_NOT_BEAT_PARENT": "does not beat parent on the selection fold",
    "ILLEGAL_MUTATION": "illegal step; no second field was tried",
    "INSUFFICIENT_EVIDENCE": "too few closed episodes",
    "HOLDOUT_CONFIRMED": "confirmed on the sealed holdout",
    "HOLDOUT_HARM": "harmful on the sealed holdout",
    "HOLDOUT_INCONCLUSIVE": "inconclusive on the sealed holdout",
}


def _reason_text(reason: str) -> str:
    return _REASON_TEXT.get(reason, reason)


def _lineage_phrase(steps: Sequence[Mapping[str, Any]]) -> str:
    if not steps:
        return "lab parent"
    return " → ".join(
        f"{step['field']}={_fmt_num(step['value'])}" for step in steps
    )


def render_generation(receipt: Mapping[str, Any]) -> str:
    """One generation as a markdown table. Search receipts omit holdout bars."""
    parent_mean = receipt["parent_selection"]["mean_r"]
    seeded = _lineage_phrase(receipt.get("parent_lineage") or [])
    lines = [
        f"## Generation {receipt['generation']}",
        "",
        f"Parent selection mean R: {_fmt_num(parent_mean)}. Seed: {seeded}.",
        f"Paper walker: {receipt['paper_walker']['execution_authority']}, "
        f"{receipt['paper_walker']['broker_class']} submissions "
        f"{receipt['paper_walker']['submitted_count']}, "
        f"halt {receipt['paper_walker']['halt_reason']}.",
        "",
        "| Candidate | Field | Before | After | Search mean R | Delta | Verdict | Reason |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for record in receipt["candidates"]:
        selection = record.get("selection") or {}
        lines.append(
            "| {candidate} | {field} | {before} | {after} | {mean} | {delta} | {verdict} | {reason} |".format(
                candidate=record["candidate_id"],
                field=record["field"],
                before=_fmt_num(record["before"]),
                after=_fmt_num(record["after"]),
                mean=_fmt_num(selection.get("mean_r")),
                delta=_fmt_delta(record.get("delta_r")),
                verdict=record["verdict"],
                reason=_reason_text(str(record["verdict_reason"])),
            )
        )
    kept = receipt["next_search_parent_candidate"] or "(parent unchanged)"
    lines.extend([
        "",
        f"Survived: {', '.join(receipt['survived']) or '—'}.",
        f"Killed: {', '.join(receipt['killed']) or '—'}.",
        f"Unknown: {', '.join(receipt['unknown']) or '—'}.",
        f"Next search parent: {kept}.",
        "",
    ])
    return "\n".join(lines)


def render_holdout(holdout: Mapping[str, Any]) -> str:
    parent_mean = holdout["parent_holdout"]["mean_r"]
    lines = [
        "## Holdout",
        "",
        "Opened once after search. Baseline is the generation-0 parent, "
        f"mean R {_fmt_num(parent_mean)}.",
        "These verdicts do not choose the next search parent and do not promote a pilot.",
        "",
        "| Generation | Candidate | Lineage | Mean R | Delta | Verdict | Reason |",
        "|---|---|---|---|---|---|---|",
    ]
    for record in holdout["candidates"]:
        metrics = record.get("holdout") or {}
        lines.append(
            "| {generation} | {candidate} | {lineage} | {mean} | {delta} | {verdict} | {reason} |".format(
                generation=record["generation"],
                candidate=record["candidate_id"],
                lineage=_lineage_phrase(record.get("lineage") or []),
                mean=_fmt_num(metrics.get("mean_r")),
                delta=_fmt_delta(record.get("delta_r")),
                verdict=record["verdict"],
                reason=_reason_text(str(record["verdict_reason"])),
            )
        )
    if not holdout["candidates"]:
        lines.append("| — | — | — | — | — | — | no search survivor |")
    lines.append("")
    return "\n".join(lines)


def search_lineage_rows(receipts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Who each generation kept, using only search receipts."""
    rows: list[dict[str, Any]] = []
    previous: str | None = None
    for receipt in receipts:
        kept_id = receipt["next_search_parent_candidate"]
        kept = None
        if kept_id is not None:
            kept = next(
                record for record in receipt["candidates"]
                if record["candidate_id"] == kept_id
            )
        rows.append({
            "advanced": receipt["search_parent_advanced"],
            "after": None if kept is None else kept["after"],
            "before": None if kept is None else kept["before"],
            "delta_r": None if kept is None else kept["delta_r"],
            "field": None if kept is None else kept["field"],
            "generation": receipt["generation"],
            "kept_candidate": kept_id,
            "seeded_from": previous or "lab_parent",
            "selection_mean_r": None if kept is None else kept["selection"]["mean_r"],
        })
        if kept_id is not None:
            previous = kept_id
    return rows


def render_lineage(rows: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        "## Search lineage",
        "",
        "Each generation seeds from the best PASS survivor of the previous one. "
        "The sealed search partition is reused. Holdout labels are not an input.",
        "",
        "| Generation | Seeded from | Kept | Field | After | Selection mean R | Delta |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            "| {generation} | {seed} | {kept} | {field} | {after} | {mean} | {delta} |".format(
                generation=row["generation"],
                seed=row["seeded_from"],
                kept=row["kept_candidate"] or "(parent unchanged)",
                field=row["field"] or "—",
                after=_fmt_num(row["after"]),
                mean=_fmt_num(row["selection_mean_r"]),
                delta=_fmt_delta(row["delta_r"]),
            )
        )
    lines.append("")
    return "\n".join(lines)


def render_report(
    receipts: Sequence[Mapping[str, Any]],
    holdout: Mapping[str, Any],
    lineage: Sequence[Mapping[str, Any]],
) -> str:
    header = "\n".join([
        "# Fixture self-improve",
        "",
        "Execution authority: ABSENT. Live enabled: false. Alpaca called: false. "
        "TypeSafe called: false. AAT-V1 holdout consumed: false. "
        "Promoted to paper pilot: false.",
        "",
        "Search reused one sealed partition. The holdout was opened once, "
        "after the last generation receipt, and its verdicts were not fed back.",
        "",
    ])
    body = [header, render_lineage(lineage)]
    body.extend(str(receipt["readable"]) for receipt in receipts)
    body.append(render_holdout(holdout))
    return "\n".join(body).rstrip() + "\n"


def _pass_records(generation_receipts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    chosen: list[dict[str, Any]] = []
    seen: set[str] = set()
    for receipt in generation_receipts:
        if receipt.get("sealed_holdout_accessed") is not False:
            raise HoldoutSealError("search receipt claims the holdout was already open")
        for record in receipt["candidates"]:
            if record["verdict"] != "PASS" or not record["legal"]:
                continue
            identity = str(record["parameter_identity"])
            if identity in seen:
                continue
            seen.add(identity)
            chosen.append({
                "candidate_id": record["candidate_id"],
                "field": record["field"],
                "fields_changed": list(record["fields_changed"]),
                "generation": receipt["generation"],
                "lineage": record["lineage"],
                "parameter_identity": identity,
            })
    return chosen


def evaluate_sealed_holdout(
    seal: HoldoutSeal,
    generation_receipts: Sequence[Mapping[str, Any]],
    *,
    policy: GatePolicy | None = None,
) -> dict[str, Any]:
    """Open the holdout once and score search survivors against the original parent.

    The verdicts are not fed back into search and are not pilot promotions.
    """
    _assert_lab_authority()
    chosen_policy = policy if policy is not None else PRECOMMITTED_GATES
    for receipt in generation_receipts:
        if receipt.get("holdout_identity") != seal.identity:
            raise HoldoutSealError("search receipt holdout identity does not match the seal")
    sessions = seal.open_for_sealed_evaluation()
    if seal.accesses != ["SEALED_EVALUATION"]:
        raise HoldoutSealError("holdout must be opened once")
    parent = lab_parent()
    parent_metrics = score_sessions(parent, sessions, partition="HOLDOUT")
    if parent_metrics.closed_episodes < chosen_policy.holdout_min_closed_episodes:
        raise ValueError("holdout partition does not meet the precommitted evidence minimum")
    judged: list[dict[str, Any]] = []
    for record in _pass_records(generation_receipts):
        parameters = materialize(record["lineage"])
        if parameters.identity_hash != record["parameter_identity"]:
            raise ValueError("candidate lineage does not match its receipt identity")
        if len(record["fields_changed"]) != 1:
            raise ValueError("survivor changed more than one field")
        metrics = score_sessions(parameters, sessions, partition="HOLDOUT")
        verdict, reason = judge_holdout(metrics, parent_metrics, chosen_policy)
        judged.append({
            "candidate_id": record["candidate_id"],
            "delta_r": _delta(metrics, parent_metrics),
            "field": record["field"],
            "fields_changed": list(record["fields_changed"]),
            "generation": record["generation"],
            "holdout": metrics.as_dict(),
            "lineage": record["lineage"],
            "parameter_identity": record["parameter_identity"],
            "search_verdict": "PASS",
            "verdict": verdict,
            "verdict_reason": reason,
        })
    payload = {
        "aat_v1_holdout_consumed": False,
        "alpaca_called": False,
        "baseline": "generation-0 parent",
        "candidates": judged,
        "execution_authority": EXECUTION_AUTHORITY,
        "gate_policy": _policy_payload(chosen_policy),
        "gate_policy_hash": canonical_hash(_policy_payload(chosen_policy)),
        "holdout_identity": seal.identity,
        "holdout_open_count": len(seal.accesses),
        "holdout_session_ids": [session.session_id for session in sessions],
        "live_enabled": False,
        "network_calls": False,
        "parent_holdout": parent_metrics.as_dict(),
        "parent_identity": parent.identity_hash,
        "promoted_to_paper_pilot": False,
        "roles": dict(ROLES),
        "schema_version": HOLDOUT_SCHEMA,
        "sealed_holdout_accessed": True,
        "selection_uses_holdout": False,
        "typesafe_called": False,
    }
    payload["readable"] = render_holdout(payload)
    return payload


def _load_generation_receipts(out: Path, generations: int) -> list[dict[str, Any]]:
    loaded: list[dict[str, Any]] = []
    for generation in range(generations):
        path = out / f"generation-{generation:03d}.json"
        loaded.append(json.loads(path.read_text(encoding="utf-8")))
    return loaded


def run_fixture_lab(
    out_dir: str | Path,
    *,
    generations: int = DEFAULT_GENERATIONS,
    catalog: Sequence[LabSession] | None = None,
    scope: MutationScope | None = None,
    policy: GatePolicy | None = None,
) -> dict[str, Any]:
    """Run search, write its receipts, then open the holdout once.

    The default is three generations. Generation ``n+1`` seeds from the best
    PASS survivor of generation ``n`` when one exists. Every generation scores
    the same sealed search partition. The holdout opens once, after the last
    receipt, and its verdicts are not a search input.
    """
    _assert_lab_authority()
    if generations < 1:
        raise ValueError("generations must be positive")
    chosen_policy = policy if policy is not None else PRECOMMITTED_GATES
    sessions = tuple(builtin_catalog() if catalog is None else catalog)
    search, seal = split_catalog(sessions)
    run_search(
        search,
        holdout_identity=seal.identity,
        out_dir=out_dir,
        generations=generations,
        scope=scope,
        policy=chosen_policy,
    )
    if seal.accesses:
        raise HoldoutSealError("holdout opened during search")
    out = Path(out_dir)
    receipts = _load_generation_receipts(out, generations)
    holdout = evaluate_sealed_holdout(seal, receipts, policy=chosen_policy)
    _write_json(out / "holdout-evaluation.json", holdout)
    lineage = search_lineage_rows(receipts)
    report = render_report(receipts, holdout, lineage)
    (out / "report.md").write_text(report, encoding="utf-8")
    summary = {
        "aat_v1_holdout_consumed": False,
        "execution_authority": EXECUTION_AUTHORITY,
        "generations": generations,
        "generations_summary": [
            {
                "generation": receipt["generation"],
                "kept_candidate": receipt["next_search_parent_candidate"],
                "killed": list(receipt["killed"]),
                "parent_selection_mean_r": receipt["parent_selection"]["mean_r"],
                "survived": list(receipt["survived"]),
                "unknown": list(receipt["unknown"]),
            }
            for receipt in receipts
        ],
        "holdout_open_count": holdout["holdout_open_count"],
        "holdout_verdicts": [
            {
                "candidate_id": record["candidate_id"],
                "delta_r": record["delta_r"],
                "generation": record["generation"],
                "verdict": record["verdict"],
                "verdict_reason": record["verdict_reason"],
            }
            for record in holdout["candidates"]
        ],
        "killed": sum(len(receipt["killed"]) for receipt in receipts),
        "live_enabled": False,
        "out": str(out),
        "promoted_to_paper_pilot": False,
        "report": "report.md",
        "schema_version": SUMMARY_SCHEMA,
        "search_lineage": lineage,
        "survived": sum(len(receipt["survived"]) for receipt in receipts),
        "unknown": sum(len(receipt["unknown"]) for receipt in receipts),
    }
    _write_json(out / "summary.json", summary)
    summary["report_text"] = report
    return summary
