"""Load local intraday bars. This module does not open a socket."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from athena_trading.orb_m.market import Bar

from .types import HoldoutRefusal, ReplayRefusal

_EASTERN = ZoneInfo("America/New_York")
_ALLOWED_PROVENANCE = frozenset({"POINT_IN_TIME", "CURRENT_SNAPSHOT", "FIXTURE"})
_HOLDOUT_MARKERS = ("holdout", "invalid_evidence")


@dataclass(frozen=True)
class SymbolDay:
    """One symbol on one regular session, with only the bars in the file."""

    session: str
    symbol: str
    atr14: float
    bars: tuple[Bar, ...]


@dataclass(frozen=True)
class BarFile:
    provenance: str
    days: tuple[SymbolDay, ...]
    source: str
    universe_members: tuple[str, ...] | None
    note: str


def load_bars(path: Path) -> BarFile:
    """Read a local JSON file or a directory of JSON files."""
    source = Path(path)
    _refuse_remote(source)
    _refuse_holdout_path(source)
    if source.is_dir():
        files = sorted(item for item in source.glob("*.json") if item.is_file())
        if not files:
            raise ReplayRefusal(f"no JSON bar files in {source}")
        loaded = [load_bars(item) for item in files]
        provenance = loaded[0].provenance
        if any(item.provenance != provenance for item in loaded):
            raise ReplayRefusal("every file in a replay directory uses the same provenance")
        members = loaded[0].universe_members
        days = tuple(day for item in loaded for day in item.days)
        return BarFile(provenance, days, str(source), members, loaded[0].note)
    if not source.is_file():
        raise ReplayRefusal(f"bar file does not exist: {source}")
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ReplayRefusal("bar file must be a JSON object")
    _refuse_holdout_payload(payload)
    provenance = str(payload.get("provenance", "")).strip()
    if provenance not in _ALLOWED_PROVENANCE:
        raise ReplayRefusal(
            "provenance must be POINT_IN_TIME, CURRENT_SNAPSHOT, or FIXTURE"
        )
    members = _members(payload.get("universe_members"))
    note = str(payload.get("note", ""))
    sessions = payload.get("sessions")
    if not isinstance(sessions, list) or not sessions:
        raise ReplayRefusal("sessions must be a non-empty list")
    days = tuple(_day(row) for row in sessions)
    if members is not None:
        allowed = set(members)
        days = tuple(day for day in days if day.symbol in allowed)
    return BarFile(provenance, days, str(source), members, note)


def _refuse_remote(path: Path) -> None:
    text = str(path)
    if "://" in text:
        raise ReplayRefusal("replay reads local files only")


def _refuse_holdout_path(path: Path) -> None:
    haystack = " ".join(part.lower() for part in path.parts)
    if any(marker in haystack for marker in _HOLDOUT_MARKERS):
        raise HoldoutRefusal("holdouts are not read")


def _refuse_holdout_payload(payload: dict) -> None:
    markers = {"holdout", "consumed_holdout", "invalid_evidence"}
    if markers & {str(key).lower() for key in payload}:
        raise HoldoutRefusal("holdouts are not read")


def _members(value: object) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not value:
        raise ReplayRefusal("universe_members must be a non-empty list of symbols")
    symbols = tuple(str(item).strip() for item in value)
    if any(not item for item in symbols) or len(set(symbols)) != len(symbols):
        raise ReplayRefusal("universe_members must be unique symbols")
    return symbols


def _day(row: object) -> SymbolDay:
    if not isinstance(row, dict):
        raise ReplayRefusal("each session row must be an object")
    session = str(row.get("session", "")).strip()
    symbol = str(row.get("symbol", "")).strip()
    if not session or not symbol:
        raise ReplayRefusal("session and symbol are required")
    try:
        session_date = date.fromisoformat(session)
    except ValueError as exc:
        raise ReplayRefusal(f"session {session!r} is not YYYY-MM-DD") from exc
    try:
        atr14 = float(row["atr14"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ReplayRefusal(f"{symbol} {session} needs a positive atr14") from exc
    if atr14 <= 0:
        raise ReplayRefusal(f"{symbol} {session} needs a positive atr14")
    raw_bars = row.get("bars")
    if not isinstance(raw_bars, list) or not raw_bars:
        raise ReplayRefusal(f"{symbol} {session} needs bars")
    bars = tuple(_bar(session_date, symbol, item) for item in raw_bars)
    minutes = [bar.minute for bar in bars]
    if len(minutes) != len(set(minutes)):
        raise ReplayRefusal(f"{symbol} {session} repeats a minute")
    return SymbolDay(session, symbol, atr14, bars)


def _bar(session_date: date, symbol: str, row: object) -> Bar:
    if not isinstance(row, dict):
        raise ReplayRefusal(f"{symbol} bar must be an object")
    try:
        minute = int(row["minute"])
        prices = [float(row[name]) for name in ("open", "high", "low", "close")]
        volume = float(row["volume"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ReplayRefusal(f"{symbol} bar is missing a field") from exc
    event_at = datetime.combine(session_date, time(9, 30), tzinfo=_EASTERN) + timedelta(
        minutes=minute,
    )
    try:
        return Bar(event_at, minute, prices[0], prices[1], prices[2], prices[3], volume)
    except ValueError as exc:
        raise ReplayRefusal(f"{symbol} minute {minute} is not a valid bar: {exc}") from exc
