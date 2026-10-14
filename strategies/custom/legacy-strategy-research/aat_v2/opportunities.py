"""Build an outcome-free AAT-V2 opportunity index from normalized minute bars."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..athena_adapter.contracts import canonical_hash
from ..orb_m.constitution import Constitution

_EASTERN = ZoneInfo("America/New_York")
_REGULAR_OPEN = time(9, 30)
_REGULAR_CLOSE = time(16, 0)
_OPPORTUNITY_SCHEMA = "athena-aat-v2-opportunity-index-v1"


class OpportunityIndexError(ValueError):
    """Input bars cannot safely produce an opportunity index."""


def build_opportunity_index(
    input_paths: list[str | Path],
    output_rows_path: str | Path,
    output_receipt_path: str | Path,
) -> dict[str, Any]:
    """Write one first-close-through row per symbol/session, refusing overwrite."""
    output_rows = Path(output_rows_path)
    output_receipt = Path(output_receipt_path)
    if output_rows.exists() or output_receipt.exists():
        raise OpportunityIndexError("refusing to overwrite opportunity index")
    sessions: dict[tuple[str, str], dict[int, dict[str, Any]]] = defaultdict(dict)
    source_paths = [Path(path) for path in input_paths]
    if not source_paths:
        raise OpportunityIndexError("at least one input path is required")
    for path in source_paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise OpportunityIndexError(f"input is unreadable: {path}") from exc
        for line_number, line in enumerate(lines, start=1):
            try:
                raw = json.loads(line)
                symbol = str(raw["symbol"])
                event_at = datetime.fromisoformat(str(raw["event_at"]))
                available_at = datetime.fromisoformat(str(raw["available_at"]))
                if event_at.tzinfo is None or available_at.tzinfo is None or available_at < event_at:
                    raise ValueError("timestamps invalid")
                local = event_at.astimezone(_EASTERN)
                if not _REGULAR_OPEN <= local.time() < _REGULAR_CLOSE:
                    continue
                minute = (local.hour - 9) * 60 + local.minute - 30
                if minute < 0 or minute >= 390:
                    continue
                required = ("open", "high", "low", "close", "volume")
                values = {key: float(raw[key]) for key in required}
                if values["low"] > min(values["open"], values["close"]):
                    raise ValueError("low violates bar invariant")
                if values["high"] < max(values["open"], values["close"]):
                    raise ValueError("high violates bar invariant")
                if values["volume"] < 0:
                    raise ValueError("volume is negative")
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise OpportunityIndexError(f"invalid bar {path}:{line_number}") from exc
            key = (symbol, local.date().isoformat())
            if minute in sessions[key]:
                raise OpportunityIndexError(f"duplicate minute for {symbol} {key[1]}")
            sessions[key][minute] = {**raw, "_available_at": available_at, "_local_minute": minute, **values}

    constitution = Constitution()
    rows: list[dict[str, Any]] = []
    for (symbol, day), bars in sorted(sessions.items()):
        if set(range(constitution.opening_minutes)) - set(bars):
            continue
        opening = [bars[minute] for minute in range(constitution.opening_minutes)]
        opening_high = max(bar["high"] for bar in opening)
        opening_low = min(bar["low"] for bar in opening)
        opening_volume = sum(bar["volume"] for bar in opening)
        signal = None
        for minute in sorted(bars):
            if minute < constitution.opening_minutes or minute >= constitution.session_deadline_minute:
                continue
            close = bars[minute]["close"]
            direction = "LONG" if close > opening_high else "SHORT" if close < opening_low else None
            if direction:
                signal = (minute, bars[minute], direction)
                break
        if signal is None:
            continue
        minute, bar, direction = signal
        identity = {
            "symbol": symbol,
            "session": day,
            "direction": direction,
            "signal_available_at": bar["_available_at"].isoformat(),
            "constitution_hash": constitution.identity_hash,
        }
        opportunity_id = canonical_hash(identity)
        feature_row = {
            "direction": direction,
            "signal_minute": minute,
            "signal_close": bar["close"],
            "opening_range_high": opening_high,
            "opening_range_low": opening_low,
            "opening_range_width_fraction": (opening_high - opening_low) / opening_low,
            "opening_range_volume": opening_volume,
            "signal_volume": bar["volume"],
        }
        rows.append({
            "opportunity_id": opportunity_id,
            "symbol": symbol,
            "decision_at": bar["_available_at"].isoformat(),
            "features": feature_row,
        })
    if not rows:
        raise OpportunityIndexError("no opportunities found")
    payload = "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows)
    output_rows.parent.mkdir(parents=True, exist_ok=True)
    output_rows.write_text(payload, encoding="utf-8", newline="\n")
    receipt = {
        "schema_version": _OPPORTUNITY_SCHEMA,
        "source_paths": [str(path) for path in source_paths],
        "row_count": len(rows),
        "rows_path": output_rows.name,
        "rows_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        "constitution_hash": constitution.identity_hash,
        "contains_outcomes": False,
        "contains_sealed_holdout": False,
        "execution_authority": "ABSENT",
    }
    receipt["index_hash"] = canonical_hash(receipt)
    output_receipt.parent.mkdir(parents=True, exist_ok=True)
    output_receipt.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return receipt
