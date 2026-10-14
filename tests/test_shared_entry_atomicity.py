"""Real processes and SQLite journals; all broker transports are in-memory fixtures."""
from __future__ import annotations

import copy
import multiprocessing as mp
import os
import sqlite3
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from athena_trading.paper import earnings, live, shared_risk
from athena_trading.paper.earnings_calendar import EarningsReport
from athena_trading.paper.journal import PaperJournal
from test_active_paper import Broker
from test_earnings_paper import BookBroker, fill_bracket, nasdaq

NOW = datetime(2026, 10, 13, 13, 46, 5, tzinfo=UTC)


def _configure(root):
    os.environ["ATHENA_STATE_DIR"] = str(root / "intraday")
    os.environ["ATHENA_EARNINGS_STATE_DIR"] = str(root / "earnings")
    os.environ["ATHENA_SHARED_RISK_DIR"] = str(root / "shared-risk")


def _entry(identity="athe-peer", symbol="DECK", qty="19"):
    return {"client_order_id": identity, "symbol": symbol, "side": "buy", "qty": qty,
            "limit_price": "104", "stop_loss": {"stop_price": "102"},
            "time_in_force": "gtc"}


def _commit(arm, root, *, same_symbol=False, hook=None):
    """Exercise the actual post-model submission methods, never a copied gate."""
    _configure(root)
    path = root / ("earnings/book.sqlite" if arm == "earnings" else "intraday/2026-10-13.sqlite")
    journal = PaperJournal(path)
    broker = BookBroker() if arm == "earnings" else Broker()
    broker.journal = journal
    broker.state["clock"].update(timestamp=NOW.isoformat(), next_close="2026-10-13T20:00:00Z")
    broker.state["account"]["buying_power"] = "2000"
    if hook:
        hook(journal, broker)
    packet = {"signal_at": (NOW - timedelta(seconds=65)).isoformat(),
              "observations": {"prior_close": 100}}
    if arm == "earnings":
        policy = earnings.EarningsPolicy(str(root / "universe.txt"))
        runner = earnings.EarningsBook(broker, None, journal, policy, calendar_transport=nasdaq())
        plan = earnings.plan_entry(
            price=104, prior_close=100, open_risk=0, open_notional=0,
            equity=100000, buying_power=2000, per_trade_risk=policy.per_trade_risk,
            total_risk=policy.total_risk, max_notional_per_trade=policy.max_notional_per_trade,
            max_notional_total=policy.max_notional_total, gap_low=policy.gap_low,
            gap_high=policy.gap_high, stop_gap_fraction=policy.stop_gap_fraction, target_r=policy.target_r,
        )
        result = runner._commit(
            earnings.bracket_order("DECK", plan), packet, plan,
            EarningsReport("DECK", "2026-10-13", "BMO"), account_id="paper-account",
            observed_at=NOW, session_day="2026-10-13", verdict_hash="fixture",
        )
    else:
        symbol = "DECK" if same_symbol else "AAPL"
        runner = live.ActivePaperPilot(broker, None, journal, live.PilotPolicy(symbol))
        order = {"symbol": symbol, "qty": "1", "side": "buy", "type": "limit",
                 "limit_price": "101.50", "time_in_force": "day", "order_class": "bracket",
                 "extended_hours": False, "stop_loss": {"stop_price": "100"},
                 "take_profit": {"limit_price": "104.50"}}
        result = runner._commit_order(
            order, packet, account_id="paper-account", observed_at=NOW,
            session_day="2026-10-13", verdict_hash="fixture", allow_stale=False, fallback=None,
        )
    posts = [order for method, path, order in broker.calls if method == "POST" and path == "/v2/orders"]
    journal.close()
    return result, posts


def _contender(arm, root, same_symbol, queue, read_ready=None, release=None, crash=None):
    root = Path(root)
    if read_ready is not None:
        original = shared_risk.other_arm_exposure

        def pause_after_peer_read(role, **kwargs):
            rows = original(role, **kwargs)
            read_ready.set()
            assert release.wait(10), "parent failed to release reader"
            return rows

        earnings.other_arm_exposure = pause_after_peer_read
        live.other_arm_exposure = pause_after_peer_read

    def hook(journal, broker):
        if crash:
            original = journal.append

            def crash_on_intent(kind, **data):
                if kind == "entry_intent" and crash == "before_checkpoint":
                    journal._checkpoint = lambda: os._exit(73)
                original(kind, **data)
                if kind == "entry_intent":
                    os._exit(73)

            journal.append = crash_on_intent

    queue.put((arm, *_commit(arm, root, same_symbol=same_symbol, hook=hook)))


