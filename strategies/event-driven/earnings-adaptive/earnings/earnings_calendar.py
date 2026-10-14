"""Free earnings calendar used by the paper earnings arm.

Source: Nasdaq's public calendar JSON at
``https://api.nasdaq.com/api/calendar/earnings?date=YYYY-MM-DD``. No API key.

Limits, which are part of the trading policy:

- The endpoint is undocumented, keyless, and has no availability guarantee.
  Datacenter addresses are often refused unless the request sends a browser
  User-Agent. A failed read blocks new entries and does not invent a calendar.
- One request is one calendar day. Rows are the names Nasdaq lists for that
  date, not a point-in-time archive. Historical revisions are not detectable.
- ``time`` is one of ``time-pre-market`` (before the open), ``time-after-hours``
  (after the close), or ``time-not-supplied``. Only the first two can schedule
  an entry. An unknown or missing time is skipped.
- The payload has no surprise, guidance, or historical-reaction fields. EPS
  text is ignored. The screener's 4–12% band is applied later to the price gap.
- Symbols are normalized to Alpaca form (``BRK/B`` and ``BRK-B`` become
  ``BRK.B``). A symbol that is not a US equity ticker is skipped.
- This module does not trade and does not call the endpoint unless a transport
  is supplied by the runner.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import urlencode

NASDAQ_EARNINGS_URL = "https://api.nasdaq.com/api/calendar/earnings"
NASDAQ_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}
# Nasdaq's public calendar uses these tokens. Anything else is not a session.
_WHEN = {
    "time-pre-market": "BMO",
    "time-after-hours": "AMC",
}
_SYMBOL = re.compile(r"[A-Z][A-Z0-9.]{0,9}")


@dataclass(frozen=True)
class EarningsReport:
    """One scheduled report whose session is known."""

    symbol: str
    report_date: str
    when: str  # BMO or AMC


def normalize_symbol(value: Any) -> str | None:
    """Return an Alpaca-style ticker, or None when the value is not one."""
    if not isinstance(value, str):
        return None
    text = value.strip().upper().replace("/", ".").replace("-", ".")
    if not _SYMBOL.fullmatch(text):
        return None
    return text


def _rows(payload: Any) -> list[Any] | None:
    """Accept the live ``data.rows`` shape and the older ``data.calendar.rows`` shape."""
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    rows = data.get("rows")
    if rows is None and isinstance(data.get("calendar"), dict):
        rows = data["calendar"].get("rows")
    if rows is None:
        return []
    if not isinstance(rows, list):
        return None
    return rows


def parse_nasdaq_calendar(
    payload: Any, *, report_date: str,
) -> tuple[list[EarningsReport], list[dict[str, str]]]:
    """Parse one day. Returns usable reports and one skip record per rejected row.

    ``report_date`` is the day that was requested, ``YYYY-MM-DD``. The payload
    does not carry a reliable per-row date.
    """
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", report_date):
        raise ValueError("earnings calendar date must be YYYY-MM-DD")
    rows = _rows(payload)
    if rows is None:
        raise ValueError("Nasdaq earnings calendar payload is unusable")
    reports: list[EarningsReport] = []
    skipped: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            skipped.append({"symbol": "", "reason": "ROW_NOT_AN_OBJECT"})
            continue
        symbol = normalize_symbol(row.get("symbol"))
        if symbol is None:
            skipped.append({"symbol": str(row.get("symbol", ""))[:16], "reason": "BAD_SYMBOL"})
            continue
        when = _WHEN.get(str(row.get("time", "")).strip().lower())
        if when is None:
            skipped.append({"symbol": symbol, "reason": "TIME_UNKNOWN"})
            continue
        if symbol in seen:
            skipped.append({"symbol": symbol, "reason": "DUPLICATE_SYMBOL"})
            continue
        seen.add(symbol)
        reports.append(EarningsReport(symbol, report_date, when))
    return reports, skipped


def nasdaq_earnings_url(day: date) -> str:
    return NASDAQ_EARNINGS_URL + "?" + urlencode({"date": day.isoformat()})
