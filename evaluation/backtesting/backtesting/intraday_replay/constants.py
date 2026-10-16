"""Delegated Stage 0 numbers. Approved risk limits are not revised here."""

from __future__ import annotations

# Operator-reported paper equity. S0-6 has not recorded a measured account.
OPERATOR_REPORTED_EQUITY = 98_900.0
EQUITY_SOURCE = "operator-reported"

# Approved paper limits. The harness enforces these and does not loosen them.
DAILY_LOSS_FRACTION = 0.005
MAX_STOP_RISK = 10.0
MAX_NOTIONAL = 1_000.0
NOTIONAL_EQUITY_FRACTION = 0.01
QUANTITY = 1
TARGET_R = 2.0

# Research gate inside the offline pass line. This is not a live halt.
DRAWDOWN_FRACTION = 0.025
HALT_SESSION_RATE_MAX = 0.05
MIN_OOS_TRADES = 100
MIN_OOS_SESSIONS = 60
FOLD_COUNT = 5
MIN_POSITIVE_FOLDS = 4
CONFIDENCE = 0.95
RESAMPLES = 1_000
UNCERTAINTY_SEED = 7

# paper-cost-scenario-v1. A labeled scenario, not a measured fee schedule.
SLIPPAGE_BPS = 2.0
SLIPPAGE_FLOOR_PER_SHARE = 0.01
SPREAD_BPS = 5.0
SPREAD_FLOOR_PER_SHARE = 0.01
REGULATORY_PER_SHARE_PER_SIDE = 0.01
COMMISSION_PER_SHARE = 0.0
SCENARIO_ID = "paper-cost-scenario-v1"

AUTHORITY = "ABSENT"
REPLAY_ORDER = (
    "frozen_orb_reentry",
    "vwap_reclaim",
    "intraday_momentum",
    "mean_reversion",
)

# Frozen ORB-M constitution identity at the time this harness was added.
# A different hash is a different strategy, and the replay refuses it.
PINNED_CONSTITUTION_HASH = (
    "febafdf0cbe1c0ae451b62522ab778ecd0f8091df3d8ea2c8f1c28a9720610ac"
)

NO_EDGE = "No edge is claimed."
FILL_ASSUMPTION = (
    "next bar open; decision close is not a fill; intrabar path is ADVERSE_FIRST; "
    "capped marketable limit column is absent"
)
PAPER_FILL_LIMITATION = "broker paper fills are not this simulation"
PERFORMANCE = "unverified"
HOLDOUTS = "not read"

# Pre-registered signal definitions for families the repository does not already
# implement. They are research assumptions written before outcomes. They are not
# approved risk limits, and they are not fitted on the replay.
VWAP_LOST_ATR = 1.0
MOMENTUM_LOOKBACK = 20
MEAN_REVERSION_STRETCH_ATR = 1.5
# Matches the frozen one-initial-plus-one-re-entry count so one name cannot loop.
# This does not activate the paper rung.
RESEARCH_MAX_ENTRIES_PER_SYMBOL = 2


def notional_cap(equity: float = OPERATOR_REPORTED_EQUITY) -> float:
    """Approved per-trade notional: the tighter of $1,000 and 1% of equity."""
    return min(MAX_NOTIONAL, equity * NOTIONAL_EQUITY_FRACTION)
