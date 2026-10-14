"""Shared verification for hash-bound row receipts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..athena_adapter.contracts import canonical_hash
from .training import AATValidationError


def verified_receipt(path: Path, *, hash_field: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AATValidationError(f"receipt is unreadable: {path.name}") from exc
    if not isinstance(value, dict):
        raise AATValidationError(f"receipt is malformed: {path.name}")
    payload = dict(value)
    claimed = payload.pop(hash_field, None)
    if claimed != canonical_hash(payload):
        raise AATValidationError(f"receipt hash mismatch: {path.name}")
    rows_name, rows_hash = value.get("rows_path"), value.get("rows_sha256")
    if not isinstance(rows_name, str) or not isinstance(rows_hash, str):
        raise AATValidationError(f"row binding is missing: {path.name}")
    rows_path = path.parent / rows_name
    if not rows_path.is_file() or hashlib.sha256(rows_path.read_bytes()).hexdigest() != rows_hash:
        raise AATValidationError(f"row hash mismatch: {path.name}")
    return value
