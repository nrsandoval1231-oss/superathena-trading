"""Recorded / fixture bar sessions for the paper walker.

Massive remains the historical provider. This format exists so CI and an
operator can walk bars without a provider pull. Live streaming is not this
module.

Schema ``athena-orb-m-paper-bars-v1``::

    {
      "schema_version": "athena-orb-m-paper-bars-v1",
      "symbol": "AAPL",
      "prior": {
        "previous_close": 100.0,
        "atr14": 2.0,
        "average_daily_volume": 5000000.0,
        "average_opening_volume": 20000.0
      },
      "bars": [
        {
          "event_at": "2026-03-02T14:30:00+00:00",
          "minute": 0,
          "open": 100.0,
          "high": 100.5,
          "low": 99.5,
          "close": 100.2,
          "volume": 2000.0
        }
      ]
    }

Timestamps must be timezone-aware. Naive values fail closed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from ..paths import config_file

from ..orb_m.market import Bar, PriorSession

BARS_SCHEMA = "athena-orb-m-paper-bars-v1"
DEFAULT_BARS_PATH = config_file("fixtures", "orb_m_paper_bars_v1.json")


@dataclass(frozen=True)
class BarSession:
    symbol: str
    prior: PriorSession
    bars: tuple[Bar, ...]

    def __post_init__(self) -> None:
        if not self.symbol or self.symbol != self.symbol.strip().upper():
            raise ValueError("symbol must be a non-empty uppercase ticker")
        if not self.bars:
            raise ValueError("bar session must contain at least one bar")


def load_bar_session(path: str | Path) -> BarSession:
    """Load a recorded session. Unknown schemas and naive timestamps fail closed."""
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("bar session must be an object")
    if value.get("schema_version") != BARS_SCHEMA:
        raise ValueError("unexpected bar session schema")
    symbol = str(value.get("symbol", "")).strip().upper()
    prior_raw = value.get("prior")
    bars_raw = value.get("bars")
    if not isinstance(prior_raw, dict) or not isinstance(bars_raw, list):
        raise ValueError("bar session requires prior and bars")
    prior = PriorSession(
        previous_close=float(prior_raw["previous_close"]),
        atr14=float(prior_raw["atr14"]),
        average_daily_volume=float(prior_raw["average_daily_volume"]),
        average_opening_volume=float(prior_raw["average_opening_volume"]),
    )
    bars = tuple(_bar_from_payload(item) for item in bars_raw)
    return BarSession(symbol, prior, bars)


def _bar_from_payload(item: object) -> Bar:
    if not isinstance(item, dict):
        raise ValueError("each bar must be an object")
    event_at = datetime.fromisoformat(str(item["event_at"]))
    if event_at.tzinfo is None or event_at.utcoffset() is None:
        raise ValueError("bar timestamps must be timezone-aware")
    return Bar(
        event_at,
        int(item["minute"]),
        float(item["open"]),
        float(item["high"]),
        float(item["low"]),
        float(item["close"]),
        float(item["volume"]),
    )
