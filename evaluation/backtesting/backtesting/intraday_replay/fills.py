"""Next-open fills, ADVERSE_FIRST, one open position, and the 0.5% halt.

The decision close is not a fill. A bar that touches the stop and the target
exits at the stop. The approved daily-loss halt stops new entries for the rest
of that session and resets the next session.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from athena_trading.orb_m.market import Bar

from .constants import (
    DAILY_LOSS_FRACTION,
    MAX_STOP_RISK,
    OPERATOR_REPORTED_EQUITY,
    QUANTITY,
    TARGET_R,
)
from .costs import scenario_cost
from .types import BookResult, ReplayTrade, Skip


@dataclass(frozen=True)
class WalkResult:
    entry: float
    exit: float
    entry_minute: int
    exit_minute: int
    gross: float
    cost: float
    net: float
    reason: str
    gapped_through_stop: bool
    skipped_reason: str | None = None


def walk_bracket(
    bars: Sequence[Bar],
    *,
    direction: str,
    signal_minute: int,
    decision_close: float,
    stop: float,
    target_price: float | None,
    target_r: float = TARGET_R,
    deadline_minute: int,
    hard_flat_minute: int,
    notional_cap: float,
) -> WalkResult | None:
    """Fill at the next open and walk out under ADVERSE_FIRST."""
    if direction not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG or SHORT")
    if target_r != TARGET_R:
        raise ValueError("target multiple stays at the approved 2R")
    future = tuple(sorted(
        (bar for bar in bars if bar.minute > signal_minute),
        key=lambda bar: bar.minute,
    ))
    if not future:
        return None
    entry_bar = future[0]
    if entry_bar.minute >= hard_flat_minute:
        return None
    side = 1.0 if direction == "LONG" else -1.0
    intended = (decision_close - stop) * side
    if intended <= 0:
        return _skipped(entry_bar, "INVALID_STOP")
    if intended > MAX_STOP_RISK:
        return _skipped(entry_bar, "STOP_CAP")
    entry = entry_bar.open
    if entry > notional_cap:
        return _skipped(entry_bar, "NOTIONAL_CAP")
    if (stop - entry) * side >= 0:
        return _closed(
            entry_minute=entry_bar.minute, exit_bar=entry_bar, entry=entry, exit_price=entry,
            reason="GAP_THROUGH_STOP", decision_close=decision_close, side=side, gapped=True,
        )
    risk = (entry - stop) * side
    target = entry + side * target_r * risk if target_price is None else target_price
    if (target - entry) * side <= 0:
        return _closed(
            entry_minute=entry_bar.minute, exit_bar=entry_bar, entry=entry, exit_price=entry,
            reason="GAP_THROUGH_TARGET", decision_close=decision_close, side=side, gapped=False,
        )
    for bar in future:
        if bar.minute >= hard_flat_minute:
            return _closed(
                entry_minute=entry_bar.minute, exit_bar=bar, entry=entry, exit_price=bar.open,
                reason="HARD_FLAT", decision_close=decision_close, side=side, gapped=False,
            )
        stop_hit = bar.low <= stop if direction == "LONG" else bar.high >= stop
        target_hit = bar.high >= target if direction == "LONG" else bar.low <= target
        if stop_hit:
            fill = min(bar.open, stop) if direction == "LONG" else max(bar.open, stop)
            gapped = (bar.open - stop) * side <= 0
            reason = "GAP_THROUGH_STOP" if gapped else "STOP"
            return _closed(
                entry_minute=entry_bar.minute, exit_bar=bar, entry=entry, exit_price=fill,
                reason=reason, decision_close=decision_close, side=side, gapped=gapped,
            )
        if target_hit:
            return _closed(
                entry_minute=entry_bar.minute, exit_bar=bar, entry=entry, exit_price=target,
                reason="TARGET", decision_close=decision_close, side=side, gapped=False,
            )
        if bar.minute >= deadline_minute:
            return _closed(
                entry_minute=entry_bar.minute, exit_bar=bar, entry=entry, exit_price=bar.close,
                reason="SESSION_DEADLINE", decision_close=decision_close, side=side, gapped=False,
            )
    last = future[-1]
    return _closed(
        entry_minute=entry_bar.minute, exit_bar=last, entry=entry, exit_price=last.close,
        reason="DATA_EXHAUSTED", decision_close=decision_close, side=side, gapped=False,
    )


def apply_book(
    trades: Sequence[ReplayTrade],
    *,
    equity: float = OPERATOR_REPORTED_EQUITY,
    loss_fraction: float = DAILY_LOSS_FRACTION,
) -> BookResult:
    """Take one position at a time and halt new entries after the daily loss."""
    if loss_fraction != DAILY_LOSS_FRACTION:
        raise ValueError("daily-loss fraction stays at the approved 0.005")
    if equity <= 0:
        raise ValueError("replay equity must be positive")
    grouped: dict[str, list[ReplayTrade]] = defaultdict(list)
    for trade in trades:
        grouped[trade.session].append(trade)
    taken: list[ReplayTrade] = []
    skips: list[Skip] = []
    halted: set[str] = set()
    for session in sorted(grouped):
        last_equity = equity
        halt_level = last_equity * (1.0 - loss_fraction)
        session_halted = False
        flat_until = -1
        taken_ids: set[str] = set()
        ordered = sorted(
            grouped[session],
            key=lambda trade: (trade.entry_minute, trade.symbol, trade.trade_id),
        )
        for trade in ordered:
            if trade.prior_id is not None and trade.prior_id not in taken_ids:
                skips.append(_skip(trade, "PRIOR_NOT_TAKEN"))
                continue
            if session_halted:
                skips.append(_skip(trade, "HALTED"))
                continue
            if trade.entry_minute <= flat_until:
                skips.append(_skip(trade, "NOT_FLAT"))
                continue
            taken.append(trade)
            taken_ids.add(trade.trade_id)
            equity += trade.net
            flat_until = trade.exit_minute
            if equity <= halt_level:
                session_halted = True
                halted.add(session)
    return BookResult(tuple(taken), tuple(skips), frozenset(halted), equity)


def _skip(trade: ReplayTrade, reason: str) -> Skip:
    return Skip(trade.session, trade.symbol, reason, trade.entry_minute, trade.trade_id)


def _skipped(bar: Bar, reason: str) -> WalkResult:
    return WalkResult(
        entry=bar.open, exit=bar.open, entry_minute=bar.minute, exit_minute=bar.minute,
        gross=0.0, cost=0.0, net=0.0, reason=reason, gapped_through_stop=False,
        skipped_reason=reason,
    )


def _closed(
    *,
    entry_minute: int,
    exit_bar: Bar,
    entry: float,
    exit_price: float,
    reason: str,
    decision_close: float,
    side: float,
    gapped: bool,
) -> WalkResult:
    gross = (exit_price - entry) * side * QUANTITY
    cost = scenario_cost(
        entry=entry, exit_price=exit_price, decision_price=decision_close, shares=QUANTITY,
    )
    return WalkResult(
        entry=entry, exit=exit_price, entry_minute=entry_minute, exit_minute=exit_bar.minute,
        gross=gross, cost=cost, net=gross - cost, reason=reason,
        gapped_through_stop=gapped,
    )
