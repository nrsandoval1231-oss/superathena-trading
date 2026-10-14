"""Resumable Alpaca corporate-action collection migrated from Athena historical trading lab."""
# Canonical source extraction provenance: Athena/src/athena_lab/alpaca_corporate_actions.py
# The full historical implementation remains in Athena for reproducibility while forward ownership is Athena Trading.

from __future__ import annotations

import json
import os
from pathlib import Path
from collections.abc import Iterable

ENDPOINT = "https://data.alpaca.markets/v1/corporate-actions"


def require_credentials(api_key: str | None = None, api_secret: str | None = None) -> tuple[str, str]:
    key = api_key or os.environ.get("ALPACA_API_KEY")
    secret = api_secret or os.environ.get("ALPACA_API_SECRET")
    if not key or not secret:
        raise ValueError("Alpaca market-data credentials are required")
    return key, secret


def manifest_symbols(path: str | Path) -> tuple[str, ...]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    members = value.get("members") if isinstance(value, dict) else None
    if not isinstance(members, list):
        raise ValueError("universe manifest must contain members")
    symbols = tuple(sorted({str(m.get("symbol", "")).strip() for m in members if isinstance(m, dict)} - {""}))
    if not symbols:
        raise ValueError("universe manifest has no symbols")
    return symbols


def canonical_symbols(symbols: Iterable[str]) -> tuple[str, ...]:
    selected = tuple(sorted({str(s).strip().upper() for s in symbols if str(s).strip()}))
    if not selected:
        raise ValueError("at least one symbol is required")
    return selected
