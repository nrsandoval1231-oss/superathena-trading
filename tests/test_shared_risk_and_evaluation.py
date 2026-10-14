"""Shared account gate and fresh-evidence comparison. No broker and no holdout rerun."""
from __future__ import annotations

import os
import stat
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from athena_trading.athena_adapter.contracts import canonical_hash
from athena_trading.paper.evaluation import (
    Opportunity, adverse_excursion, chronological_drawdown, compare_policies,
    fill_from_next_bar, session_uncertainty,
)
from athena_trading.paper.funnel import record_opportunity
from athena_trading.paper.journal import PaperJournal
from athena_trading.paper.learning import LearningStore
from athena_trading.paper.shared_risk import (
    UNRESOLVED_SHARED_POLICY, OpenExposure, authorize_entry,
    exposures_from_journal, other_arm_exposure,
)


def test_shared_gate_blocks_a_second_reservation_and_lists_inactive_checks():
    open_book = [OpenExposure("earnings", "DECK", 1500.0, 40.0, True, "athe-deck")]
    same = authorize_entry(
        arm="intraday", symbol="DECK", notional=100.0, stop_risk=1.0, overnight=False,
        buying_power=100_000.0, open_exposure=open_book,
    )
    assert same.allowed is False and same.reason == "SYMBOL_ALREADY_RESERVED"
    assert same.unresolved == UNRESOLVED_SHARED_POLICY
    crowded = authorize_entry(
        arm="intraday", symbol="AAPL", notional=200.0, stop_risk=1.0, overnight=False,
        buying_power=1600.0, open_exposure=open_book,
    )
    assert crowded.reason == "BUYING_POWER"
    overnight = authorize_entry(
        arm="intraday", symbol="AAPL", notional=100.0, stop_risk=1.0, overnight=True,
        buying_power=100_000.0, open_exposure=[],
    )
    assert overnight.reason == "OVERNIGHT_NOT_AUTHORIZED"
    earnings = authorize_entry(
        arm="earnings", symbol="AAPL", notional=100.0, stop_risk=1.0, overnight=True,
        buying_power=100_000.0, open_exposure=[],
    )
    assert earnings.allowed is False
    assert earnings.reason == "OVERNIGHT_NOT_AUTHORIZED"
    assert earnings.overnight_authority == "inactive"
    daytime = authorize_entry(
        arm="earnings", symbol="AAPL", notional=100.0, stop_risk=1.0, overnight=False,
        buying_power=100_000.0, open_exposure=[],
    )
    assert daytime.allowed is True
    assert daytime.overnight_authority == "flat-by-close"
    assert "correlation_limit" in earnings.unresolved


def test_partial_fill_keeps_only_the_residual_shares(tmp_path):
    journal = PaperJournal(tmp_path / "book.sqlite")
    journal.append("entry_intent", order={
        "client_order_id": "athe-deck", "symbol": "DECK", "side": "buy", "qty": "19",
        "limit_price": "100", "stop_loss": {"stop_price": "98"},
    })
    journal.append("entry_observation", client_order_id="athe-deck", order={
        "client_order_id": "athe-deck", "symbol": "DECK", "side": "buy", "qty": "19",
        "filled_qty": "19", "legs": [
            {"side": "sell", "filled_qty": "5"},
            {"side": "sell", "filled_qty": "0"},
        ],
    })
    rows = exposures_from_journal(journal, "earnings")
    assert len(rows) == 1
    assert rows[0].notional == pytest.approx(1400.0)
    assert rows[0].stop_risk == pytest.approx(28.0)
    journal.append("position_closed", client_order_id="athe-deck")
    assert exposures_from_journal(journal, "earnings") == []
    journal.close()


def test_locked_other_journal_stays_readable(tmp_path, monkeypatch):
    """A peer can read while the owner holds the writer lock. An empty book is empty."""
    root = tmp_path / "earnings"
    monkeypatch.setenv("ATHENA_EARNINGS_STATE_DIR", str(root))
    held = PaperJournal(root / "book.sqlite")
    held.append("binding", binding={"arm": "earnings"})
    assert other_arm_exposure("intraday") == []
    held.append("entry_intent", order={
        "client_order_id": "athe-deck", "symbol": "DECK", "side": "buy", "qty": "10",
        "limit_price": "100", "stop_loss": {"stop_price": "98"},
    })
    assert other_arm_exposure("intraday")[0].notional == pytest.approx(1000.0)
    held.close()
    assert other_arm_exposure("intraday")[0].symbol == "DECK"


