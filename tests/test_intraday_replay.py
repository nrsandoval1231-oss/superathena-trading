"""Offline intraday replay. No broker, no network, no order."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from athena_trading.backtesting.intraday_replay.bars import load_bars
from athena_trading.backtesting.intraday_replay.constants import (
    NO_EDGE,
    OPERATOR_REPORTED_EQUITY,
    PINNED_CONSTITUTION_HASH,
    REPLAY_ORDER,
)
from athena_trading.backtesting.intraday_replay.constitution_guard import require_constitution
from athena_trading.backtesting.intraday_replay.costs import scenario_cost, scenario_cost_legs
from athena_trading.backtesting.intraday_replay.families import families
from athena_trading.backtesting.intraday_replay.fills import apply_book, walk_bracket
from athena_trading.backtesting.intraday_replay.harness import _out_of_sample, run_replay, run_replay_order
from athena_trading.backtesting.intraday_replay.pass_line import evaluate_pass_line
from athena_trading.backtesting.intraday_replay.types import (
    ConstitutionDrift,
    GenerateResult,
    HoldoutRefusal,
    ReplayRefusal,
    ReplayTrade,
)
from athena_trading.orb_m.constitution import Constitution
from athena_trading.orb_m.execution import fill_price
from athena_trading.orb_m.market import Bar

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "evaluation/backtesting/fixtures/intraday_replay_sample.json"
HARNESS = ROOT / "evaluation/backtesting/backtesting/intraday_replay"
SCRIPT = ROOT / "scripts/run_intraday_replay.py"
BANNED_PARTS = {
    "alpaca", "urllib", "socket", "http", "requests", "aiohttp", "httpx",
    "websocket", "urllib3", "broker_adapters",
}
BANNED_MODULES = {
    "athena_trading.execution",
    "athena_trading.broker_adapters",
    "athena_trading.broker_adapters.alpaca",
    "athena_trading.paper.alpaca",
    "athena_trading.paper.live",
    "athena_trading.intraday",
    "athena_trading.intraday.live",
    "athena_trading.intraday.cloud",
}
BANNED_TEXT = (
    "AlpacaPaperBroker", "urlopen", "OrderIntent", "paper-api.alpaca",
    "athena_trading.execution", "athena_trading.broker_adapters",
    "athena_trading.paper.live", "FAVORABLE_FIRST",
)


def _bar(minute: int, open_: float, high: float, low: float, close: float, volume: float = 10_000.0):
    base = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
    return Bar(base + timedelta(minutes=minute), minute, open_, high, low, close, volume)


def _trade(session: str, net: float, *, minute: int = 20, symbol: str = "AAA",
           index: int = 0, prior: str | None = None, entry_minute: int | None = None,
           exit_minute: int | None = None) -> ReplayTrade:
    entry_at = minute if entry_minute is None else entry_minute
    exit_at = minute + 1 if exit_minute is None else exit_minute
    return ReplayTrade(
        trade_id=f"{session}-{symbol}-{index}",
        session=session, symbol=symbol, family="vwap_reclaim", direction="LONG",
        signal_minute=entry_at - 1, entry_minute=entry_at, exit_minute=exit_at,
        decision_close=50.0, entry=50.0, exit=50.0, gross=net, cost=0.0, net=net,
        reason="TARGET", gapped_through_stop=False, prior_id=prior,
    )


def _sessions(count: int) -> list[str]:
    start = date(2024, 1, 2)
    return [(start + timedelta(days=offset)).isoformat() for offset in range(count)]


def _score(trades, sessions, *, halted=(), provenance="POINT_IN_TIME"):
    return evaluate_pass_line(
        trades, sessions=sessions, halted_sessions=set(halted), provenance=provenance,
        constitution_hash=Constitution().identity_hash,
    )


def test_harness_modules_import_no_broker_or_network_code():
    offenders = []
    paths = list(HARNESS.rglob("*.py")) + [SCRIPT]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for token in BANNED_TEXT:
            if token in text:
                offenders.append(f"{path.name}:{token}")
        tree = ast.parse(text)
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
            for name in modules:
                parts = set(name.split("."))
                if name in BANNED_MODULES or parts & BANNED_PARTS:
                    offenders.append(f"{path.name}:{name}")
    assert offenders == []


def test_importing_the_harness_does_not_load_a_broker_module():
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    probe = (
        "import sys\n"
        "import athena_trading.backtesting.intraday_replay.harness\n"
        "banned = [name for name in sys.modules if 'alpaca' in name.lower() "
        "or name == 'socket' or name.startswith('urllib.request') "
        "or name.startswith('urllib.error') or name.startswith('http.client') "
        "or name.startswith('requests') or 'broker_adapters' in name]\n"
        "sys.stderr.write('\\n'.join(banned))\n"
        "raise SystemExit(1 if banned else 0)\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe], check=False, capture_output=True, text=True, env=env,
    )
    assert completed.returncode == 0, completed.stderr


def test_live_runner_does_not_reference_the_harness():
    roots = [
        ROOT / "strategies/custom/predictive-intraday",
        ROOT / "operations/paper-trading",
        ROOT / "core",
        ROOT / "scripts/run_athena_paper.py",
        ROOT / "scripts/run_orb_m_paper.py",
    ]
    hits = []
    for root in roots:
        paths = [root] if root.is_file() else list(root.rglob("*.py"))
        for path in paths:
            if "intraday_replay" in path.read_text(encoding="utf-8"):
                hits.append(str(path.relative_to(ROOT)))
    assert hits == []


def test_pinned_constitution_matches_the_live_object_and_a_mismatch_is_refused():
    live = require_constitution()
    assert live.identity_hash == PINNED_CONSTITUTION_HASH
    assert live.max_initial_attempts_per_direction == 1
    assert live.max_reentries_per_direction == 1
    assert live.intrabar_resolution == "ADVERSE_FIRST"
    with pytest.raises(ConstitutionDrift):
        require_constitution("0" * 64)


def test_replay_order_is_the_delegated_sequence():
    assert REPLAY_ORDER == (
        "frozen_orb_reentry", "vwap_reclaim", "intraday_momentum", "mean_reversion",
    )
    assert tuple(families()) == REPLAY_ORDER


def test_scenario_charges_slippage_floor_spread_and_regulatory_cent():
    # $100 entry, $102 exit, $101 decision. 2 bps is above the one-cent floor.
    cost = scenario_cost(entry=100.0, exit_price=102.0, decision_price=101.0)
    assert cost == pytest.approx(0.02 + 0.0204 + 0.0505 + 0.02)
    # $10 prices: 2 bps is $0.002, so the floor binds on each side.
    cheap = scenario_cost(entry=10.0, exit_price=10.0, decision_price=10.0)
    assert cheap == pytest.approx(0.01 + 0.01 + 0.01 + 0.02)


def test_orb_haircut_is_not_charged_twice():
    constitution = Constitution()
    raw_entry, raw_exit, decision = 100.0, 102.0, 101.0
    slipped_entry = fill_price(raw_entry, "LONG", is_entry=True, constitution=constitution)
    slipped_exit = fill_price(raw_exit, "LONG", is_entry=False, constitution=constitution)
    from athena_trading.backtesting.intraday_replay.costs import constitution_scenario_extra

    extra = constitution_scenario_extra(
        direction="LONG", slipped_entry=slipped_entry, exit_legs=((slipped_exit, 1.0),),
        decision_price=decision, slippage_bps=constitution.slippage_bps,
        commission_per_share=constitution.commission_per_share,
    )
    simulator = slipped_exit - slipped_entry
    raw_gross = raw_exit - raw_entry
    full = scenario_cost(entry=raw_entry, exit_price=raw_exit, decision_price=decision)
    assert simulator - extra == pytest.approx(raw_gross - full)
    legs = scenario_cost_legs(
        entry=raw_entry, exits=((raw_exit, 0.25), (raw_exit, 0.75)), decision_price=decision,
    )
    assert legs == pytest.approx(full)


def test_fill_is_the_next_open_and_a_dual_touch_stops_out():
    bars = [
        _bar(16, 100.0, 100.2, 99.9, 100.1),
        _bar(17, 100.0, 104.0, 98.0, 99.0),
    ]
    # Stop 99 and 2R target 102 are both inside bar 17. Adverse resolution stops.
    result = walk_bracket(
        bars, direction="LONG", signal_minute=15, decision_close=101.0, stop=99.0,
        target_price=None, deadline_minute=375, hard_flat_minute=389, notional_cap=989.0,
    )
    assert result is not None and result.skipped_reason is None
    assert result.entry == pytest.approx(100.0)
    assert result.entry != 101.0
    assert result.reason == "STOP"
    assert result.exit == pytest.approx(99.0)
    assert result.gapped_through_stop is False


def test_a_gap_through_the_stop_fills_at_the_open():
    bars = [
        _bar(16, 100.0, 100.2, 99.8, 100.0),
        _bar(17, 98.0, 98.5, 97.0, 97.5),
    ]
    result = walk_bracket(
        bars, direction="LONG", signal_minute=15, decision_close=100.5, stop=99.0,
        target_price=None, deadline_minute=375, hard_flat_minute=389, notional_cap=989.0,
    )
    assert result is not None
    assert result.reason == "GAP_THROUGH_STOP"
    assert result.exit == pytest.approx(98.0)
    assert result.gross == pytest.approx(-2.0)


def test_target_multiple_stays_at_two_and_quantity_stays_at_one():
    with pytest.raises(ValueError):
        walk_bracket(
            [_bar(16, 100.0, 100.2, 99.8, 100.0)], direction="LONG", signal_minute=15,
            decision_close=100.5, stop=99.0, target_price=None, target_r=3.0,
            deadline_minute=375, hard_flat_minute=389, notional_cap=989.0,
        )
    with pytest.raises(ValueError):
        _trade("2024-01-02", 1.0).__class__(
            **{**_trade("2024-01-02", 1.0).__dict__, "shares": 2},
        )


def test_daily_loss_halt_trips_at_the_approved_fraction_and_releases_the_next_session():
    sessions = ["2024-01-02", "2024-01-03"]
    losing = _trade(sessions[0], -5.0, index=0, entry_minute=20, exit_minute=21)
    later = _trade(sessions[0], 1.0, index=1, entry_minute=22, exit_minute=23, prior=None)
    nxt = _trade(sessions[1], 1.0, index=2, entry_minute=20, exit_minute=21)
    book = apply_book((losing, later, nxt), equity=1_000.0)
    assert sessions[0] in book.halted_sessions
    assert sessions[1] not in book.halted_sessions
    assert [trade.trade_id for trade in book.trades] == [losing.trade_id, nxt.trade_id]
    assert any(skip.reason == "HALTED" for skip in book.skips)
    inside = apply_book((_trade(sessions[0], -4.99),), equity=1_000.0)
    assert inside.halted_sessions == frozenset()


def test_one_position_blocks_an_overlap_and_its_dependent_trade():
    first = _trade("2024-01-02", 1.0, symbol="AAA", index=0, entry_minute=10, exit_minute=20)
    overlap = _trade("2024-01-02", 1.0, symbol="BBB", index=1, entry_minute=12, exit_minute=18)
    child = _trade(
        "2024-01-02", 1.0, symbol="BBB", index=2, entry_minute=21, exit_minute=30,
        prior=overlap.trade_id,
    )
    book = apply_book((first, overlap, child))
    assert [trade.trade_id for trade in book.trades] == [first.trade_id]
    reasons = {skip.trade_id: skip.reason for skip in book.skips}
    assert reasons[overlap.trade_id] == "NOT_FLAT"
    assert reasons[child.trade_id] == "PRIOR_NOT_TAKEN"


def test_positive_expectancy_with_a_negative_session_lower_bound_fails():
    sessions = _sessions(60)
    trades = []
    for index, session in enumerate(sessions):
        net = -40.0 if index == len(sessions) - 1 else 1.0
        trades.append(_trade(session, net, index=0, minute=20))
        trades.append(_trade(session, net, index=1, minute=30))
    scored = _score(trades, sessions)
    assert scored["metrics"]["cost_adjusted_expectancy_per_trade"] > 0
    assert scored["metrics"]["session_lower_bound"] < 0
    assert scored["checks"]["session_lower_bound_positive"] is False
    assert scored["numeric_pass"] is False
    assert scored["gate_passed"] is False
    assert scored["no_edge_claimed"] == NO_EDGE
    assert scored["market_evidence"] is False


def test_a_uniform_sample_can_pass_the_numeric_gate_without_claiming_an_edge():
    sessions = _sessions(60)
    trades = [
        _trade(session, 1.0, index=index, minute=20 + index)
        for session in sessions for index in range(2)
    ]
    scored = _score(trades, sessions)
    assert scored["numeric_pass"] is True
    assert scored["gate_passed"] is True
    assert scored["market_evidence"] is False
    assert scored["no_edge_claimed"] == NO_EDGE
    fixture = _score(trades, sessions, provenance="FIXTURE")
    assert fixture["numeric_pass"] is True
    assert fixture["gate_passed"] is False


def test_three_of_five_folds_halt_rate_drawdown_and_sample_size_fail_closed():
    sessions = _sessions(60)
    trades = []
    for index, session in enumerate(sessions):
        # Folds are 12 sessions each. Folds 2 and 3 are the middle 24 sessions.
        net = -0.01 if 24 <= index < 48 else 1.0
        trades.append(_trade(session, net, index=0))
        trades.append(_trade(session, net, index=1, minute=30))
    scored = _score(trades, sessions)
    assert scored["metrics"]["positive_folds"] == 3
    assert scored["checks"]["positive_folds"] is False
    halted = _score(trades, sessions, halted=sessions[:4])
    assert halted["checks"]["halt_rate"] is False
    at_the_line = _score(trades, sessions, halted=sessions[:3])
    assert at_the_line["checks"]["halt_rate"] is True
    deep = [_trade(sessions[0], -3_000.0, index=0)]
    deep.extend(_trade(session, 1.0, index=1) for session in sessions[1:])
    drawdown = _score(deep, sessions)
    assert drawdown["metrics"]["cost_adjusted_drawdown"] > 0.025 * OPERATOR_REPORTED_EQUITY
    assert drawdown["checks"]["drawdown"] is False
    short = _score(
        [_trade(session, 1.0) for session in sessions], sessions,
    )
    assert short["checks"]["oos_trades"] is False
    earlier = [trade for trade in trades if trade.session in set(sessions[:59])]
    assert _score(earlier, sessions[:59])["checks"]["oos_sessions"] is False
    drifted = evaluate_pass_line(
        trades, sessions=sessions, halted_sessions=set(), provenance="POINT_IN_TIME",
        constitution_hash="f" * 64,
    )
    assert drifted["checks"]["constitution_hash"] is False


def test_fit_receives_only_earlier_folds():
    class Spy:
        def __init__(self):
            self.seen: list[list[str]] = []

        def fit(self, training):
            self.seen.append(sorted({day.session for day in training}))
            return {"fitted": False}

        def generate(self, days, params):
            del days, params
            return GenerateResult((), ())

    sessions = _sessions(5)
    days = []
    from athena_trading.backtesting.intraday_replay.bars import SymbolDay
    for session in sessions:
        days.append(SymbolDay(session, "AAA", 1.0, (_bar(0, 50, 50.2, 49.8, 50),)))
    spy = Spy()
    _out_of_sample(spy, days)
    assert len(spy.seen) == 5
    for fold, training in enumerate(spy.seen):
        assert sessions[fold] not in training
        assert set(training) <= set(sessions[:fold])


def test_sample_fixture_replays_orb_without_passing_the_gate_or_using_the_close(tmp_path):
    report = run_replay(SAMPLE, family="frozen_orb_reentry", out=tmp_path / "orb.json")
    assert report["authority"] == "ABSENT"
    assert report["orders_submitted"] == 0
    assert report["broker_client"] is False
    assert report["capped_marketable_limit"] == "absent"
    assert report["holdouts"] == "not read"
    assert report["no_edge_claimed"] == NO_EDGE
    assert report["gate_passed"] is False
    assert report["fixture_is_not_market_evidence"] is True
    assert report["constitution_identity_hash"] == PINNED_CONSTITUTION_HASH
    assert report["trades"]
    assert all(trade["shares"] == 1 for trade in report["trades"])
    assert all(trade["decision_close_used_as_fill"] is False for trade in report["trades"])
    assert all(trade["entry_minute"] > trade["signal_minute"] for trade in report["trades"])
    first = report["trades"][0]
    assert first["entry"] == pytest.approx(50.4)
    assert first["decision_close"] == pytest.approx(50.5)
    stored = json.loads((tmp_path / "orb.json").read_text(encoding="utf-8"))
    assert stored["family"] == "frozen_orb_reentry"


def test_replay_order_writes_one_report_per_family(tmp_path):
    reports = run_replay_order(SAMPLE, out_dir=tmp_path)
    assert [report["family"] for report in reports] == list(REPLAY_ORDER)
    paths = sorted(path.name for path in tmp_path.glob("*.json"))
    assert paths == [
        "01-frozen_orb_reentry.json",
        "02-vwap_reclaim.json",
        "03-intraday_momentum.json",
        "04-mean_reversion.json",
    ]
    assert all(report["market_evidence"] is False for report in reports)


def test_holdout_paths_and_remote_paths_are_refused(tmp_path):
    payload = SAMPLE.read_text(encoding="utf-8")
    holdout = tmp_path / "holdout" / "bars.json"
    holdout.parent.mkdir()
    holdout.write_text(payload, encoding="utf-8")
    with pytest.raises(HoldoutRefusal):
        load_bars(holdout)
    marked = tmp_path / "INVALID_EVIDENCE.json"
    marked.write_text(payload, encoding="utf-8")
    with pytest.raises(HoldoutRefusal):
        load_bars(marked)
    with pytest.raises(ReplayRefusal):
        load_bars(Path("https://example.com/bars.json"))


def test_current_snapshot_is_labeled_and_vwap_momentum_and_reversion_emit(tmp_path):
    payload = json.loads(SAMPLE.read_text(encoding="utf-8"))
    payload["provenance"] = "CURRENT_SNAPSHOT"
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    report = run_replay(path, family="frozen_orb_reentry")
    assert report["carries_survivorship_bias"] is True
    assert report["gate_passed"] is False

    vwap_day = _stretch_day("2024-02-01", kind="vwap")
    momentum_day = _stretch_day("2024-02-02", kind="momentum")
    fade_day = _stretch_day("2024-02-03", kind="fade")
    catalog = families()
    params = {"fitted": False}
    vwap = catalog["vwap_reclaim"].generate((vwap_day,), params)
    momentum = catalog["intraday_momentum"].generate((momentum_day,), params)
    fade = catalog["mean_reversion"].generate((fade_day,), params)
    assert vwap.trades and vwap.trades[0].direction == "LONG"
    assert vwap.trades[0].entry != vwap.trades[0].decision_close
    assert momentum.trades and momentum.trades[0].direction == "LONG"
    assert fade.trades and fade.trades[0].direction == "LONG"
    assert fade.trades[0].reason == "STOP"


def _stretch_day(session: str, *, kind: str):
    from athena_trading.backtesting.intraday_replay.bars import SymbolDay

    rows = []
    for minute in range(15):
        rows.append(_session_bar(session, minute, 100.0, 100.05, 99.95, 100.0))
    if kind == "vwap":
        rows.append(_session_bar(session, 15, 99.0, 99.2, 98.0, 98.5))
        rows.append(_session_bar(session, 16, 99.8, 100.4, 99.7, 100.2))
        rows.append(_session_bar(session, 17, 100.3, 100.5, 100.1, 100.4))
        rows.append(_session_bar(session, 18, 100.4, 106.0, 100.2, 105.0))
        atr = 1.0
    elif kind == "momentum":
        price = 100.0
        for minute in range(15, 40):
            price += 0.05
            rows.append(_session_bar(session, minute, price, price + 0.2, price - 0.05, price + 0.15))
        rows.append(_session_bar(session, 40, price, price + 0.3, price - 0.05, price + 0.25))
        rows.append(_session_bar(session, 41, price + 0.3, price + 2.0, price + 0.2, price + 1.5))
        atr = 0.4
    else:
        for minute in range(15, 20):
            rows.append(_session_bar(session, minute, 100.0, 100.05, 99.95, 100.0, volume=100_000))
        rows.append(_session_bar(session, 20, 98.2, 98.3, 97.6, 98.0, volume=1_000))
        rows.append(_session_bar(session, 21, 98.1, 101.0, 96.0, 97.0, volume=1_000))
        atr = 1.0
    return SymbolDay(session, "AAA", atr, tuple(rows))


def _session_bar(session, minute, open_, high, low, close, volume=10_000.0):
    event = datetime.combine(
        date.fromisoformat(session), datetime.strptime("09:30", "%H:%M").time(),
        tzinfo=ZoneInfo("America/New_York"),
    ) + timedelta(minutes=minute)
    return Bar(event, minute, open_, high, low, close, volume)


def test_script_writes_a_report_and_rejects_live(tmp_path):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    out = tmp_path / "report.json"
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--bars", str(SAMPLE), "--family", "frozen_orb_reentry",
         "--out", str(out)],
        check=False, capture_output=True, text=True, env=env,
    )
    assert completed.returncode == 0, completed.stderr
    assert NO_EDGE in completed.stdout
    assert json.loads(out.read_text(encoding="utf-8"))["orders_submitted"] == 0
    refused = subprocess.run(
        [sys.executable, str(SCRIPT), "--bars", str(SAMPLE), "--family", "frozen_orb_reentry",
         "LIVE"],
        check=False, capture_output=True, text=True, env=env,
    )
    assert refused.returncode == 2