def _join(process, expected=0):
    process.join(15)
    if process.is_alive():
        process.kill()
        process.join()
        pytest.fail("entry process did not terminate")
    assert process.exitcode == expected


@pytest.mark.parametrize("same_symbol", [False, True])
@pytest.mark.parametrize("first_arm", ["earnings", "intraday"])
def test_concurrent_read_check_reserve_is_one_account_transaction(tmp_path, first_arm, same_symbol):
    # The first real peer read sees no reservation and pauses. Without coordination,
    # the second real runner also authorizes before the first has durably reserved.
    ctx = mp.get_context("spawn")
    queue, ready, release = ctx.Queue(), ctx.Event(), ctx.Event()
    second_arm = "intraday" if first_arm == "earnings" else "earnings"
    first = ctx.Process(target=_contender, args=(first_arm, str(tmp_path), same_symbol, queue, ready, release))
    second = ctx.Process(target=_contender, args=(second_arm, str(tmp_path), same_symbol, queue))
    first.start()
    try:
        assert ready.wait(10)
        second.start()
        _join(second)
        release.set()
        _join(first)
        results = [queue.get(timeout=2), queue.get(timeout=2)]
        posts = [order for _arm, _result, orders in results for order in orders]
        assert len(posts) == 1, results
        assert sum(float(order["qty"]) * float(order["limit_price"]) for order in posts) <= 2000
        assert sorted(result for _arm, result, _orders in results) == ["ENTRY_SUBMITTED", "SHARED_RISK_BLOCKED"]
        # Once the holder exits, a fresh runner must still reject the reservation.
        # Deferring only while the mutex is held would not provide durable safety.
        retried, retry_posts = _commit(second_arm, tmp_path, same_symbol=same_symbol)
        assert retried == "SHARED_RISK_BLOCKED"
        assert retry_posts == []
    finally:
        release.set()
        for process in (first, second):
            if process.pid and process.is_alive():
                process.kill()
                process.join()


@pytest.mark.parametrize("crash", ["after_checkpoint", "before_checkpoint"])
def test_process_death_keeps_reservation_and_releases_account_lock(tmp_path, crash):
    ctx = mp.get_context("spawn")
    queue = ctx.Queue()
    process = ctx.Process(target=_contender, args=("earnings", str(tmp_path), False, queue, None, None, crash))
    process.start()
    _join(process, 73)
    result, posts = _commit("intraday", tmp_path)
    assert result == "SHARED_RISK_BLOCKED"
    assert posts == []
    _configure(tmp_path)
    assert shared_risk.other_arm_exposure("intraday")[0].notional == 1976
    # Recovery may reopen the writer and preserve the one-row commit/checkpoint window.
    recovered = PaperJournal(tmp_path / "earnings/book.sqlite")
    assert shared_risk.exposures_from_journal(recovered, "earnings")[0].notional == 1976
    recovered.close()


def test_account_sample_cannot_precede_the_order_used_for_a_buying_power_exemption(tmp_path):
    _configure(tmp_path)
    peer = PaperJournal(tmp_path / "earnings/book.sqlite")
    inserted = False
    reads = []

    def hook(journal, broker):
        original = broker.call

        def call(method, path, payload=None):
            nonlocal inserted
            reads.append(path)
            if path == "/v2/clock":
                return copy.deepcopy(broker.state["clock"])
            if path == "/v2/account":
                return copy.deepcopy(broker.state["account"])
            if path == "/v2/positions":
                if not inserted:
                    order = {**_entry(), "id": "earn-peer", "status": "new", "filled_qty": "0"}
                    peer.append("entry_intent", order=order)
                    peer.append("entry_ack", client_order_id=order["client_order_id"], order=order)
                    broker.state["orders"] = [order]
                    broker.state["account"]["buying_power"] = "24"
                    inserted = True
                return []
            if path == "/v2/orders?status=open&nested=true&limit=500":
                return copy.deepcopy(broker.state["orders"])
            return original(method, path, payload)

        broker.call = call
        broker.snapshot = lambda: live.LivePaperAPI.snapshot(broker)

    result, posts = _commit("intraday", tmp_path, hook=hook)
    peer.close()
    assert result in {"RISK_CHANGED", "SHARED_RISK_BLOCKED"}
    assert posts == []
    assert reads.index("/v2/account") > reads.index("/v2/orders?status=open&nested=true&limit=500")