def test_funnel_rejects_an_unknown_stage_and_does_not_repeat(tmp_path):
    journal = PaperJournal(tmp_path / "paper.sqlite")
    now = datetime(2026, 10, 13, 14, tzinfo=UTC)
    record_opportunity(journal, stage="model_vetoed", reason="JEV_VETO", at=now, signal_at="t1")
    record_opportunity(journal, stage="model_vetoed", reason="JEV_VETO", at=now, signal_at="t1")
    assert sum(event["kind"] == "opportunity" for event in journal.events) == 1
    with pytest.raises(ValueError, match="unknown opportunity stage"):
        record_opportunity(journal, stage="guessed", reason="NO", at=now, signal_at="t1")
    journal.close()


def _item(**overrides):
    base = dict(
        opportunity_id="z-late", session="2026-01-02", symbol="DECK", at="2026-01-02T15:00:00Z",
        decision_close=100.0, next_open=101.0, next_close=103.0, stop=99.0, target=104.0,
        direction="LONG", jev_without_memory="TAKE_TRADE", jev_with_memory="NO_TRADE",
    )
    base.update(overrides)
    return Opportunity(**base)


def test_fill_uses_the_next_open_and_a_gap_through_the_stop():
    gapped = _item(
        decision_close=100.0, next_open=97.0, next_close=96.0, stop=99.0, target=104.0,
    )
    fill = fill_from_next_bar(gapped)
    assert fill["entry"] == 97.0
    assert fill["decision_close_used_as_fill"] is False
    assert fill["gapped_through_stop"] is True
    assert fill["gross"] == 0.0
    assert adverse_excursion(gapped) == pytest.approx(-3.0)


def test_drawdown_follows_time_and_sessions_stay_together():
    rows = [
        {"at": "2026-01-02T15:00:00Z", "opportunity_id": "a", "gross": 20.0},
        {"at": "2026-01-03T15:00:00Z", "opportunity_id": "m", "gross": -10.0},
        {"at": "2026-01-01T15:00:00Z", "opportunity_id": "z", "gross": -5.0},
    ]
    assert chronological_drawdown(rows) == pytest.approx(10.0)
    band = session_uncertainty(
        [("A", 10.0), ("A", 10.0), ("B", -5.0)], resamples=40, confidence=0.95, seed=3,
    )
    assert band["sessions"] == 2
    assert band["n"] == 3
    assert band["mean"] == pytest.approx(5.0)
    # A session draw is AA, BB, or one of each. An independent draw can land elsewhere.
    assert band["lower"] in {-5.0, 5.0, 10.0}


def test_comparison_keeps_three_policies_and_does_not_claim_an_edge():
    rows = [
        _item(opportunity_id="1", at="2026-01-01T15:00:00Z", session="2026-01-01",
              direction="LONG", jev_without_memory="TAKE_TRADE", jev_with_memory="TAKE_TRADE"),
        _item(opportunity_id="2", at="2026-01-02T15:00:00Z", session="2026-01-02",
              direction="SHORT", decision_close=100.0, next_open=101.0, next_close=99.0,
              stop=102.0, target=96.0, jev_without_memory="NO_TRADE", jev_with_memory="TAKE_TRADE"),
    ]
    report = compare_policies(rows, cost_per_share=0.01)
    assert set(report["policies"]) == {"deterministic", "jev_without_memory", "jev_with_memory"}
    assert report["policies"]["deterministic"]["taken"] == 2
    assert report["policies"]["jev_without_memory"]["taken"] == 1
    assert report["policies"]["jev_with_memory"]["skipped"] == []
    assert report["policies"]["deterministic"]["by_direction"]["SHORT"]["taken"] == 1
    assert report["performance"] == "unverified"
    assert report["holdouts"] == "not read"
    assert "not a calibrated" in report["jev_confidence"]
    assert report["fill_assumption"].startswith("next bar open")


def test_restart_still_sees_the_other_book_until_it_closes(tmp_path, monkeypatch):
    root = tmp_path / "earnings"
    monkeypatch.setenv("ATHENA_EARNINGS_STATE_DIR", str(root))
    book = PaperJournal(root / "book.sqlite")
    book.append("entry_intent", order={
        "client_order_id": "athe-deck", "symbol": "DECK", "side": "buy", "qty": "10",
        "limit_price": "100", "stop_loss": {"stop_price": "98"},
    })
    book.close()
    restarted = PaperJournal(root / "book.sqlite")
    assert exposures_from_journal(restarted, "earnings")[0].notional == pytest.approx(1000.0)
    restarted.close()
    seen = other_arm_exposure("intraday")
    assert [row.symbol for row in seen] == ["DECK"]
    closed = PaperJournal(root / "book.sqlite")
    closed.append("position_closed", client_order_id="athe-deck")
    closed.close()
    assert other_arm_exposure("intraday") == []


