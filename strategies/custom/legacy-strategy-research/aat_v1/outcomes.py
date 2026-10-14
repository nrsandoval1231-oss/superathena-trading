"""TRAINING-only outcome diagnostic for ATR-qualified ORB-M opportunities."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ..athena_adapter.contracts import canonical_hash
from ..orb_m.constitution import Constitution, ManagementParameters
from ..orb_m.entry import BreakoutSignal, OpeningRange
from ..orb_m.execution import run_position
from ..orb_m.market import Bar
from ..orb_m.session import run_full_session
from .opportunities import OpportunityCompileError, _Session, _load_receipt, _parse_row
from .training import AATValidationError, load_training_projection

EVALUATOR_ID = "ORB_M_FIRST_BREAKOUT_NO_DETERIORATION_DIAGNOSTIC_V1"
FULL_EVALUATOR_ID = "FROZEN_FULL_ORB_M_EVALUATOR_V1"
SCORING_SEMANTICS = {
    "schema_version": "aat-v1-action-scoring-v1",
    "metric": "normalized_r",
    "action_multipliers": {
        "PASS": 0.0,
        "ENTER_REDUCED": 0.5,
        "ENTER_STANDARD": 1.0,
        "ENTER_HIGH_CONVICTION": 2.0,
    },
    "regret": "best_legal_action_score_minus_actual_action_score",
    "legal_actions": ["PASS", "ENTER_REDUCED", "ENTER_STANDARD", "ENTER_HIGH_CONVICTION"],
}


def _bar(raw: dict[str, Any], minute: int) -> Bar:
    return Bar(
        event_at=datetime.fromisoformat(raw["event_at"]), minute=minute,
        open=float(raw["open"]), high=float(raw["high"]), low=float(raw["low"]),
        close=float(raw["close"]), volume=float(raw["volume"]),
        vwap=float(raw["vwap"]) if raw.get("vwap") is not None else None,
        transactions=int(raw["transactions"]) if raw.get("transactions") is not None else None,
    )


def evaluate_training_outcomes(
    source_receipt_path: str | Path,
    source_rows_path: str | Path,
    opportunity_receipt_path: str | Path,
    protocol_path: str | Path,
    output_rows_path: str | Path,
    output_receipt_path: str | Path,
    *,
    full_session: bool = False,
) -> dict[str, Any]:
    """Evaluate selected opportunities without exposing outcomes to an Actor."""
    output_rows, output_receipt = Path(output_rows_path), Path(output_receipt_path)
    if output_rows.exists() or output_receipt.exists():
        raise AATValidationError("refusing to overwrite outcome evidence")
    source_receipt = _load_receipt(
        Path(source_receipt_path), Path(source_rows_path), partition="TRAINING"
    )
    opportunity_receipt, opportunities = load_training_projection(opportunity_receipt_path, protocol_path)
    if opportunity_receipt.get("compiler") not in {
        "ORB_M_FIRST_CLOSE_BREAKOUT_V2_ATR14",
        "ORB_M_FIRST_CLOSE_BREAKOUT_V3_RESOLVED_ATR14",
    }:
        raise AATValidationError("outcomes require ATR14-qualified opportunities")
    if opportunity_receipt.get("source_projection_hash") != source_receipt.get("projection_hash"):
        raise AATValidationError("opportunity/source projection mismatch")

    selected = {row.opportunity_id: row for row in opportunities}
    sessions: dict[tuple[str, str], _Session] = {}
    source_row_count = 0
    with Path(source_rows_path).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            source_row_count += 1
            try:
                parsed = _parse_row(json.loads(line), line_number)
            except json.JSONDecodeError as exc:
                raise OpportunityCompileError(f"row {line_number} is invalid JSON") from exc
            if parsed is None:
                continue
            symbol, day, minute, raw, available_at = parsed
            session = sessions.setdefault((symbol, day), _Session(symbol, day))
            session.regular.append((minute, raw, available_at))
            if 0 <= minute < 15:
                session.opening[minute] = raw
    if source_row_count != source_receipt.get("training_row_count"):
        raise AATValidationError("raw TRAINING row count mismatch")

    constitution = Constitution()
    parameters = ManagementParameters()
    evaluated: dict[str, dict[str, Any]] = {}
    for session in sessions.values():
        by_minute = {minute: (raw, available_at) for minute, raw, available_at in session.regular}
        if not set(range(390)).issubset(by_minute) or set(session.opening) != set(range(15)):
            continue
        opening = OpeningRange(
            high=max(float(row["high"]) for row in session.opening.values()),
            low=min(float(row["low"]) for row in session.opening.values()),
            volume=sum(float(row["volume"]) for row in session.opening.values()),
            frozen_at_minute=15,
        )
        signal = None
        signal_available_at = None
        for minute in range(15, constitution.session_deadline_minute):
            raw, available_at = by_minute[minute]
            close = float(raw["close"])
            direction = "LONG" if close > opening.high else "SHORT" if close < opening.low else None
            if direction is not None:
                signal = BreakoutSignal(direction, minute, close, opening)
                signal_available_at = available_at
                break
        if signal is None:
            continue
        opportunity_id = canonical_hash({
            "symbol": session.symbol, "session": session.day,
            "direction": signal.direction,
            "signal_available_at": signal_available_at.isoformat(),
            "constitution_hash": constitution.identity_hash,
        })
        opportunity = selected.get(opportunity_id)
        if opportunity is None:
            continue
        atr14 = opportunity.features.get("atr14")
        if not isinstance(atr14, (int, float)) or atr14 <= 0:
            raise AATValidationError("opportunity ATR14 is invalid")
        bars = [_bar(by_minute[minute][0], minute) for minute in range(390)]
        if full_session:
            session_result = run_full_session(opening, bars, float(atr14), constitution, parameters)
            if not session_result.episodes:
                raise AATValidationError("full-session outcome has no episodes")
            net_r = session_result.net_r
            peak_r = max(episode.result.peak_r for episode in session_result.episodes)
            trough_r = min(episode.result.trough_r for episode in session_result.episodes)
            entry_minute = session_result.episodes[0].result.entry_minute
            bars_held = sum(episode.result.bars_held for episode in session_result.episodes)
            exit_reason = session_result.episodes[-1].result.exit_reason
            episode_count = len(session_result.episodes)
            reentry_count = session_result.reentries
        else:
            result = run_position(signal, bars, float(atr14), constitution, parameters)
            if result is None or result.exit_reason in {"OPEN", "DATA_EXHAUSTED"}:
                raise AATValidationError("diagnostic outcome is unresolved")
            net_r, peak_r, trough_r = result.net_r, result.peak_r, result.trough_r
            entry_minute, bars_held, exit_reason = result.entry_minute, result.bars_held, result.exit_reason
            episode_count, reentry_count = 1, 0
        session_evidence_hash = canonical_hash(tuple(
            {key: by_minute[minute][0].get(key) for key in (
                "event_at", "available_at", "open", "high", "low", "close", "volume", "vwap", "transactions"
            )} for minute in range(390)
        ))
        evaluated[opportunity_id] = {
            "opportunity_id": opportunity_id,
            "candidate_hash": opportunity.candidate_hash,
            "feature_hash": canonical_hash(opportunity.features),
            "session_evidence_hash": session_evidence_hash,
            "net_r": net_r,
            "peak_r": peak_r,
            "trough_r": trough_r,
            "entry_minute": entry_minute,
            "bars_held": bars_held,
            "exit_reason": exit_reason,
            "episode_count": episode_count,
            "reentry_count": reentry_count,
            "evaluator": FULL_EVALUATOR_ID if full_session else EVALUATOR_ID,
            "partition": "TRAINING",
            "execution_authority": "ABSENT",
        }
    if set(evaluated) != set(selected):
        missing = sorted(set(selected) - set(evaluated))
        raise AATValidationError(f"selected opportunities could not be evaluated: {missing}")

    ordered = [evaluated[row.opportunity_id] for row in opportunities]
    payload = "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in ordered)
    output_rows.parent.mkdir(parents=True, exist_ok=True)
    output_rows.write_text(payload, encoding="utf-8", newline="\n")
    receipt = {
        "schema_version": (
            "aat-v1-training-full-session-outcome-v1"
            if full_session else "aat-v1-training-outcome-diagnostic-v1"
        ),
        "evaluator": FULL_EVALUATOR_ID if full_session else EVALUATOR_ID,
        "source_projection_hash": source_receipt["projection_hash"],
        "opportunity_projection_hash": opportunity_receipt["projection_hash"],
        "constitution_hash": constitution.identity_hash,
        "management_parameters_hash": parameters.identity_hash,
        "partition": "TRAINING",
        "row_count": len(ordered),
        "rows_path": output_rows.name,
        "rows_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        "actor_visible": False,
        "adaptation_evidence": full_session,
        "scoring_hash": canonical_hash(SCORING_SEMANTICS) if full_session else None,
        "contains_sealed_holdout": False,
        "execution_authority": "ABSENT",
    }
    receipt["result_hash"] = canonical_hash(receipt)
    output_receipt.parent.mkdir(parents=True, exist_ok=True)
    output_receipt.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    return receipt
