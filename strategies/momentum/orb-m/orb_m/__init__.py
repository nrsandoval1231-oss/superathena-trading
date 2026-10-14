"""Athena ORB-M v1.0 — deterministic 15-minute opening-range breakout engine.

The constitution is immutable and defines the strategy.  Athena adapts only the
management parameters enumerated in ``ADAPTIVE_SURFACE``; it does not invent or
alter the strategy itself.
"""
from .constitution import (
    ADAPTIVE_SURFACE, BreakoutAction, Constitution, ManagementParameters, TrailStage,
)
from .deterioration import DeteriorationContext, detect_signals, pressure_by_minute
from .entry import (
    AttemptBudget, BreakoutSignal, OpeningRange, RiskFrame, build_risk_frame,
    detect_breakout, freeze_opening_range,
)
from .execution import ExecutionResult, run_position
from .management import (
    PositionState, action_for, exit_pressure, stage_for, trail_stop_r,
)
from .quality import (
    COMPONENT_NAMES, BreakoutQualityInputs, BreakoutQualityResult, score_breakout,
)
from .session import (
    EpisodeRecord, SessionEpisode, SessionResult, SessionRiskState,
    SymbolSessionResult, deterioration_by_minute, quality_for, run_full_session,
    run_symbol_session,
)
from .universe import (
    PoolProvenance, SelectionRule, SymbolStatistics, UniverseManifest,
    select_universe,
)
from .market import (
    Bar, PremarketContext, PriorSession, average_true_range, gap_percent,
    premarket_context, relative_volume, session_vwap, true_range,
)

__all__ = [
    "ADAPTIVE_SURFACE", "AttemptBudget", "Bar", "BreakoutAction", "BreakoutSignal",
    "BreakoutQualityInputs", "BreakoutQualityResult", "COMPONENT_NAMES",
    "Constitution", "DeteriorationContext", "EpisodeRecord", "ExecutionResult",
    "ManagementParameters", "OpeningRange",
    "PoolProvenance", "PositionState", "PremarketContext", "PriorSession",
    "RiskFrame", "SelectionRule", "SessionEpisode", "SessionResult",
    "SessionRiskState", "SymbolStatistics",
    "SymbolSessionResult", "TrailStage", "UniverseManifest",
    "action_for", "average_true_range", "build_risk_frame", "detect_breakout",
    "detect_signals", "deterioration_by_minute", "exit_pressure",
    "freeze_opening_range", "gap_percent",
    "premarket_context", "pressure_by_minute", "quality_for", "relative_volume",
    "run_full_session", "run_position", "run_symbol_session", "score_breakout",
    "select_universe", "session_vwap", "stage_for", "trail_stop_r", "true_range",
]
