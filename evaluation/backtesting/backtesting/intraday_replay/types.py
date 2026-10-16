"""Replay records. These are research rows, not orders."""

from __future__ import annotations

from dataclasses import dataclass


class ReplayRefusal(ValueError):
    """The replay will not score this input."""


class ConstitutionDrift(ReplayRefusal):
    """The frozen ORB constitution hash does not match this harness."""


class HoldoutRefusal(ReplayRefusal):
    """Consumed holdouts and invalid-evidence artifacts are not read."""


@dataclass(frozen=True)
class ReplayTrade:
    """One closed, cost-adjusted round trip. Share count stays at one."""

    trade_id: str
    session: str
    symbol: str
    family: str
    direction: str
    signal_minute: int
    entry_minute: int
    exit_minute: int
    decision_close: float
    entry: float
    exit: float
    gross: float
    cost: float
    net: float
    reason: str
    gapped_through_stop: bool
    prior_id: str | None = None
    shares: int = 1

    def __post_init__(self) -> None:
        if self.direction not in {"LONG", "SHORT"}:
            raise ValueError("direction must be LONG or SHORT")
        if self.shares != 1:
            raise ValueError("replay quantity is one share")
        if self.exit_minute < self.entry_minute:
            raise ValueError("exit minute precedes entry")
        if self.entry <= 0 or self.exit <= 0 or self.decision_close <= 0:
            raise ValueError("trade prices must be positive")


@dataclass(frozen=True)
class Skip:
    session: str
    symbol: str
    reason: str
    minute: int
    trade_id: str | None = None


@dataclass(frozen=True)
class GenerateResult:
    trades: tuple[ReplayTrade, ...]
    skips: tuple[Skip, ...]


@dataclass(frozen=True)
class BookResult:
    trades: tuple[ReplayTrade, ...]
    skips: tuple[Skip, ...]
    halted_sessions: frozenset[str]
    ending_equity: float