@pytest.mark.parametrize("filled,exited,expected", [("0", "0", 1976), ("10", "5", 1456)])
def test_gtc_done_for_day_stays_reserved_across_restart_and_next_session(tmp_path, filled, exited, expected):
    _configure(tmp_path)
    path = tmp_path / "earnings/book.sqlite"
    journal = PaperJournal(path)
    order = _entry()
    journal.append("entry_intent", order=order)
    journal.append("entry_observation", client_order_id=order["client_order_id"], order={
        **order, "status": "done_for_day", "filled_qty": filled,
        "legs": [{"side": "sell", "filled_qty": exited}],
    })
    journal.close()
    rows = shared_risk.other_arm_exposure("intraday", today=date(2026, 10, 14))
    assert sum(row.notional for row in rows) == expected
    recovered = PaperJournal(path)
    assert shared_risk.exposures_from_journal(recovered, "earnings")[0].notional == expected
    recovered.append("entry_observation", client_order_id=order["client_order_id"], order={
        **order, "status": "canceled", "filled_qty": filled,
        "legs": [{"side": "sell", "filled_qty": exited}],
    })
    rows = shared_risk.exposures_from_journal(recovered, "earnings")
    assert sum(row.notional for row in rows) == (float(filled) - float(exited)) * 104
    recovered.close()


@pytest.mark.parametrize("corruption", ["truncate", "delete_checkpoint", "delete_database", "wrong_digest"])
def test_read_only_peer_preserves_durable_checkpoint_integrity(tmp_path, corruption):
    _configure(tmp_path)
    path = tmp_path / "earnings/book.sqlite"
    journal = PaperJournal(path)
    journal.append("binding", binding={"arm": "earnings"})
    journal.append("entry_intent", order=_entry())
    journal.close()
    checkpoint = path.with_suffix(".sqlite.checkpoint")
    if corruption == "truncate":
        db = sqlite3.connect(path)
        db.execute("DELETE FROM events WHERE seq=2")
        db.commit()
        db.close()
    elif corruption == "delete_checkpoint":
        checkpoint.unlink()
    elif corruption == "delete_database":
        path.unlink()
    else:
        checkpoint.write_text('{"seq":2,"digest":"wrong"}')
    with pytest.raises(shared_risk.SharedExposureUnreadable):
        shared_risk.other_arm_exposure("intraday")


def test_prior_session_intraday_reservation_stays_in_earnings_risk(tmp_path):
    _configure(tmp_path)
    journal = PaperJournal(tmp_path / "intraday/2026-10-12.sqlite")
    journal.append("entry_intent", order=_entry("athp-old", "AAPL", "1"))
    journal.close()
    rows = shared_risk.other_arm_exposure("earnings", today=date(2026, 10, 13))
    assert [(row.symbol, row.notional) for row in rows] == [("AAPL", 104)]


def test_new_day_reservation_does_not_claim_overnight_exposure(tmp_path):
    journal = PaperJournal(tmp_path / "book.sqlite")
    journal.append("entry_intent", order={**_entry(), "time_in_force": "day"})
    rows = shared_risk.exposures_from_journal(journal, "earnings")
    assert rows[0].overnight is False
    journal.close()


