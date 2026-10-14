"""Point-in-time universe selection and an immutable frozen manifest.

Selection must be decidable using only information available *before* the
campaign window opens.  Ranking today's liquid names and then backtesting them
over the last two years selects survivors, and no amount of partition
discipline afterwards removes the resulting upward bias.

Two guards enforce that here.  The lookback window must end on or before the
campaign start, and the candidate pool must declare its provenance: a pool
assembled from a current listing snapshot is recorded as such, so the bias is
visible in the manifest rather than hidden in it.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from ..athena_adapter.contracts import canonical_hash


class PoolProvenance(StrEnum):
    """How the candidate list was assembled."""

    #: Constituents as listed at the lookback window, from a historical source.
    POINT_IN_TIME = "POINT_IN_TIME"
    #: Symbols known to be listed today. Carries survivorship bias by
    #: construction: names delisted during the window cannot appear.
    CURRENT_SNAPSHOT = "CURRENT_SNAPSHOT"


@dataclass(frozen=True)
class SelectionRule:
    """Frozen, declared before any outcome is inspected."""

    universe_size: int = 50
    lookback_sessions: int = 60
    min_price: float = 5.0
    min_median_dollar_volume: float = 20_000_000.0
    min_session_coverage: float = 0.95
    rank_by: str = "median_dollar_volume"

    def __post_init__(self) -> None:
        if self.universe_size < 1 or self.lookback_sessions < 1:
            raise ValueError("universe size and lookback must be positive")
        if self.min_price <= 0 or self.min_median_dollar_volume <= 0:
            raise ValueError("liquidity floors must be positive")
        if not 0 < self.min_session_coverage <= 1:
            raise ValueError("session coverage must be within (0, 1]")
        if self.rank_by != "median_dollar_volume":
            raise ValueError("only median_dollar_volume ranking is registered")

    @property
    def identity_hash(self) -> str:
        return canonical_hash(self)


@dataclass(frozen=True)
class SymbolStatistics:
    """Lookback summary for one candidate, computed strictly before the window."""

    symbol: str
    sessions_observed: int
    median_price: float
    median_dollar_volume: float
    median_opening_volume: float

    def __post_init__(self) -> None:
        if not self.symbol or self.sessions_observed < 0:
            raise ValueError("invalid symbol statistics")
        if min(self.median_price, self.median_dollar_volume) < 0:
            raise ValueError("statistics cannot be negative")


@dataclass(frozen=True)
class UniverseManifest:
    """Immutable record of who was selected, by what rule, from what pool."""

    members: tuple[str, ...]
    rule: SelectionRule
    provenance: PoolProvenance
    lookback_start: date
    lookback_end: date
    campaign_start: date
    campaign_end: date
    candidates_considered: int
    rejected_counts: dict

    def __post_init__(self) -> None:
        if len(set(self.members)) != len(self.members):
            raise ValueError("universe contains duplicates")
        if not self.lookback_start < self.lookback_end:
            raise ValueError("lookback window must be ordered")
        if self.lookback_end > self.campaign_start:
            raise ValueError(
                "lookback must end on or before campaign start; selecting on data "
                "from inside the campaign window leaks the outcome into the universe")
        if not self.campaign_start < self.campaign_end:
            raise ValueError("campaign window must be ordered")

    @property
    def carries_survivorship_bias(self) -> bool:
        return self.provenance is PoolProvenance.CURRENT_SNAPSHOT

    @property
    def identity_hash(self) -> str:
        return canonical_hash({
            "members": self.members, "rule": self.rule.identity_hash,
            "provenance": self.provenance.value,
            "lookback": (self.lookback_start.isoformat(), self.lookback_end.isoformat()),
            "campaign": (self.campaign_start.isoformat(), self.campaign_end.isoformat()),
            "candidates_considered": self.candidates_considered,
        })

    def to_payload(self) -> dict:
        return {
            "schema_version": "athena-orb-m-universe-v1",
            "members": list(self.members),
            "universe_size": len(self.members),
            "rule": {**self.rule.__dict__, "rule_hash": self.rule.identity_hash},
            "pool_provenance": self.provenance.value,
            "carries_survivorship_bias": self.carries_survivorship_bias,
            "lookback_start": self.lookback_start.isoformat(),
            "lookback_end": self.lookback_end.isoformat(),
            "campaign_start": self.campaign_start.isoformat(),
            "campaign_end": self.campaign_end.isoformat(),
            "candidates_considered": self.candidates_considered,
            "rejected_counts": dict(sorted(self.rejected_counts.items())),
            "manifest_hash": self.identity_hash,
        }


def select_universe(statistics: Sequence[SymbolStatistics], rule: SelectionRule, *,
                    provenance: PoolProvenance, lookback_start: date, lookback_end: date,
                    campaign_start: date, campaign_end: date) -> UniverseManifest:
    """Apply the frozen rule. Ties break on symbol so the result is reproducible."""
    rejected = {"price": 0, "dollar_volume": 0, "coverage": 0}
    eligible = []
    for item in statistics:
        if item.sessions_observed < rule.min_session_coverage * rule.lookback_sessions:
            rejected["coverage"] += 1
            continue
        if item.median_price < rule.min_price:
            rejected["price"] += 1
            continue
        if item.median_dollar_volume < rule.min_median_dollar_volume:
            rejected["dollar_volume"] += 1
            continue
        eligible.append(item)
    eligible.sort(key=lambda item: (-item.median_dollar_volume, item.symbol))
    members = tuple(item.symbol for item in eligible[:rule.universe_size])
    return UniverseManifest(members, rule, provenance, lookback_start, lookback_end,
                            campaign_start, campaign_end, len(statistics), rejected)
