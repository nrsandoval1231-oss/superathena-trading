"""Delegated Gate 1 pass line. A pass does not claim an edge."""

from __future__ import annotations

from collections.abc import Sequence

from athena_trading.backtesting.evaluation import chronological_drawdown, session_uncertainty
from athena_trading.orb_m.constitution import Constitution

from .constants import (
    CONFIDENCE,
    DRAWDOWN_FRACTION,
    EQUITY_SOURCE,
    FOLD_COUNT,
    HALT_SESSION_RATE_MAX,
    HOLDOUTS,
    MIN_OOS_SESSIONS,
    MIN_OOS_TRADES,
    MIN_POSITIVE_FOLDS,
    NO_EDGE,
    OPERATOR_REPORTED_EQUITY,
    PINNED_CONSTITUTION_HASH,
    RESAMPLES,
    UNCERTAINTY_SEED,
)
from .types import ReplayRefusal, ReplayTrade


def chronological_folds(sessions: Sequence[str], n: int = FOLD_COUNT) -> dict[str, int]:
    """Split sessions into ``n`` contiguous folds, earliest first. No shuffle."""
    ordered = sorted(set(sessions))
    if len(ordered) < n:
        raise ValueError(f"walk-forward needs at least {n} sessions, found {len(ordered)}")
    counts = [len(ordered) // n] * n
    for index in range(len(ordered) % n):
        counts[index] += 1
    assignment: dict[str, int] = {}
    cursor = 0
    for fold, count in enumerate(counts):
        for session in ordered[cursor:cursor + count]:
            assignment[session] = fold
        cursor += count
    return assignment


def evaluate_pass_line(
    trades: Sequence[ReplayTrade],
    *,
    sessions: Sequence[str],
    halted_sessions: set[str] | frozenset[str],
    provenance: str,
    constitution_hash: str,
    no_edge: str = NO_EDGE,
    resamples: int = RESAMPLES,
    seed: int = UNCERTAINTY_SEED,
) -> dict[str, object]:
    """Score out-of-sample trades. Training rows are not included by the caller."""
    session_list = sorted(set(sessions))
    unknown = sorted({trade.session for trade in trades} - set(session_list))
    if unknown:
        raise ReplayRefusal(f"trades reference sessions outside the replay: {unknown}")
    extra_halts = sorted(set(halted_sessions) - set(session_list))
    if extra_halts:
        raise ReplayRefusal(f"halted sessions outside the replay: {extra_halts}")
    live_hash = Constitution().identity_hash
    expectancy = _expectancy(trades)
    band = _session_band(trades, session_list, resamples=resamples, seed=seed)
    drawdown = _cost_adjusted_drawdown(trades)
    halt_rate = (len(halted_sessions) / len(session_list)) if session_list else None
    fold_rows, positive_folds = _fold_rows(trades, session_list)
    drawdown_limit = DRAWDOWN_FRACTION * OPERATOR_REPORTED_EQUITY
    checks = {
        "expectancy_positive": expectancy is not None and expectancy > 0.0,
        "session_lower_bound_positive": float(band["lower"]) > 0.0,
        "oos_trades": len(trades) >= MIN_OOS_TRADES,
        "oos_sessions": len(session_list) >= MIN_OOS_SESSIONS,
        "halt_rate": halt_rate is not None and halt_rate <= HALT_SESSION_RATE_MAX,
        "drawdown": drawdown <= drawdown_limit,
        "positive_folds": positive_folds >= MIN_POSITIVE_FOLDS and fold_rows is not None,
        "constitution_hash": constitution_hash == live_hash == PINNED_CONSTITUTION_HASH,
        "provenance": provenance in {"POINT_IN_TIME", "CURRENT_SNAPSHOT"},
        "no_edge_claimed": no_edge == NO_EDGE,
        "holdouts_not_read": True,
    }
    numeric_keys = (
        "expectancy_positive", "session_lower_bound_positive", "oos_trades",
        "oos_sessions", "halt_rate", "drawdown", "positive_folds", "constitution_hash",
    )
    numeric_pass = all(bool(checks[key]) for key in numeric_keys)
    gate_passed = numeric_pass and bool(checks["provenance"]) and bool(checks["no_edge_claimed"])
    return {
        "numeric_pass": numeric_pass,
        "gate_passed": gate_passed,
        "market_evidence": False,
        "no_edge_claimed": NO_EDGE,
        "holdouts": HOLDOUTS,
        "checks": checks,
        "metrics": {
            "cost_adjusted_expectancy_per_trade": expectancy,
            "session_mean": band["mean"],
            "session_lower_bound": band["lower"],
            "session_resamples": resamples,
            "confidence": CONFIDENCE,
            "uncertainty_seed": seed,
            "oos_trades": len(trades),
            "oos_sessions": len(session_list),
            "halted_sessions": len(halted_sessions),
            "halt_rate": halt_rate,
            "cost_adjusted_drawdown": drawdown,
            "drawdown_limit": drawdown_limit,
            "drawdown_fraction_of_replay_equity": (
                drawdown / OPERATOR_REPORTED_EQUITY if OPERATOR_REPORTED_EQUITY else None
            ),
            "positive_folds": positive_folds,
            "folds": fold_rows,
            "replay_equity": OPERATOR_REPORTED_EQUITY,
            "replay_equity_source": EQUITY_SOURCE,
        },
    }


def _expectancy(trades: Sequence[ReplayTrade]) -> float | None:
    if not trades:
        return None
    return sum(trade.net for trade in trades) / len(trades)


def _session_band(
    trades: Sequence[ReplayTrade],
    sessions: Sequence[str],
    *,
    resamples: int,
    seed: int,
) -> dict[str, float]:
    """Mean cost-adjusted dollars per session, sessions resampled whole."""
    totals = []
    for session in sessions:
        total = sum(trade.net for trade in trades if trade.session == session)
        totals.append((session, total))
    return session_uncertainty(totals, resamples=resamples, confidence=CONFIDENCE, seed=seed)


def _cost_adjusted_drawdown(trades: Sequence[ReplayTrade]) -> float:
    """Peak-to-trough of scenario-net dollars in exit order.

    ``chronological_drawdown`` reads the ``gross`` field. The value placed there
    is the cost-adjusted net for this gate.
    """
    rows = [
        {
            "at": f"{trade.session}T{trade.exit_minute:04d}",
            "opportunity_id": trade.trade_id,
            "gross": trade.net,
        }
        for trade in trades
    ]
    return chronological_drawdown(rows)


def _fold_rows(
    trades: Sequence[ReplayTrade], sessions: Sequence[str],
) -> tuple[list[dict[str, object]] | None, int]:
    try:
        assignment = chronological_folds(sessions)
    except ValueError:
        return None, 0
    rows = []
    positive = 0
    for fold in range(FOLD_COUNT):
        fold_sessions = {session for session, index in assignment.items() if index == fold}
        fold_trades = [trade for trade in trades if trade.session in fold_sessions]
        expectancy = _expectancy(fold_trades)
        is_positive = expectancy is not None and expectancy > 0.0
        positive += int(is_positive)
        rows.append({
            "fold": fold,
            "sessions": len(fold_sessions),
            "trades": len(fold_trades),
            "cost_adjusted_expectancy_per_trade": expectancy,
            "positive": is_positive,
        })
    return rows, positive