@pytest.mark.parametrize("arm", ["intraday", "earnings"])
def test_occupied_entry_coordinator_does_not_delay_model_free_session_exit(tmp_path, arm):
    observed = {}

    def hook(journal, broker):
        observed["broker"] = broker
        if arm == "intraday":
            journal.append("binding", binding={
                "account_id": "paper-account", "policy": asdict(live.PilotPolicy("AAPL")),
            })

    result, posts = _commit(arm, tmp_path, hook=hook)
    assert result == "ENTRY_SUBMITTED"
    broker = observed["broker"]
    if arm == "earnings":
        fill_bracket(broker, posts[0]["client_order_id"])
        path = tmp_path / "earnings/book.sqlite"
    else:
        broker.parent.update(status="filled", filled_qty="1")
        broker.state.update(orders=[], positions=[{"symbol": "AAPL", "qty": "1"}])
        path = tmp_path / "intraday/2026-10-13.sqlite"
    broker.state["clock"]["timestamp"] = "2026-10-13T19:46:05Z"
    journal = PaperJournal(path)
    broker.journal = journal
    blocker = PaperJournal(tmp_path / "coordinator-holder.sqlite")
    try:
        if arm == "earnings":
            runner = earnings.EarningsBook(
                broker, None, journal, earnings.EarningsPolicy(str(tmp_path / "universe.txt")),
                calendar_transport=nasdaq(),
            )
        else:
            runner = live.ActivePaperPilot(broker, None, journal, live.PilotPolicy("AAPL"))
        with shared_risk.entry_coordination(blocker, "paper-account"):
            assert runner.tick() == "FLATTENING"
        assert any(method == "DELETE" for method, _path, _payload in broker.calls)
        assert len([method for method, _path, _payload in broker.calls if method == "POST"]) == 1
    finally:
        blocker.close()
        journal.close()


@pytest.mark.parametrize("failure", ["missing", "unusable"])
def test_missing_or_unusable_coordinator_blocks_only_new_entries(tmp_path, failure):
    def hook(journal, broker):
        if failure == "missing":
            os.environ.pop("ATHENA_SHARED_RISK_DIR", None)
        else:
            bad = tmp_path / "not-a-directory"
            bad.write_text("blocked")
            os.environ["ATHENA_SHARED_RISK_DIR"] = str(bad)

    result, posts = _commit("intraday", tmp_path, hook=hook)
    assert result == "SHARED_RISK_BLOCKED"
    assert posts == []


def test_changed_coordinator_is_not_silently_a_different_account_lock(tmp_path):
    assert _commit("intraday", tmp_path)[0] == "ENTRY_SUBMITTED"

    def hook(journal, broker):
        os.environ["ATHENA_SHARED_RISK_DIR"] = str(tmp_path / "wrong-risk-directory")
        broker.state["account"]["buying_power"] = "100000"

    result, posts = _commit("earnings", tmp_path, hook=hook)
    assert result == "SHARED_RISK_BLOCKED"
    assert posts == []


def test_entry_coordination_works_without_peer_directory_write_access(tmp_path):
    assert os.geteuid() != 0, "permission proof must run unprivileged"
    assert _commit("earnings", tmp_path)[0] == "ENTRY_SUBMITTED"
    peer = tmp_path / "earnings"
    before = {path.name: path.read_bytes() for path in peer.iterdir()}
    for path in peer.iterdir():
        path.chmod(0o444)
    peer.chmod(0o555)

    def hook(journal, broker):
        broker.state["account"]["buying_power"] = "3000"

    result, posts = _commit("intraday", tmp_path, hook=hook)
    assert result == "ENTRY_SUBMITTED"
    assert len(posts) == 1
    assert {path.name: path.read_bytes() for path in peer.iterdir()} == before
    assert peer.stat().st_mode & 0o777 == 0o555


def test_units_grant_only_dedicated_shared_coordination_write_path():
    root = Path(__file__).resolve().parents[1]
    for name, peer in [("athena-paper", "/var/lib/athena-earnings"), ("athena-earnings", "/var/lib/athena")]:
        unit = (root / "deploy" / f"{name}.service").read_text()
        assert "Environment=ATHENA_SHARED_RISK_DIR=/var/lib/athena-risk" in unit
        write_paths = next(line.split("=", 1)[1].split() for line in unit.splitlines() if line.startswith("ReadWritePaths="))
        assert "/var/lib/athena-risk" in write_paths
        assert peer not in write_paths
        assert "ProtectSystem=strict" in unit and "UMask=0077" in unit
    assert "install -d -m 0700 -o athena -g athena /var/lib/athena-risk" in (root / "deploy/install.sh").read_text()