def test_outcome_ingestion_keeps_earnings_out_of_the_intraday_study(tmp_path):
    """Offline stand-in for a reconciled close. It is not a broker session."""
    source = PaperJournal(tmp_path / "2026-07-01.sqlite")
    at = datetime(2026, 7, 1, 15, tzinfo=UTC)
    source.append("binding", binding={"account_id": "paper-account", "policy": {"symbol": "AAPL"}})
    order = {
        "client_order_id": "fixture-0", "symbol": "AAPL", "side": "buy",
        "limit_price": "100", "stop_loss": {"stop_price": "98"},
    }
    receipt = {"accepted": True, "question_hash": "q"}
    source.append(
        "entry_intent", session="2026-07-01", at=at, order=order,
        verdict_hash=canonical_hash(receipt),
    )
    source.append("adjudication", receipt=receipt)
    parent = {**order, "id": "parent", "qty": "1", "filled_qty": "1",
              "filled_avg_price": "100", "status": "filled"}
    source.append("flat_confirmed", parent=parent, order_history=[
        parent,
        {"id": "exit", "symbol": "AAPL", "side": "sell", "qty": "1", "filled_qty": "1",
         "filled_avg_price": "98", "status": "filled"},
    ], snapshot={"clock": {"timestamp": "2026-07-01T16:00:00+00:00"}, "positions": [], "orders": []})
    store = LearningStore(tmp_path / "learning")
    store.ingest(source, datetime(2026, 7, 1, 17, tzinfo=UTC))
    stored = store.experiences()
    assert len(stored) == 1
    assert stored[0]["gross_pnl"] == "-2"
    assert stored[0]["result"] == "LOSS"
    assert stored[0].get("arm") is None
    source.close()
    store.journal.close()


def _entry(symbol, client_order_id, qty, price="100"):
    return {
        "client_order_id": client_order_id, "symbol": symbol, "side": "buy", "qty": qty,
        "limit_price": price, "stop_loss": {"stop_price": "98"},
    }


