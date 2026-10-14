"""FRED ALFRED vintage adapter for market-wide macro records.

Macro evidence for ORB-M is a scheduled-event flag visible by the 09:45 ET
decision, using the print as it stood on that date rather than today's
restated value.  ALFRED is the vintage archive that can say that; the
current-view FRED series cannot.

The adapter is a pure per-row function: one ALFRED vintage observation becomes
one ``ExogenousRecord``.  It does not fetch, does not invent a second record
type, and does not substitute a later vintage for the original.  Live ALFRED
calls, when used at all, live in this module, require an explicit vintage
window, and fail closed without ``FRED_API_KEY``.  Tests never invoke them.
"""
from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable, Mapping
from datetime import date, datetime, time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .contracts import ExogenousContractError, ExogenousRecord

EASTERN = ZoneInfo("America/New_York")

#: Scheduled BLS/BEA-style print.  ALFRED vintage fields are dates, not clock
#: times; this is the ORB-M convention for turning a vintage date into an
#: instant visible by 09:45 ET.  It is not a timestamp FRED supplied.
SCHEDULED_PRINT_ET = time(8, 30)

API_ROOT = "https://api.stlouisfed.org"
OBSERVATIONS_PATH = "/fred/series/observations"
VINTAGE_DATES_PATH = "/fred/series/vintagedates"

#: output_type=1 returns one row per real-time period, so original prints and
#: later revisions remain distinct rows with their own ``realtime_start``.
VINTAGE_OUTPUT_TYPE = "1"
VINTAGE_UNITS = "lin"

Transport = Callable[[str, str, dict[str, str]], tuple[int, bytes]]


class AlfredError(ValueError):
    """An ALFRED row or live fetch cannot be used."""


class MissingAlfredCredentialsError(AlfredError):
    """FRED_API_KEY is absent.  Fail closed; do not call the network."""


def alfred_adapter(raw: Mapping[str, Any]) -> ExogenousRecord:
    """Map one ALFRED vintage observation to one macro ``ExogenousRecord``.

    Required vendor fields: ``series_id``, ``date`` (observation period),
    ``realtime_start`` (this vintage), ``value``, ``original_realtime_start``
    (earliest vintage of this observation; equal to ``realtime_start`` for a
    scheduled print), and a timezone-aware ``available_at``.

    ``event_at`` is the observation period ``date`` at 00:00 America/New_York
    unless the row supplies a timezone-aware override.  ``available_at`` is
    never derived here: missing or naive values fail closed so a date-only
    vintage cannot silently become midnight UTC.
    """
    if not isinstance(raw, Mapping):
        raise ExogenousContractError("ALFRED observation is not an object")
    series_id = _required_text(raw.get("series_id"), label="series_id")
    observation_date = _parse_alfred_date(raw.get("date"), label="date")
    vintage_date = _parse_alfred_date(raw.get("realtime_start"), label="realtime_start")
    original_vintage = _parse_alfred_date(
        raw.get("original_realtime_start"), label="original_realtime_start",
    )
    if original_vintage > vintage_date:
        raise ExogenousContractError("original_realtime_start postdates this vintage")
    value = _numeric_value(raw.get("value"))
    available_at = _parse_aware_datetime(raw.get("available_at"), label="available_at")
    event_at = (
        _parse_aware_datetime(raw.get("event_at"), label="event_at")
        if raw.get("event_at") is not None
        else datetime.combine(observation_date, time(0, 0), tzinfo=EASTERN)
    )
    scheduled = original_vintage == vintage_date
    original_id = _external_id(series_id, observation_date, original_vintage)
    payload: dict[str, Any] = {
        "external_id": _external_id(series_id, observation_date, vintage_date),
        "series_id": series_id,
        "observation_date": observation_date.isoformat(),
        "vintage_date": vintage_date.isoformat(),
        "value": value,
        "kind": "scheduled_print" if scheduled else "revision",
    }
    realtime_end = raw.get("realtime_end")
    if realtime_end is not None and str(realtime_end).strip():
        payload["realtime_end"] = _parse_alfred_date(
            realtime_end, label="realtime_end",
        ).isoformat()
    category = raw.get("category")
    if category is not None and str(category).strip():
        payload["category"] = str(category).strip()
    return ExogenousRecord(
        source="macro",
        symbol=None,
        event_at=event_at,
        available_at=available_at,
        payload=payload,
        revision_of=None if scheduled else original_id,
    )


