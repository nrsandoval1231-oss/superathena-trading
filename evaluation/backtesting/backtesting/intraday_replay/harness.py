"""Run one family, or the four families in delegated order, from local bars."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path

from athena_trading.orb_m.constitution import ManagementParameters

from .bars import BarFile, SymbolDay, load_bars
from .constants import (
    AUTHORITY,
    EQUITY_SOURCE,
    FILL_ASSUMPTION,
    FOLD_COUNT,
    HOLDOUTS,
    MEAN_REVERSION_STRETCH_ATR,
    MOMENTUM_LOOKBACK,
    NO_EDGE,
    OPERATOR_REPORTED_EQUITY,
    PAPER_FILL_LIMITATION,
    PERFORMANCE,
    QUANTITY,
    REPLAY_ORDER,
    RESEARCH_MAX_ENTRIES_PER_SYMBOL,
    SCENARIO_ID,
    TARGET_R,
    VWAP_LOST_ATR,
)
from .constitution_guard import require_constitution
from .families import families
from .fills import apply_book
from .pass_line import chronological_folds, evaluate_pass_line
from .types import GenerateResult, ReplayRefusal, ReplayTrade, Skip


def run_replay(
    path: Path,
    *,
    family: str,
    out: Path | None = None,
    expected_constitution: str | None = None,
) -> dict[str, object]:
    """Replay one family. Authority stays ABSENT and no order is built."""
    catalog = families()
    if family not in catalog:
        raise ReplayRefusal(f"unknown family {family!r}; replay order is {list(REPLAY_ORDER)}")
    loaded = load_bars(Path(path))
    _refuse_duplicate_days(loaded.days)
    constitution = require_constitution(expected_constitution)
    produced, fit_log = _out_of_sample(catalog[family], loaded.days)
    book = apply_book(produced.trades)
    sessions = sorted({day.session for day in loaded.days})
    scored = evaluate_pass_line(
        book.trades,
        sessions=sessions,
        halted_sessions=book.halted_sessions,
        provenance=loaded.provenance,
        constitution_hash=constitution.identity_hash,
    )
    report = _report(
        loaded, family, constitution.identity_hash, produced, book.trades,
        book.skips, book.halted_sessions, book.ending_equity, fit_log, scored,
    )
    if out is not None:
        _write(report, Path(out))
    return report


def run_replay_order(path: Path, *, out_dir: Path) -> list[dict[str, object]]:
    """Write one report per family, in replay order, each before the next starts."""
    destination = Path(out_dir)
    destination.mkdir(parents=True, exist_ok=True)
    reports: list[dict[str, object]] = []
    previous: str | None = None
    for index, name in enumerate(REPLAY_ORDER, start=1):
        target = destination / f"{index:02d}-{name}.json"
        report = run_replay(path, family=name)
        report["previous_report"] = previous
        report["order_index"] = index
        _write(report, target)
        previous = str(target)
        reports.append(report)
    return reports


def _out_of_sample(family, days: Sequence[SymbolDay]) -> tuple[GenerateResult, list[dict[str, object]]]:
    sessions = sorted({day.session for day in days})
    by_session: dict[str, list[SymbolDay]] = defaultdict(list)
    for day in days:
        by_session[day.session].append(day)
    try:
        assignment = chronological_folds(sessions)
    except ValueError:
        produced = family.generate(tuple(days), {"fitted": False})
        note = {
            "fold": None,
            "training_sessions": [],
            "test_sessions": sessions,
            "note": "fewer than 5 sessions; walk-forward cannot pass",
        }
        return produced, [note]
    trades: list[ReplayTrade] = []
    skips: list[Skip] = []
    log: list[dict[str, object]] = []
    for fold in range(FOLD_COUNT):
        training = [
            day for session, fold_id in assignment.items() if fold_id < fold
            for day in by_session[session]
        ]
        test = [
            day for session, fold_id in assignment.items() if fold_id == fold
            for day in by_session[session]
        ]
        params = family.fit(tuple(training))
        if params.get("fitted"):
            raise ReplayRefusal("replay families do not fit parameters on the sample")
        log.append({
            "fold": fold,
            "training_sessions": sorted({day.session for day in training}),
            "test_sessions": sorted({day.session for day in test}),
        })
        produced = family.generate(tuple(test), params)
        trades.extend(produced.trades)
        skips.extend(produced.skips)
    return GenerateResult(tuple(trades), tuple(skips)), log


def _report(
    loaded: BarFile,
    family: str,
    constitution_hash: str,
    produced: GenerateResult,
    taken: Sequence[ReplayTrade],
    book_skips: Sequence[Skip],
    halted_sessions: frozenset[str],
    ending_equity: float,
    fit_log: list[dict[str, object]],
    scored: dict[str, object],
) -> dict[str, object]:
    skips = tuple(produced.skips) + tuple(book_skips)
    return {
        "authority": AUTHORITY,
        "orders_submitted": 0,
        "broker_client": False,
        "family": family,
        "replay_order": list(REPLAY_ORDER),
        "performance": PERFORMANCE,
        "holdouts": HOLDOUTS,
        "no_edge_claimed": NO_EDGE,
        "paper_fill_limitation": PAPER_FILL_LIMITATION,
        "fill_assumption": FILL_ASSUMPTION,
        "capped_marketable_limit": "absent",
        "cost_scenario": SCENARIO_ID,
        "cost_scenario_is_measured": False,
        "replay_equity": OPERATOR_REPORTED_EQUITY,
        "replay_equity_source": EQUITY_SOURCE,
        "measured_buying_power": None,
        "constitution_identity_hash": constitution_hash,
        "management_parameters": "ManagementParameters defaults; not evolved",
        "management_identity_hash": ManagementParameters().identity_hash,
        "target_r": TARGET_R,
        "quantity": QUANTITY,
        "provenance": loaded.provenance,
        "carries_survivorship_bias": loaded.provenance == "CURRENT_SNAPSHOT",
        "fixture_is_not_market_evidence": loaded.provenance == "FIXTURE",
        "universe_members": list(loaded.universe_members) if loaded.universe_members else None,
        "source": loaded.source,
        "parameters_fitted": False,
        "research_assumptions": {
            "approved": False,
            "fitted": False,
            "vwap_lost_atr": VWAP_LOST_ATR,
            "momentum_lookback": MOMENTUM_LOOKBACK,
            "mean_reversion_stretch_atr": MEAN_REVERSION_STRETCH_ATR,
            "max_entries_per_symbol_for_new_families": RESEARCH_MAX_ENTRIES_PER_SYMBOL,
            "note": (
                "Written before outcomes so the replay can run. "
                "Not an approved risk limit and not a fitted threshold."
            ),
        },
        "needs_nick": [
            "target_r stays 2; changing the intraday multiple is NEEDS NICK",
            "concentration_limit is inactive and NEEDS NICK before it does anything",
        ],
        "numeric_pass": scored["numeric_pass"],
        "gate_passed": scored["gate_passed"],
        "market_evidence": False,
        "checks": scored["checks"],
        "metrics": scored["metrics"],
        "fit_log": fit_log,
        "skip_counts": dict(sorted(Counter(skip.reason for skip in skips).items())),
        "halted_sessions": sorted(halted_sessions),
        "ending_equity": ending_equity,
        "trades": [_trade_row(trade) for trade in taken],
    }


def _trade_row(trade: ReplayTrade) -> dict[str, object]:
    return {
        "trade_id": trade.trade_id,
        "session": trade.session,
        "symbol": trade.symbol,
        "family": trade.family,
        "direction": trade.direction,
        "signal_minute": trade.signal_minute,
        "entry_minute": trade.entry_minute,
        "exit_minute": trade.exit_minute,
        "decision_close": trade.decision_close,
        "entry": trade.entry,
        "exit": trade.exit,
        "gross": trade.gross,
        "cost": trade.cost,
        "net": trade.net,
        "reason": trade.reason,
        "gapped_through_stop": trade.gapped_through_stop,
        "prior_id": trade.prior_id,
        "shares": trade.shares,
        "decision_close_used_as_fill": False,
    }


def _refuse_duplicate_days(days: Sequence[SymbolDay]) -> None:
    seen: set[tuple[str, str]] = set()
    for day in days:
        key = (day.session, day.symbol)
        if key in seen:
            raise ReplayRefusal(f"duplicate symbol session: {day.symbol} {day.session}")
        seen.add(key)


def _write(report: dict[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
