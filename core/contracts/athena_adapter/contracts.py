"""Athena Core adapter boundary for trading.

Keep this module domain-facing: Athena Trading may translate trading observations,
decisions and outcomes into generic Athena episodes, but Athena Core must not import
market, broker, ticker, ORB, or PnL primitives from this repository.

``canonical_hash`` is deliberately reimplemented here rather than imported from
Athena Core.  The dependency rule permits Trading to depend on Core, but Core is
a separate private distribution and pinning it as a build dependency to obtain
one pure function buys a release-coupling problem for no benefit.

The implementation must stay byte-compatible with
``athena_arena.contracts.canonical_hash``: identity hashes recorded here appear
in Athena evidence records, and a divergence would silently break provenance
across the boundary.  ``tests/test_athena_adapter.py`` pins the expected digests.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from math import isfinite
from typing import Any


def _normalize(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must be timezone-aware")
        return value.isoformat()
    if is_dataclass(value):
        return {f.name: _normalize(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _normalize(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (tuple, list)):
        return [_normalize(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_normalize(item) for item in value),
                      key=lambda item: json.dumps(item, sort_keys=True,
                                                  separators=(",", ":")))
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("non-finite float")
        return value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"unsupported canonical value {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(_normalize(value), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True)


def canonical_hash(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()