def annotate_alfred_revisions(
    rows: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Stamp ``original_realtime_start`` per ``(series_id, date)``.

    The earliest ``realtime_start`` for an observation date is the scheduled
    print.  Later vintages of the same date are revisions.  A per-row adapter
    cannot see the other vintages, so this annotation has to happen first or
    ``alfred_adapter`` refuses the row.
    """
    materialized = [dict(row) for row in rows]
    first: dict[tuple[str, str], str] = {}
    parsed: list[tuple[int, str, str, str]] = []
    for index, row in enumerate(materialized):
        series_id = _required_text(row.get("series_id"), label="series_id")
        observation = _parse_alfred_date(row.get("date"), label="date").isoformat()
        vintage = _parse_alfred_date(row.get("realtime_start"), label="realtime_start")
        vintage_text = vintage.isoformat()
        parsed.append((index, series_id, observation, vintage_text))
        key = (series_id, observation)
        established = first.get(key)
        if established is None or vintage_text < established:
            first[key] = vintage_text
    for index, series_id, observation, _vintage in parsed:
        materialized[index]["series_id"] = series_id
        materialized[index]["original_realtime_start"] = first[(series_id, observation)]
    return tuple(materialized)


def stamp_scheduled_availability(
    rows: Iterable[Mapping[str, Any]],
    *,
    clock: time = SCHEDULED_PRINT_ET,
    tz: ZoneInfo = EASTERN,
) -> tuple[dict[str, Any], ...]:
    """Attach timezone-aware ``available_at`` from each vintage date and a clock.

    ALFRED does not provide a release time.  Callers that want the 08:30 ET
    scheduled-print convention use this helper; the adapter will not invent a
    time on its own.  An already-present ``available_at`` is validated rather
    than overwritten.
    """
    if clock.tzinfo is not None:
        raise ExogenousContractError("release clock is a local time, not an offset")
    stamped = []
    for row in rows:
        item = dict(row)
        existing = item.get("available_at")
        if existing is not None:
            _parse_aware_datetime(existing, label="available_at")
            stamped.append(item)
            continue
        vintage = _parse_alfred_date(item.get("realtime_start"), label="realtime_start")
        item["available_at"] = datetime.combine(vintage, clock, tzinfo=tz).isoformat()
        stamped.append(item)
    return tuple(stamped)


def api_key_from_env() -> str:
    """Return ``FRED_API_KEY`` or fail closed without touching the network."""
    key = os.environ.get("FRED_API_KEY", "").strip()
    if not key:
        raise MissingAlfredCredentialsError(
            "FRED_API_KEY is required for a live ALFRED fetch"
        )
    return key


def fetch_alfred_vintage_dates(
    series_id: str,
    *,
    realtime_start: str,
    realtime_end: str,
    api_key: str | None = None,
    transport: Transport | None = None,
) -> tuple[str, ...]:
    """List ALFRED vintage dates.  Optional; not invoked by tests or ingest."""
    key = api_key if api_key is not None else api_key_from_env()
    _require_key(key)
    series = _required_text(series_id, label="series_id")
    start = _parse_alfred_date(realtime_start, label="realtime_start").isoformat()
    end = _parse_alfred_date(realtime_end, label="realtime_end").isoformat()
    payload = _alfred_get(
        VINTAGE_DATES_PATH,
        {"series_id": series, "realtime_start": start, "realtime_end": end},
        api_key=key,
        transport=transport,
    )
    dates = payload.get("vintage_dates")
    if not isinstance(dates, list):
        raise AlfredError("ALFRED vintage-dates response is unusable")
    parsed = tuple(
        _parse_alfred_date(item, label="vintage_date").isoformat() for item in dates
    )
    claimed = payload.get("count")
    if claimed is not None and int(claimed) != len(parsed):
        raise AlfredError("ALFRED vintage-dates response was truncated")
    return parsed


def fetch_alfred_observations(
    series_id: str,
    *,
    realtime_start: str | None = None,
    realtime_end: str | None = None,
    vintage_dates: str | None = None,
    observation_start: str | None = None,
    observation_end: str | None = None,
    api_key: str | None = None,
    transport: Transport | None = None,
) -> tuple[dict[str, Any], ...]:
    """Pull ALFRED vintage observations.  Optional; not invoked by tests.

    A vintage constraint is mandatory: either ``vintage_dates`` or both
    ``realtime_start`` and ``realtime_end``.  Observation bounds are optional
    but, when supplied, must be provided as a pair.  Omitting the vintage
    constraint would hit the current-view default (realtime period = today)
    and is refused.
    """
    key = api_key if api_key is not None else api_key_from_env()
    _require_key(key)
    series = _required_text(series_id, label="series_id")
    query = _vintage_query(
        realtime_start=realtime_start,
        realtime_end=realtime_end,
        vintage_dates=vintage_dates,
    )
    has_observation_start = bool(observation_start and str(observation_start).strip())
    has_observation_end = bool(observation_end and str(observation_end).strip())
    if has_observation_start != has_observation_end:
        raise AlfredError("observation_start and observation_end must be supplied together")
    if has_observation_start:
        start = _parse_alfred_date(observation_start, label="observation_start")
        end = _parse_alfred_date(observation_end, label="observation_end")
        if end < start:
            raise AlfredError("observation_end precedes observation_start")
        query["observation_start"] = start.isoformat()
        query["observation_end"] = end.isoformat()
    query["series_id"] = series
    query["units"] = VINTAGE_UNITS
    query["output_type"] = VINTAGE_OUTPUT_TYPE
    payload = _alfred_get(
        OBSERVATIONS_PATH, query, api_key=key, transport=transport,
    )
    observations = payload.get("observations")
    if not isinstance(observations, list):
        raise AlfredError("ALFRED observations response is unusable")
    claimed = payload.get("count")
    if claimed is not None and int(claimed) != len(observations):
        raise AlfredError("ALFRED observations response was truncated")
    rows = []
    for index, item in enumerate(observations):
        if not isinstance(item, Mapping):
            raise AlfredError(f"ALFRED observation {index} is not an object")
        row = dict(item)
        row["series_id"] = series
        rows.append(row)
    return annotate_alfred_revisions(rows)


def _vintage_query(
    *,
    realtime_start: str | None,
    realtime_end: str | None,
    vintage_dates: str | None,
) -> dict[str, str]:
    has_start = bool(realtime_start and str(realtime_start).strip())
    has_end = bool(realtime_end and str(realtime_end).strip())
    has_vintages = bool(vintage_dates and str(vintage_dates).strip())
    if has_start != has_end:
        raise AlfredError("realtime_start and realtime_end must be supplied together")
    if has_start == has_vintages:
        raise AlfredError(
            "ALFRED fetch requires vintage_dates or a realtime_start/realtime_end "
            "window, not both, and not neither"
        )
    if has_vintages:
        dates = tuple(
            _parse_alfred_date(part.strip(), label="vintage_dates").isoformat()
            for part in str(vintage_dates).split(",")
            if part.strip()
        )
        if not dates:
            raise AlfredError("vintage_dates is empty")
        return {"vintage_dates": ",".join(dates)}
    start = _parse_alfred_date(realtime_start, label="realtime_start")
    end = _parse_alfred_date(realtime_end, label="realtime_end")
    if end < start:
        raise AlfredError("realtime_end precedes realtime_start")
    return {"realtime_start": start.isoformat(), "realtime_end": end.isoformat()}


def _require_key(key: str) -> None:
    if not isinstance(key, str) or not key.strip():
        raise MissingAlfredCredentialsError(
            "FRED_API_KEY is required for a live ALFRED fetch"
        )


def _default_transport(method: str, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
    request = Request(url, headers=headers, method=method)
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, response.read()
    except HTTPError as exc:
        raise AlfredError(
            f"ALFRED {method} failed closed with HTTP {exc.code}"
        ) from exc
    except URLError as exc:
        raise AlfredError("ALFRED request failed closed") from exc


def _alfred_get(
    path: str,
    query: Mapping[str, str],
    *,
    api_key: str,
    transport: Transport | None,
) -> dict[str, Any]:
    if path not in {OBSERVATIONS_PATH, VINTAGE_DATES_PATH}:
        raise AlfredError("ALFRED fetch is pinned to vintage endpoints")
    params = dict(query)
    params["api_key"] = api_key
    params["file_type"] = "json"
    url = f"{API_ROOT}{path}?{urlencode(params)}"
    status, raw = (transport or _default_transport)("GET", url, {"Accept": "application/json"})
    if status < 200 or status >= 300:
        raise AlfredError(f"ALFRED GET failed closed with HTTP {status}")
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AlfredError("ALFRED response was not JSON") from exc
    if not isinstance(parsed, dict):
        raise AlfredError("ALFRED response was not an object")
    return parsed


def _external_id(series_id: str, observation_date: date, vintage_date: date) -> str:
    """Stable vintage identity so ``assert_stable_availability`` can fire.

    The vintage date is part of the id: a revision is a different fact, not a
    retimestamp of the original.  Re-pulling the same vintage with a moved
    ``available_at`` keeps this id and is rejected.
    """
    return f"alfred:{series_id}:{observation_date.isoformat()}:{vintage_date.isoformat()}"


def _required_text(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExogenousContractError(f"{label} is missing")
    return value.strip()


def _parse_alfred_date(value: object, *, label: str) -> date:
    text = _required_text(str(value) if isinstance(value, date) else value, label=label)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ExogenousContractError(f"{label} is not YYYY-MM-DD") from exc
    return parsed


def _parse_aware_datetime(value: object, *, label: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError as exc:
            raise ExogenousContractError(f"{label} is not ISO-8601") from exc
    else:
        raise ExogenousContractError(f"{label} is missing")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ExogenousContractError(f"{label} must be timezone-aware")
    return parsed


def _numeric_value(value: object) -> str:
    if value in (None, "", "."):
        raise ExogenousContractError("ALFRED observation value is missing")
    text = str(value).strip()
    try:
        float(text)
    except (TypeError, ValueError) as exc:
        raise ExogenousContractError("ALFRED observation value is not numeric") from exc
    return text
