"""Pure parser for one GDELT 2.0 GKG 27-field row.

This module performs no network access and does not infer company identity from
free text. Callers provide the symbol mapping after an independently reviewed
entity-matching step. The GKG timestamp is preserved as both event and
availability time: it is the first observed timestamp available from this
source, not a claim about the article publisher's internal publication clock.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .contracts import ExogenousContractError, ExogenousRecord

GKG_FIELD_COUNT = 27


class GdeltError(ValueError):
    """A GDELT GKG row cannot be admitted."""


def parse_gkg_row(raw: str, *, symbol: str) -> ExogenousRecord:
    """Map one GDELT GKG v2.1 tab-separated row to a news record."""
    if not isinstance(raw, str):
        raise GdeltError("GKG row must be text")
    fields = raw.rstrip("\r\n").split("\t")
    if len(fields) != GKG_FIELD_COUNT:
        raise GdeltError(f"GKG row must contain {GKG_FIELD_COUNT} fields")
    if not isinstance(symbol, str) or not symbol.strip():
        raise GdeltError("symbol is required")
    record_id = fields[0].strip()
    timestamp = fields[1].strip()
    domain = fields[3].strip()
    url = fields[4].strip()
    if not record_id:
        raise GdeltError("GKG record id is missing")
    if not url:
        raise GdeltError("GKG URL is missing")
    try:
        observed_at = datetime.strptime(timestamp, "%Y%m%d%H%M%S").replace(
            tzinfo=UTC
        )
    except ValueError as exc:
        raise GdeltError("GKG timestamp is invalid") from exc
    payload: dict[str, Any] = {
        "external_id": f"gdelt:{record_id}:{symbol.strip()}",
        "gkg_record_id": record_id,
        "url": url,
        "domain": domain,
        "themes": _split_semicolon(fields[7]),
        "persons": _split_semicolon(fields[11]),
        "organizations": _split_semicolon(fields[13]),
        "tone": _parse_tone(fields[15]),
        "source_timestamp": timestamp,
    }
    try:
        return ExogenousRecord(
            source="news",
            symbol=symbol.strip(),
            event_at=observed_at,
            available_at=observed_at,
            payload=payload,
        )
    except ExogenousContractError as exc:
        raise GdeltError("GKG row violates the exogenous contract") from exc


def _split_semicolon(value: str) -> list[str]:
    return [item for item in value.split(";") if item]


def _parse_tone(value: str) -> list[float] | None:
    if not value:
        return None
    try:
        return [float(item) for item in value.split(",")]
    except ValueError as exc:
        raise GdeltError("GKG tone is invalid") from exc