def _peer_env(earnings: Path, intraday: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["ATHENA_EARNINGS_STATE_DIR"] = str(earnings)
    env["ATHENA_STATE_DIR"] = str(intraday)
    env["PYTHONPATH"] = os.pathsep.join(["src", env.get("PYTHONPATH", "")])
    return env


def _lock_readonly(root: Path) -> None:
    """Match a systemd peer mount: the directory and files can be read, not written."""
    for path in root.iterdir():
        path.chmod(0o444)
    root.chmod(0o555)


def test_working_zero_fill_still_reserves_the_whole_order(tmp_path):
    """A 19-share working order with no fills still occupies all 19 shares."""
    journal = PaperJournal(tmp_path / "book.sqlite")
    journal.append("entry_intent", order=_entry("DECK", "athe-deck", "19"))
    journal.append("entry_observation", client_order_id="athe-deck", order={
        **_entry("DECK", "athe-deck", "19"), "status": "new", "filled_qty": "0", "legs": [],
    })
    rows = exposures_from_journal(journal, "earnings")
    assert len(rows) == 1
    assert rows[0].notional == pytest.approx(1900.0)
    decision = authorize_entry(
        arm="intraday", symbol="DECK", notional=100.0, stop_risk=1.0, overnight=False,
        buying_power=100_000.0, open_exposure=rows,
    )
    assert decision.reason == "SYMBOL_ALREADY_RESERVED"
    journal.append("entry_observation", client_order_id="athe-deck", order={
        **_entry("DECK", "athe-deck", "19"), "status": "canceled", "filled_qty": "0", "legs": [],
    })
    assert exposures_from_journal(journal, "earnings") == []
    journal.close()


def test_partial_fill_keeps_the_position_and_the_unfilled_remainder(tmp_path):
    journal = PaperJournal(tmp_path / "book.sqlite")
    journal.append("entry_intent", order=_entry("DECK", "athe-deck", "19"))
    journal.append("entry_observation", client_order_id="athe-deck", order={
        **_entry("DECK", "athe-deck", "19"), "status": "partially_filled", "filled_qty": "10",
        "legs": [{"side": "sell", "filled_qty": "0"}],
    })
    rows = exposures_from_journal(journal, "earnings")
    assert rows[0].notional == pytest.approx(1900.0)
    crowded = authorize_entry(
        arm="intraday", symbol="AAPL", notional=100.0, stop_risk=1.0, overnight=False,
        buying_power=1950.0, open_exposure=rows,
    )
    assert crowded.reason == "BUYING_POWER"
    journal.append("entry_observation", client_order_id="athe-deck", order={
        **_entry("DECK", "athe-deck", "19"), "status": "partially_filled", "filled_qty": "10",
        "legs": [{"side": "sell", "filled_qty": "5"}],
    })
    residual = exposures_from_journal(journal, "earnings")
    # 5 shares still held plus 9 shares still working.
    assert residual[0].notional == pytest.approx(1400.0)
    journal.close()


def test_malformed_fill_evidence_does_not_become_zero_exposure(tmp_path):
    journal = PaperJournal(tmp_path / "book.sqlite")
    journal.append("entry_intent", order=_entry("DECK", "athe-deck", "19"))
    journal.append("entry_observation", client_order_id="athe-deck", order={
        **_entry("DECK", "athe-deck", "19"), "status": "new", "filled_qty": "not-a-number",
    })
    with pytest.raises(Exception, match="malformed"):
        exposures_from_journal(journal, "earnings")
    journal.close()


def test_held_writer_lock_still_returns_a_consistent_peer_snapshot(tmp_path, monkeypatch):
    """The other runner may keep its journal open. Reading it must not take that lock."""
    root = tmp_path / "earnings"
    monkeypatch.setenv("ATHENA_EARNINGS_STATE_DIR", str(root))
    held = PaperJournal(root / "book.sqlite")
    held.append("entry_intent", order=_entry("DECK", "athe-deck", "19"))
    rows = other_arm_exposure("intraday")
    assert [row.symbol for row in rows] == ["DECK"]
    assert rows[0].notional == pytest.approx(1900.0)
    held.close()


def test_read_only_peer_directories_expose_both_books(tmp_path, monkeypatch):
    earnings = tmp_path / "earnings"
    intraday = tmp_path / "athena"
    book = PaperJournal(earnings / "book.sqlite")
    book.append("entry_intent", order=_entry("DECK", "athe-deck", "19"))
    book.close()
    day = PaperJournal(intraday / "2026-10-13.sqlite")
    day.append("entry_intent", order=_entry("AAPL", "athp-aapl", "1", "101.50"))
    day.close()
    _lock_readonly(earnings)
    _lock_readonly(intraday)
    monkeypatch.setenv("ATHENA_EARNINGS_STATE_DIR", str(earnings))
    monkeypatch.setenv("ATHENA_STATE_DIR", str(intraday))
    earnings_rows = other_arm_exposure("intraday")
    intraday_rows = other_arm_exposure("earnings", today=date(2026, 10, 13))
    assert [(row.symbol, row.notional) for row in earnings_rows] == [("DECK", pytest.approx(1900.0))]
    assert [(row.symbol, row.notional) for row in intraday_rows] == [("AAPL", pytest.approx(101.50))]
    assert stat.S_IMODE(earnings.stat().st_mode) == 0o555


def test_unreadable_peer_snapshot_fails_closed_without_rewriting_it(tmp_path, monkeypatch):
    root = tmp_path / "earnings"
    book = PaperJournal(root / "book.sqlite")
    book.append("entry_intent", order=_entry("DECK", "athe-deck", "19"))
    book.close()
    sqlite = root / "book.sqlite"
    sqlite.chmod(0)
    monkeypatch.setenv("ATHENA_EARNINGS_STATE_DIR", str(root))
    with pytest.raises(Exception) as caught:
        other_arm_exposure("intraday")
    assert type(caught.value).__name__ in {"SharedExposureUnreadable", "SharedBookBusy"}
    assert "another paper runner holds" not in str(caught.value)
    assert stat.S_IMODE(sqlite.stat().st_mode) == 0


def test_both_runners_read_each_other_while_both_journals_stay_open(tmp_path):
    earnings = tmp_path / "earnings"
    intraday = tmp_path / "athena"
    earnings.mkdir()
    intraday.mkdir()
    ready_e = tmp_path / "ready-earnings"
    ready_i = tmp_path / "ready-intraday"
    out_e = tmp_path / "out-earnings"
    out_i = tmp_path / "out-intraday"
    script = """
import os, time
from datetime import date
from pathlib import Path
from athena_trading.paper.journal import PaperJournal
from athena_trading.paper.shared_risk import other_arm_exposure
role = os.environ["ROLE"]
order = {
    "client_order_id": "athe-deck" if role == "earnings" else "athp-aapl",
    "symbol": "DECK" if role == "earnings" else "AAPL",
    "side": "buy", "qty": "19" if role == "earnings" else "1",
    "limit_price": "100" if role == "earnings" else "101.50",
    "stop_loss": {"stop_price": "98"},
}
path = Path(os.environ["OWN"])
journal = PaperJournal(path)
journal.append("entry_intent", order=order)
Path(os.environ["READY"]).write_text("up")
deadline = time.time() + 20
while time.time() < deadline:
    if Path(os.environ["PEER_READY"]).exists():
        break
    time.sleep(0.02)
else:
    Path(os.environ["OUT"]).write_text("peer did not start")
    journal.close()
    raise SystemExit(1)
try:
    if role == "earnings":
        rows = other_arm_exposure("earnings", today=date(2026, 10, 13))
    else:
        rows = other_arm_exposure("intraday")
    Path(os.environ["OUT"]).write_text(",".join(f"{row.symbol}:{row.notional}" for row in rows))
except Exception as exc:
    Path(os.environ["OUT"]).write_text(type(exc).__name__ + ": " + str(exc))
finally:
    journal.close()
"""
    env = _peer_env(earnings, intraday)
    procs = []
    specs = (
        ("earnings", earnings / "book.sqlite", ready_e, ready_i, out_e),
        ("intraday", intraday / "2026-10-13.sqlite", ready_i, ready_e, out_i),
    )
    for role, own, ready, peer_ready, out in specs:
        child = env.copy()
        child.update(ROLE=role, OWN=str(own), READY=str(ready), PEER_READY=str(peer_ready), OUT=str(out))
        procs.append(subprocess.Popen(
            [sys.executable, "-c", script],
            cwd=str(Path(__file__).resolve().parents[1]), env=child,
        ))
    try:
        for proc in procs:
            assert proc.wait(timeout=30) == 0
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.kill()
    assert out_i.read_text() == "DECK:1900.0"
    assert out_e.read_text() == "AAPL:101.5"


def test_uncertainty_uses_the_same_population_as_expectancy():
    """Abstentions are zero returns. Skipped sessions stay in the common blocks."""
    taken = _item(
        opportunity_id="1", session="2026-01-01", at="2026-01-01T15:00:00Z",
        decision_close=100.0, next_open=100.0, next_close=110.0, stop=90.0, target=130.0,
        jev_without_memory="TAKE_TRADE", jev_with_memory="NO_TRADE",
    )
    skipped = _item(
        opportunity_id="2", session="2026-01-02", at="2026-01-02T15:00:00Z",
        decision_close=100.0, next_open=100.0, next_close=110.0, stop=90.0, target=130.0,
        jev_without_memory="NO_TRADE", jev_with_memory="NO_TRADE",
    )
    report = compare_policies([taken, skipped], resamples=40, seed=7)
    selective = report["policies"]["jev_without_memory"]
    assert selective["expectancy_per_opportunity"] == pytest.approx(5.0)
    assert selective["uncertainty"]["mean"] == pytest.approx(5.0)
    assert selective["uncertainty"]["sessions"] == 2
    assert selective["uncertainty"]["n"] == 2
    assert selective["uncertainty"]["lower"] != pytest.approx(10.0)
    assert report["policies"]["deterministic"]["uncertainty"]["sessions"] == 2
    paired = report["paired_session_differences"]["jev_without_memory_minus_deterministic"]
    assert paired["sessions"] == 2
    assert paired["mean"] == pytest.approx(-5.0)


def test_untouched_stop_is_not_an_observed_adverse_excursion():
    flat = _item(
        decision_close=100.0, next_open=100.0, next_close=100.0, stop=90.0, direction="LONG",
    )
    moved = _item(
        decision_close=100.0, next_open=100.0, next_close=100.0, stop=80.0, direction="LONG",
    )
    assert adverse_excursion(flat) == adverse_excursion(moved)
    assert adverse_excursion(flat) != pytest.approx(-10.0)
    from athena_trading.paper import evaluation
    detail = getattr(evaluation, "adverse_excursion_detail", None)
    assert detail is not None
    first, second = detail(flat), detail(moved)
    assert first["observed"] == second["observed"]
    assert first["path"] == "unavailable"
    assert first["kind"] == "close_only"
    assert first["stop_distance_bound"] != second["stop_distance_bound"]
    assert first["observed"] != first["stop_distance_bound"]
