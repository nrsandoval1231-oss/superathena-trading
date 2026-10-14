"""Compile raw TRAINING bars into outcome-free ORB-M opportunities.

The compiler stops at the frozen breakout signal.  It does not score breakout
quality, simulate a trade, inspect an outcome, or read another partition.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..athena_adapter.contracts import canonical_hash
from ..orb_m.constitution import Constitution
from ..orb_m.market import average_true_range

_EASTERN = ZoneInfo("America/New_York")
_RAW_SCHEMA = "athena-aat-v1-training-projection-v1"
_HOLDOUT_RAW_SCHEMA = "athena-aat-v1-sealed-holdout-projection-v1"
_OPPORTUNITY_SCHEMA = "athena-aat-v1-opportunity-projection-v1"


class OpportunityCompileError(ValueError):
    """The source projection cannot safely produce AAT opportunities."""


@dataclass
class _Session:
    symbol: str
    day: str
    opening: dict[int, dict[str, Any]] = field(default_factory=dict)
    regular: list[tuple[int, dict[str, Any], datetime]] = field(default_factory=list)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_receipt(path: Path, rows_path: Path, *, partition: str) -> dict[str, Any]:
    if partition == "TRAINING" and (
        "holdout" in str(path).lower() or "holdout" in str(rows_path).lower()
    ):
        raise OpportunityCompileError("holdout paths are forbidden")
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OpportunityCompileError("raw TRAINING receipt is unreadable") from exc
    expected = {
        "TRAINING": (_RAW_SCHEMA, "TRAINING_ONLY", False, "training"),
        "SEALED_HOLDOUT": (
            _HOLDOUT_RAW_SCHEMA, "ONE_TIME_SEALED_HOLDOUT_EVALUATION", True, "holdout"
        ),
    }.get(partition)
    if expected is None:
        raise OpportunityCompileError("unsupported opportunity partition")
    schema, capability, contains_holdout, prefix = expected
    if receipt.get("schema_version") != schema or receipt.get("capability") != capability:
        raise OpportunityCompileError(f"raw {partition} receipt schema or capability mismatch")
    if receipt.get("contains_sealed_holdout") is not contains_holdout:
        label = "sealed holdout" if partition == "TRAINING" else "sealed-holdout"
        raise OpportunityCompileError(f"source {label} declaration mismatch for {partition}")
    if receipt.get("execution_authority") != "ABSENT":
        raise OpportunityCompileError("execution authority must be ABSENT")
    expected_hash = receipt.get(f"{prefix}_rows_sha256")
    if not isinstance(expected_hash, str) or _sha256(rows_path) != expected_hash:
        raise OpportunityCompileError(f"raw {partition} rows hash mismatch")
    return receipt


def _parse_row(raw: Any, line_number: int) -> tuple[str, str, int, dict[str, Any], datetime] | None:
    if not isinstance(raw, dict):
        raise OpportunityCompileError(f"row {line_number} is not an object")
    required = {"symbol", "event_at", "available_at", "open", "high", "low", "close", "volume"}
    if not required.issubset(raw):
        raise OpportunityCompileError(f"row {line_number} is missing required fields")
    try:
        event_at = datetime.fromisoformat(raw["event_at"])
        available_at = datetime.fromisoformat(raw["available_at"])
        if event_at.tzinfo is None or available_at.tzinfo is None or available_at < event_at:
            raise ValueError
        local = event_at.astimezone(_EASTERN)
        minute = (local.hour * 60 + local.minute) - (9 * 60 + 30)
        prices = [float(raw[key]) for key in ("open", "high", "low", "close")]
        volume = float(raw["volume"])
    except (TypeError, ValueError) as exc:
        raise OpportunityCompileError(f"row {line_number} has invalid market data") from exc
    if min(prices) <= 0 or prices[1] < max(prices[0], prices[3]) or prices[2] > min(prices[0], prices[3]) or volume < 0:
        raise OpportunityCompileError(f"row {line_number} violates bar invariants")
    if not 0 <= minute < 390:
        return None
    symbol = raw["symbol"]
    if not isinstance(symbol, str) or not symbol:
        raise OpportunityCompileError(f"row {line_number} has invalid symbol")
    return symbol, local.date().isoformat(), minute, raw, available_at


def _compile_opportunities(
    receipt_path: str | Path,
    rows_path: str | Path,
    output_rows_path: str | Path,
    output_receipt_path: str | Path,
    *,
    maximum_opportunities: int,
    require_atr14: bool = False,
    require_resolved_session: bool = False,
    partition: str = "TRAINING",
    context_receipt_path: str | Path | None = None,
    context_rows_path: str | Path | None = None,
) -> dict[str, Any]:
    """Write a bounded, deterministic opportunity projection and receipt."""
    source_receipt_path, source_rows_path = Path(receipt_path), Path(rows_path)
    output_rows, output_receipt = Path(output_rows_path), Path(output_receipt_path)
    if maximum_opportunities < 1:
        raise OpportunityCompileError("maximum opportunities must be positive")
    if require_resolved_session and not require_atr14:
        raise OpportunityCompileError("resolved-session mode requires ATR14 qualification")
    if output_rows.exists() or output_receipt.exists():
        raise OpportunityCompileError("refusing to overwrite output")
    receipt = _load_receipt(source_receipt_path, source_rows_path, partition=partition)
    sessions: dict[tuple[str, str], _Session] = {}
    eligible_sessions: set[tuple[str, str]] = set()
    source_row_count = 0

    def ingest(path: Path, *, eligible: bool) -> int:
        count = 0
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                count += 1
                try:
                    parsed = _parse_row(json.loads(line), line_number)
                except json.JSONDecodeError as exc:
                    raise OpportunityCompileError(f"row {line_number} is invalid JSON") from exc
                if parsed is None:
                    continue
                symbol, day, minute, raw, available_at = parsed
                key = (symbol, day)
                session = sessions.setdefault(key, _Session(symbol, day))
                if minute in session.opening or any(item[0] == minute for item in session.regular):
                    raise OpportunityCompileError(f"duplicate regular minute for {symbol} {day}")
                session.regular.append((minute, raw, available_at))
                if 0 <= minute < 15:
                    session.opening[minute] = raw
                if eligible:
                    eligible_sessions.add(key)
        return count

    if (context_receipt_path is None) != (context_rows_path is None):
        raise OpportunityCompileError("context receipt and rows must be supplied together")
    if context_receipt_path is not None and context_rows_path is not None:
        context_receipt = _load_receipt(
            Path(context_receipt_path), Path(context_rows_path), partition="TRAINING"
        )
        context_count = ingest(Path(context_rows_path), eligible=False)
        if context_count != context_receipt.get("training_row_count"):
            raise OpportunityCompileError("raw TRAINING context row count mismatch")
        if (
            context_receipt.get("dataset_hash") != receipt.get("dataset_hash")
            or context_receipt.get("assignment_hash") != receipt.get("assignment_hash")
            or context_receipt.get("protocol_hash") != receipt.get("protocol_hash")
        ):
            raise OpportunityCompileError("TRAINING context identity mismatch")
    source_row_count = ingest(source_rows_path, eligible=True)

    count_field = "training_row_count" if partition == "TRAINING" else "holdout_row_count"
    if source_row_count != receipt.get(count_field):
        raise OpportunityCompileError(f"raw {partition} row count mismatch")

    constitution = Constitution()
    complete_daily: dict[str, list[tuple[str, tuple[float, float, float]]]] = {}
    if require_atr14:
        for session in sessions.values():
            by_minute = {minute: row for minute, row, _ in session.regular}
            if set(by_minute) != set(range(390)):
                continue
            daily = (
                max(float(row["high"]) for row in by_minute.values()),
                min(float(row["low"]) for row in by_minute.values()),
                float(by_minute[389]["close"]),
            )
            complete_daily.setdefault(session.symbol, []).append((session.day, daily))
        for values in complete_daily.values():
            values.sort(key=lambda item: item[0])
    candidates: list[tuple[datetime, str, dict[str, Any]]] = []
    for key, session in sessions.items():
        if key not in eligible_sessions:
            continue
        if set(session.opening) != set(range(constitution.opening_minutes)):
            continue
        if require_resolved_session and {minute for minute, _, _ in session.regular} != set(range(390)):
            continue
        opening_high = max(float(row["high"]) for row in session.opening.values())
        opening_low = min(float(row["low"]) for row in session.opening.values())
        opening_volume = sum(float(row["volume"]) for row in session.opening.values())
        atr14 = None
        if require_atr14:
            prior = [daily for day, daily in complete_daily.get(session.symbol, []) if day < session.day]
            if len(prior) < 15:
                continue
            atr14 = average_true_range(prior[-15:])
        observed: list[dict[str, Any]] = [session.opening[index] for index in range(15)]
        for minute, row, available_at in sorted(session.regular, key=lambda item: item[0]):
            if minute < 15:
                continue
            if minute >= constitution.session_deadline_minute:
                break
            close = float(row["close"])
            direction = "LONG" if close > opening_high else "SHORT" if close < opening_low else None
            observed.append(row)
            if direction is None:
                continue
            if any(datetime.fromisoformat(bar["available_at"]) > available_at for bar in session.opening.values()):
                continue
            known_observed = [
                bar for bar in observed
                if datetime.fromisoformat(bar["available_at"]) <= available_at
            ]
            identity_seed = {
                "symbol": session.symbol,
                "session": session.day,
                "direction": direction,
                "signal_available_at": available_at.isoformat(),
                "constitution_hash": constitution.identity_hash,
            }
            features = {
                "direction": direction,
                "signal_minute": minute,
                "signal_close": close,
                "opening_range_high": opening_high,
                "opening_range_low": opening_low,
                "opening_range_width_fraction": (opening_high - opening_low) / opening_low,
                "opening_range_volume": opening_volume,
                "signal_volume": float(row["volume"]),
                "vwap_to_signal": (
                    sum(((float(bar["high"]) + float(bar["low"]) + float(bar["close"])) / 3) * float(bar["volume"]) for bar in known_observed)
                    / sum(float(bar["volume"]) for bar in known_observed)
                    if sum(float(bar["volume"]) for bar in known_observed) > 0 else None
                ),
                "source_adjusted": bool(row.get("adjusted")),
            }
            if atr14 is not None:
                features["atr14"] = atr14
            opportunity = {
                "opportunity_id": canonical_hash(identity_seed),
                "candidate_hash": constitution.identity_hash,
                "features": features,
            }
            candidates.append((available_at, opportunity["opportunity_id"], opportunity))
            break

    selected = [item[2] for item in sorted(candidates, key=lambda item: (item[0], item[1]))[:maximum_opportunities]]
    if not selected:
        raise OpportunityCompileError("no complete breakout opportunities found")
    output_rows.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in selected)
    output_rows.write_text(payload, encoding="utf-8", newline="\n")
    result = {
        "schema_version": _OPPORTUNITY_SCHEMA,
        "source_projection_hash": receipt["projection_hash"],
        "dataset_hash": receipt["dataset_hash"],
        "assignment_hash": receipt["assignment_hash"],
        "protocol_hash": receipt["protocol_hash"],
        "partition": partition,
        "compiler": (
            "ORB_M_FIRST_CLOSE_BREAKOUT_V3_RESOLVED_ATR14" if require_resolved_session
            else "ORB_M_FIRST_CLOSE_BREAKOUT_V2_ATR14" if require_atr14
            else "ORB_M_FIRST_CLOSE_BREAKOUT_V1"
        ),
        "requires_15_complete_prior_sessions": require_atr14,
        "constitution_hash": constitution.identity_hash,
        "rows_path": output_rows.name,
        "row_count": len(selected),
        "rows_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        "contains_outcomes": False,
        "contains_sealed_holdout": partition == "SEALED_HOLDOUT",
        "execution_authority": "ABSENT",
    }
    if require_resolved_session:
        result["requires_complete_current_session"] = True
    result["projection_hash"] = canonical_hash(result)
    output_receipt.parent.mkdir(parents=True, exist_ok=True)
    output_receipt.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    return result


def compile_training_opportunities(
    receipt_path: str | Path, rows_path: str | Path,
    output_rows_path: str | Path, output_receipt_path: str | Path, *,
    maximum_opportunities: int, require_atr14: bool = False,
    require_resolved_session: bool = False,
) -> dict[str, Any]:
    return _compile_opportunities(
        receipt_path, rows_path, output_rows_path, output_receipt_path,
        maximum_opportunities=maximum_opportunities, require_atr14=require_atr14,
        require_resolved_session=require_resolved_session, partition="TRAINING",
    )


def compile_holdout_opportunities(
    receipt_path: str | Path, rows_path: str | Path,
    output_rows_path: str | Path, output_receipt_path: str | Path, *,
    maximum_opportunities: int, require_atr14: bool = False,
    require_resolved_session: bool = False,
    context_receipt_path: str | Path | None = None,
    context_rows_path: str | Path | None = None,
) -> dict[str, Any]:
    return _compile_opportunities(
        receipt_path, rows_path, output_rows_path, output_receipt_path,
        maximum_opportunities=maximum_opportunities, require_atr14=require_atr14,
        require_resolved_session=require_resolved_session, partition="SEALED_HOLDOUT",
        context_receipt_path=context_receipt_path, context_rows_path=context_rows_path,
    )
