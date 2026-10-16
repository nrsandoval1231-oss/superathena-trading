"""Candidate signals in the delegated replay order.

Frozen ORB re-entry calls the existing simulator and does not edit the
constitution. The other three families are pre-registered research rules.
None of them submits an order. None of them fits a threshold on the sample.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from athena_trading.orb_m.constitution import ManagementParameters
from athena_trading.orb_m.entry import freeze_opening_range
from athena_trading.orb_m.market import session_vwap
from athena_trading.orb_m.session import run_full_session

from .constants import (
    MAX_STOP_RISK,
    MEAN_REVERSION_STRETCH_ATR,
    MOMENTUM_LOOKBACK,
    QUANTITY,
    RESEARCH_MAX_ENTRIES_PER_SYMBOL,
    VWAP_LOST_ATR,
    notional_cap,
)
from .constitution_guard import require_constitution
from .costs import scenario_cost_legs, unslip
from .fills import walk_bracket
from .bars import SymbolDay
from .types import GenerateResult, ReplayRefusal, ReplayTrade, Skip


@dataclass(frozen=True)
class _Setup:
    direction: str
    signal_minute: int
    decision_close: float
    stop: float
    target_price: float | None


class FrozenOrbReentry:
    """Constitution budget: one initial attempt and one re-entry per direction."""

    name = "frozen_orb_reentry"

    def fit(self, training: Sequence[SymbolDay]) -> dict[str, object]:
        del training
        return {"fitted": False}

    def generate(self, days: Sequence[SymbolDay], params: Mapping[str, object]) -> GenerateResult:
        _refuse_fitted(params)
        constitution = require_constitution()
        parameters = ManagementParameters()
        trades: list[ReplayTrade] = []
        skips: list[Skip] = []
        for day in _ordered(days):
            try:
                opening = freeze_opening_range(day.bars, constitution)
            except ValueError:
                skips.append(Skip(day.session, day.symbol, "DATA_DEFERRED", 0))
                continue
            result = run_full_session(
                opening, day.bars, day.atr14, constitution, parameters,
            )
            previous_id: str | None = None
            for index, episode in enumerate(result.episodes):
                trade_id = f"{self.name}:{day.session}:{day.symbol}:{index}"
                trade, skip = _orb_trade(
                    day, episode, trade_id, previous_id, constitution,
                )
                if trade is not None:
                    trades.append(trade)
                if skip is not None:
                    skips.append(skip)
                previous_id = trade_id
        return GenerateResult(tuple(trades), tuple(skips))


class VwapReclaim:
    """A completed close back through session VWAP after a one-ATR loss of it.

    ``session_vwap`` is an input. The ORB quality weight is not an entry.
    """

    name = "vwap_reclaim"

    def fit(self, training: Sequence[SymbolDay]) -> dict[str, object]:
        del training
        return {"fitted": False}

    def generate(self, days: Sequence[SymbolDay], params: Mapping[str, object]) -> GenerateResult:
        _refuse_fitted(params)
        constitution = require_constitution()
        return _scan(days, self.name, constitution, _vwap_setups)


class IntradayMomentum:
    """Close through a 20-bar lookback extreme after the opening range is frozen."""

    name = "intraday_momentum"

    def fit(self, training: Sequence[SymbolDay]) -> dict[str, object]:
        del training
        return {"fitted": False}

    def generate(self, days: Sequence[SymbolDay], params: Mapping[str, object]) -> GenerateResult:
        _refuse_fitted(params)
        constitution = require_constitution()
        ready: list[SymbolDay] = []
        deferred: list[Skip] = []
        for day in _ordered(days):
            try:
                freeze_opening_range(day.bars, constitution)
            except ValueError:
                deferred.append(Skip(day.session, day.symbol, "DATA_DEFERRED", 0))
                continue
            ready.append(day)
        produced = _scan(ready, self.name, constitution, _momentum_setups)
        return GenerateResult(produced.trades, tuple(deferred) + produced.skips)


class LiquidMeanReversion:
    """Fade a 1.5 ATR stretch from session VWAP. Liquidity is a screen."""

    name = "mean_reversion"

    def fit(self, training: Sequence[SymbolDay]) -> dict[str, object]:
        del training
        return {"fitted": False}

    def generate(self, days: Sequence[SymbolDay], params: Mapping[str, object]) -> GenerateResult:
        _refuse_fitted(params)
        constitution = require_constitution()
        return _scan(days, self.name, constitution, _reversion_setups)


def families() -> dict[str, FrozenOrbReentry | VwapReclaim | IntradayMomentum | LiquidMeanReversion]:
    """Replay order: frozen ORB, then VWAP, then momentum, then mean reversion."""
    ordered = (FrozenOrbReentry(), VwapReclaim(), IntradayMomentum(), LiquidMeanReversion())
    return {family.name: family for family in ordered}


def _refuse_fitted(params: Mapping[str, object]) -> None:
    if params.get("fitted"):
        raise ReplayRefusal("replay families do not fit parameters on the sample")


def _ordered(days: Sequence[SymbolDay]) -> tuple[SymbolDay, ...]:
    return tuple(sorted(days, key=lambda day: (day.session, day.symbol)))


def _scan(days, family: str, constitution, setups_for) -> GenerateResult:
    trades: list[ReplayTrade] = []
    skips: list[Skip] = []
    for day in _ordered(days):
        prior: str | None = None
        blocked_box = _Box(-1)
        sequence = 0
        for setup in setups_for(day, constitution, blocked_box):
            if sequence >= RESEARCH_MAX_ENTRIES_PER_SYMBOL:
                break
            if setup.signal_minute <= blocked_box.value:
                continue
            walked = walk_bracket(
                day.bars,
                direction=setup.direction,
                signal_minute=setup.signal_minute,
                decision_close=setup.decision_close,
                stop=setup.stop,
                target_price=setup.target_price,
                deadline_minute=constitution.session_deadline_minute,
                hard_flat_minute=constitution.hard_flat_minute,
                notional_cap=notional_cap(),
            )
            if walked is None:
                continue
            if walked.skipped_reason:
                skips.append(Skip(
                    day.session, day.symbol, walked.skipped_reason, setup.signal_minute,
                ))
                continue
            trade = ReplayTrade(
                trade_id=f"{family}:{day.session}:{day.symbol}:{sequence}",
                session=day.session,
                symbol=day.symbol,
                family=family,
                direction=setup.direction,
                signal_minute=setup.signal_minute,
                entry_minute=walked.entry_minute,
                exit_minute=walked.exit_minute,
                decision_close=setup.decision_close,
                entry=walked.entry,
                exit=walked.exit,
                gross=walked.gross,
                cost=walked.cost,
                net=walked.net,
                reason=walked.reason,
                gapped_through_stop=walked.gapped_through_stop,
                prior_id=prior,
                shares=QUANTITY,
            )
            trades.append(trade)
            prior = trade.trade_id
            blocked_box.value = trade.exit_minute
            sequence += 1
    return GenerateResult(tuple(trades), tuple(skips))


class _Box:
    """Mutable minute cursor shared with a setup generator."""

    def __init__(self, value: int) -> None:
        self.value = value


def _vwap_setups(day: SymbolDay, constitution, blocked: _Box):
    ordered = sorted(day.bars, key=lambda bar: bar.minute)
    lost: str | None = None
    extreme: float | None = None
    stretch = VWAP_LOST_ATR * day.atr14
    for bar in ordered:
        if bar.minute < constitution.opening_minutes or bar.minute <= blocked.value:
            continue
        if bar.minute >= constitution.session_deadline_minute:
            break
        vwap = session_vwap([item for item in ordered if 0 <= item.minute <= bar.minute])
        if vwap is None:
            continue
        if lost is None:
            if bar.close <= vwap - stretch:
                lost, extreme = "LONG", bar.low
            elif bar.close >= vwap + stretch:
                lost, extreme = "SHORT", bar.high
            continue
        if lost == "LONG":
            extreme = bar.low if extreme is None else min(extreme, bar.low)
            reclaimed = bar.close >= vwap
        else:
            extreme = bar.high if extreme is None else max(extreme, bar.high)
            reclaimed = bar.close <= vwap
        if not reclaimed or extreme is None:
            continue
        direction = lost
        stop = extreme
        lost = None
        extreme = None
        yield _Setup(direction, bar.minute, bar.close, stop, None)


def _momentum_setups(day: SymbolDay, constitution, blocked: _Box):
    try:
        opening = freeze_opening_range(day.bars, constitution)
    except ValueError:
        return
    ordered = sorted(day.bars, key=lambda bar: bar.minute)
    for bar in ordered:
        if bar.minute < constitution.opening_minutes or bar.minute <= blocked.value:
            continue
        if bar.minute >= constitution.session_deadline_minute:
            break
        window = [
            item for item in ordered
            if bar.minute - MOMENTUM_LOOKBACK <= item.minute < bar.minute
        ]
        if len(window) != MOMENTUM_LOOKBACK:
            continue
        if bar.close > opening.high and bar.close > max(item.high for item in window):
            yield _Setup("LONG", bar.minute, bar.close, bar.close - day.atr14, None)
        elif bar.close < opening.low and bar.close < min(item.low for item in window):
            yield _Setup("SHORT", bar.minute, bar.close, bar.close + day.atr14, None)


def _reversion_setups(day: SymbolDay, constitution, blocked: _Box):
    ordered = sorted(day.bars, key=lambda bar: bar.minute)
    armed = True
    stretch = MEAN_REVERSION_STRETCH_ATR * day.atr14
    for bar in ordered:
        if bar.minute < constitution.opening_minutes or bar.minute <= blocked.value:
            continue
        if bar.minute >= constitution.session_deadline_minute:
            break
        if bar.close < constitution.price_min:
            continue
        vwap = session_vwap([item for item in ordered if 0 <= item.minute <= bar.minute])
        if vwap is None:
            continue
        if not armed:
            if abs(bar.close - vwap) < day.atr14:
                armed = True
            continue
        if bar.close <= vwap - stretch:
            armed = False
            yield _Setup("LONG", bar.minute, bar.close, bar.close - day.atr14, vwap)
        elif bar.close >= vwap + stretch:
            armed = False
            yield _Setup("SHORT", bar.minute, bar.close, bar.close + day.atr14, vwap)


def _orb_trade(day, episode, trade_id: str, prior_id: str | None, constitution):
    result = episode.result
    frame = result.position.risk_frame
    by_minute = {bar.minute: bar for bar in day.bars}
    signal_bar = by_minute.get(episode.signal_minute)
    if signal_bar is None:
        return None, Skip(day.session, day.symbol, "MISSING_SIGNAL_BAR", episode.signal_minute, trade_id)
    if not result.position.fills:
        return None, Skip(day.session, day.symbol, "NO_FILL", episode.signal_minute, trade_id)
    entry_slipped = result.entry_price
    if frame.risk_per_share > MAX_STOP_RISK or entry_slipped > notional_cap():
        reason = "STOP_CAP" if frame.risk_per_share > MAX_STOP_RISK else "NOTIONAL_CAP"
        return None, Skip(day.session, day.symbol, reason, episode.signal_minute, trade_id)
    exit_legs = tuple(
        (frame.price_at_r(fill["exit_r"]), float(fill["fraction"]))
        for fill in result.position.fills
    )
    raw_entry = unslip(
        entry_slipped, episode.direction, is_entry=True,
        slippage_bps=constitution.slippage_bps,
        commission_per_share=constitution.commission_per_share,
    )
    raw_exits = tuple(
        (unslip(
            slipped, episode.direction, is_entry=False,
            slippage_bps=constitution.slippage_bps,
            commission_per_share=constitution.commission_per_share,
        ), fraction)
        for slipped, fraction in exit_legs
    )
    side = 1.0 if episode.direction == "LONG" else -1.0
    gross = sum((price - raw_entry) * side * fraction * QUANTITY for price, fraction in raw_exits)
    cost = scenario_cost_legs(
        entry=raw_entry, exits=raw_exits, decision_price=signal_bar.close, shares=QUANTITY,
    )
    exit_minute = result.entry_minute + result.bars_held
    exit_bar = by_minute.get(exit_minute)
    gapped = False
    if result.exit_reason == "STOP" and exit_bar is not None:
        gapped = (exit_bar.open - frame.stop_price) * side <= 0
    trade = ReplayTrade(
        trade_id=trade_id,
        session=day.session,
        symbol=day.symbol,
        family=FrozenOrbReentry.name,
        direction=episode.direction,
        signal_minute=episode.signal_minute,
        entry_minute=result.entry_minute,
        exit_minute=exit_minute,
        decision_close=signal_bar.close,
        entry=raw_entry,
        exit=raw_exits[-1][0],
        gross=gross,
        cost=cost,
        net=gross - cost,
        reason=result.exit_reason,
        gapped_through_stop=gapped,
        prior_id=prior_id,
        shares=QUANTITY,
    )
    return trade, None
