"""Adversarial close/restart sequences. All broker activity is in-memory."""
from __future__ import annotations

import copy
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlsplit

import pytest

from athena_trading.athena_adapter.jev import ModelError
from athena_trading.paper.earnings import EarningsBook
from athena_trading.paper.journal import PaperJournal
from athena_trading.paper.learning import LearningStore
from athena_trading.paper.ownership import load_ownership_orders, load_ownership_symbols
from test_active_paper import _prepare_flat_history
from test_earnings_paper import (
    NOW, _book, _both_reports, _lose_deck_close, _open_two_symbols, _posts, fill_bracket, nasdaq,
)


@pytest.fixture(autouse=True)
def isolate_learning(tmp_path, monkeypatch):
    monkeypatch.setenv("ATHENA_STATE_DIR", str(tmp_path / "learning"))
    monkeypatch.delenv("ATHENA_EARNINGS_STATE_DIR", raising=False)


def prepare_close(tmp_path, monkeypatch):
    book, broker, journal, _ = _book(tmp_path, monkeypatch)
    assert book.tick() == "ENTRY_SUBMITTED"
    cid = _posts(broker)[0]["client_order_id"]
    fill_bracket(broker, cid)
    for leg in broker.parents[cid]["legs"]:
        leg["status"] = "canceled"
    broker.state["orders"] = []
    return book, broker, journal, cid


def close_order(**changes):
    order = {
        "id": "recovered-close", "client_order_id": "broker-close",
        "symbol": "DECK", "side": "sell", "type": "market", "order_class": "simple",
        "qty": "19", "filled_qty": "0", "filled_avg_price": None, "status": "new",
        "created_at": NOW.isoformat(), "submitted_at": NOW.isoformat(),
    }
    order.update(changes)
    return order


def lose_before_acceptance(broker):
    original = broker.call
    def call(method, path, payload=None):
        if method == "DELETE" and urlsplit(path).path == "/v2/positions/DECK":
            broker.calls.append((method, path, payload))
            raise ModelError("timeout")
        return original(method, path, payload)
    broker.call = call
    return original


def restart(tmp_path, book, broker, journal, calendar=nasdaq):
    journal.close()
    reopened = PaperJournal(tmp_path / "book.sqlite")
    return EarningsBook(broker, None, reopened, book.policy, calendar_transport=calendar()), reopened


def position_deletes(broker, symbol="DECK"):
    return [path for method, path, _ in broker.calls
            if method == "DELETE" and urlsplit(path).path == "/v2/positions/" + symbol]


@pytest.mark.parametrize("changes", [
    {"side": "buy"}, {"qty": "1"}, {"qty": "19.01"},
    {"created_at": "2026-10-12T13:40:05Z"},
    {"created_at": (NOW + timedelta(minutes=2)).isoformat()},
    {"created_at": None, "submitted_at": None},
    {"submitted_at": "2026-10-12T13:40:05Z"},
], ids=["side", "qty", "fractional-qty", "old", "late", "untimed", "old-submission"])
def test_lost_close_rejects_an_unrelated_market_order(tmp_path, monkeypatch, changes):
    book, broker, journal, cid, _ = _open_two_symbols(tmp_path, monkeypatch)
    lost = _lose_deck_close(broker)
    with pytest.raises(ModelError, match="timeout"):
        book.tick()
    unrelated = close_order(**changes)
    broker.state["orders"] = [unrelated]
    book, journal = restart(tmp_path, book, broker, journal, _both_reports)
    try:
        assert book.tick() == "FLATTENING"
        assert book._last("close_ack", cid) is None
        assert len(position_deletes(broker)) == 1
        assert position_deletes(broker, "CROX")
        # Even after the unrelated BUY disappears and changes the net position,
        # a pending close may not acquire authority over the new shares.
        broker.state["orders"] = []
        broker.state["positions"][0]["qty"] = "38"
        assert book.tick() in {"FLATTENING", "POSITION_MISMATCH"}
        assert len(position_deletes(broker)) == 1
        assert lost["order"] is not None
    finally:
        journal.close()


@pytest.mark.parametrize("duplicate", [False, True])
def test_terminal_lost_close_recovers_after_restart(tmp_path, monkeypatch, duplicate):
    book, broker, journal, cid = prepare_close(tmp_path, monkeypatch)
    original = lose_before_acceptance(broker)
    with pytest.raises(ModelError, match="timeout"):
        book.tick()
    terminal = close_order(status="filled", filled_qty="19", filled_avg_price="106")
    broker.state["positions"] = []
    def call(method, path, payload=None):
        if method == "GET" and path.startswith("/v2/orders?"):
            broker.calls.append((method, path, payload))
            return [copy.deepcopy(terminal)] * (2 if duplicate else 1)
        return original(method, path, payload)
    broker.call = call
    book, journal = restart(tmp_path, book, broker, journal)
    try:
        assert book.tick() == "FLATTENING"
        book.tick()
        assert book.open_trades() == {}
        assert journal.last("position_closed")["client_order_id"] == cid
        assert journal.last("learning_recorded")
        assert len(position_deletes(broker)) == 1
        with_store = LearningStore(tmp_path / "learning")
        try:
            assert Decimal(with_store.experiences()[0]["gross_pnl"]) == Decimal("38")
        finally:
            with_store.close()
    finally:
        journal.close()


@pytest.mark.parametrize("history", [[], "unavailable", "truncated", "conflicting", "ambiguous"])
def test_unresolved_flat_close_remains_visible(tmp_path, monkeypatch, history):
    book, broker, journal, _ = prepare_close(tmp_path, monkeypatch)
    original = lose_before_acceptance(broker)
    with pytest.raises(ModelError, match="timeout"):
        book.tick()
    broker.state["positions"] = []
    order = close_order(status="filled", filled_qty="19", filled_avg_price="106")
    def call(method, path, payload=None):
        if method == "GET" and path.startswith("/v2/orders?"):
            if history == "unavailable":
                raise ModelError("timeout")
            if history == "truncated":
                return [order] * 500
            if history == "conflicting":
                return [order, dict(order, side="buy")]
            if history == "ambiguous":
                return [order, dict(order, id="other-close")]
            return history
        return original(method, path, payload)
    broker.call = call
    try:
        assert [book.tick() for _ in range(3)] == ["FLATTENING"] * 3
        assert journal.last("position_closed") is None
        assert journal.last("close_ack") is None
        assert len(position_deletes(broker)) == 1
    finally:
        journal.close()


@pytest.mark.parametrize("position_qty", ["38", "19.01", "18.99", "-19"])
def test_close_path_rechecks_owned_residual_before_delete(tmp_path, monkeypatch, position_qty):
    book, broker, journal, cid = prepare_close(tmp_path, monkeypatch)
    book.request_flatten_owned()
    broker.state["positions"][0]["qty"] = position_qty
    try:
        assert book.tick() == "POSITION_MISMATCH"
        assert position_deletes(broker) == []
        assert book._last("position_closed", cid) is None
    finally:
        journal.close()


def test_working_partial_close_must_refresh_before_outcome(tmp_path, monkeypatch):
    book, broker, journal, _ = prepare_close(tmp_path, monkeypatch)
    original = broker.call
    def call(method, path, payload=None):
        ack = original(method, path, payload)
        if method == "DELETE" and urlsplit(path).path == "/v2/positions/DECK":
            return dict(ack, status="partially_filled", filled_qty="5", filled_avg_price="106")
        return ack
    broker.call = call
    assert book.tick() == "FLATTENING"
    oid = journal.last("close_ack")["order"]["id"]
    broker.order_by_id[oid].update(status="filled", filled_qty="19", filled_avg_price="106")
    broker.state["positions"] = []
    try:
        for _ in range(3):
            book.tick()
        assert journal.last("position_closed")
        assert journal.last("earnings_experience")["close_orders"][0]["filled_qty"] == "19"
    finally:
        journal.close()


@pytest.mark.parametrize("status, first_fill", [
    ("canceled", "0"), ("rejected", "0"), ("expired", "0"), ("canceled", "5"),
])
def test_retry_aggregates_terminal_attempts_and_closes_only_residual(
    tmp_path, monkeypatch, status, first_fill,
):
    book, broker, journal, _ = prepare_close(tmp_path, monkeypatch)
    assert book.tick() == "FLATTENING"
    first = copy.deepcopy(journal.last("close_ack")["order"])
    broker.order_by_id[first["id"]] = dict(
        first, status=status, filled_qty=first_fill,
        filled_avg_price="106" if first_fill == "5" else None,
    )
    residual = str(19 - int(first_fill))
    broker.state["positions"][0]["qty"] = residual
    original = broker.call
    def call(method, path, payload=None):
        if method == "DELETE" and urlsplit(path).path == "/v2/positions/DECK":
            broker.calls.append((method, path, payload))
            second = dict(first, id="second-close", qty=residual)
            broker.order_by_id["second-close"] = dict(
                second, status="filled", filled_qty=residual, filled_avg_price="106",
            )
            return second
        return original(method, path, payload)
    broker.call = call
    try:
        assert book.tick() == "FLATTENING"
        assert journal.last("close_intent")["positions"][0]["qty"] == residual
        broker.state["positions"] = []
        for _ in range(3):
            book.tick()
        assert journal.last("position_closed")
        store = LearningStore(tmp_path / "learning")
        try:
            assert Decimal(store.experiences()[0]["gross_pnl"]) == Decimal("38")
        finally:
            store.close()
    finally:
        journal.close()


@pytest.mark.parametrize("changes", [
    {"id": "unrelated"}, {"symbol": "CROX"}, {"side": "buy"}, {"qty": "38"},
])
def test_refreshed_close_must_preserve_acknowledged_identity(tmp_path, monkeypatch, changes):
    book, broker, journal, _ = prepare_close(tmp_path, monkeypatch)
    assert book.tick() == "FLATTENING"
    oid = journal.last("close_ack")["order"]["id"]
    broker.order_by_id[oid].update(changes)
    broker.state["positions"] = []
    try:
        assert [book.tick() for _ in range(3)] == ["FLATTENING"] * 3
        assert journal.last("position_closed") is None
    finally:
        journal.close()


def test_closed_earnings_ownership_survives_ledger_and_restart(tmp_path, monkeypatch):
    earnings_dir = tmp_path / "earnings"
    earnings_dir.mkdir()
    book, broker, journal, cid = prepare_close(earnings_dir, monkeypatch)
    assert book.tick() == "FLATTENING"
    oid = journal.last("close_ack")["order"]["id"]
    broker.state["positions"] = []
    for _ in range(3):
        book.tick()
    assert not book.open_trades()
    assert load_ownership_symbols(earnings_dir) == set()
    book, journal = restart(earnings_dir, book, broker, journal)
    book.publish_ledger()
    other_dir = tmp_path / "intraday"
    other_dir.mkdir()
    history = [copy.deepcopy(broker.parents[cid]), copy.deepcopy(broker.order_by_id[oid])]
    pilot, _, intraday_journal = _prepare_flat_history(other_dir, monkeypatch, history)
    monkeypatch.setenv("ATHENA_EARNINGS_STATE_DIR", str(earnings_dir))
    try:
        assert pilot.tick() == "FLATTENING"
        assert pilot.tick() == "COMPLETE"
        flat = intraday_journal.last("flat_confirmed")
        assert any(row["id"] == oid for row in flat["account_order_history"])
        assert all(row.get("symbol") == "AAPL" for row in flat["order_history"])
    finally:
        intraday_journal.close()
        journal.close()


def test_active_symbol_ledger_never_hides_unowned_history(tmp_path, monkeypatch):
    pilot, _, journal = _prepare_flat_history(tmp_path, monkeypatch, [
        close_order(id="manual-deck-order", status="filled", filled_qty="19", filled_avg_price="106"),
    ])
    try:
        assert pilot.tick() == "FLATTENING"
        with pytest.raises(ValueError, match="unexplained"):
            pilot.tick()
        assert journal.last("flat_confirmed") is None
    finally:
        journal.close()


@pytest.mark.parametrize("close_time, before, cutoff", [
    ("16:00", "2026-10-13T19:44:59Z", "2026-10-13T19:45:00Z"),
    ("13:00", "2026-10-13T16:44:59Z", "2026-10-13T16:45:00Z"),
])
def test_no_overnight_closes_at_actual_session_buffer(
    tmp_path, monkeypatch, close_time, before, cutoff,
):
    book, broker, journal, _ = _book(tmp_path, monkeypatch)
    assert book.tick() == "ENTRY_SUBMITTED"
    cid = _posts(broker)[0]["client_order_id"]
    fill_bracket(broker, cid)
    original = broker.call
    def call(method, path, payload=None):
        value = original(method, path, payload)
        if path.startswith("/v2/calendar"):
            for row in value:
                if row["date"] == "2026-10-13":
                    row["close"] = close_time
        return value
    broker.call = call
    try:
        broker.state["clock"]["timestamp"] = before
        assert book.tick() == "POSITION_OPEN"
        broker.state["clock"]["timestamp"] = cutoff
        assert book.tick() == "FLATTENING"
        assert book._last("trade_exit", cid)["reason"] == "SESSION_CLOSE"
        for leg in broker.parents[cid]["legs"]:
            leg["status"] = "canceled"
        broker.state["orders"] = []
        assert book.tick() == "FLATTENING"
        assert len(position_deletes(broker)) == 1
        assert len(_posts(broker)) == 1
    finally:
        journal.close()


def test_multiday_configuration_blocks_new_entries_but_preserves_recovery(tmp_path, monkeypatch):
    from dataclasses import replace
    book, broker, journal, cid = prepare_close(tmp_path, monkeypatch)
    assert book.policy.max_hold_sessions == 1
    # A legacy persistent policy remains readable; it never authorizes another hold.
    old = replace(book.policy, max_hold_sessions=3)
    # Use a separate legacy-bound book rather than weakening the current journal binding.
    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    legacy_journal = PaperJournal(legacy_dir / "book.sqlite")
    from dataclasses import asdict
    legacy_journal.append("binding", binding={"account_id": "paper-account", "policy": asdict(old)})
    for event in journal.events:
        if event["kind"] in {"entry_intent", "entry_ack"}:
            legacy_journal.append(event["kind"], **{k: v for k, v in event.items() if k != "kind"})
    recovered = EarningsBook(broker, None, legacy_journal, old, calendar_transport=nasdaq())
    try:
        assert recovered.tick() == "FLATTENING"
        assert len(position_deletes(broker)) == 1
        broker.state["positions"] = []
        for _ in range(3):
            status = recovered.tick()
        assert recovered.open_trades() == {}
        assert status == "MULTIDAY_POLICY_DISABLED"
        assert len(_posts(broker)) == 1
    finally:
        legacy_journal.close()
        journal.close()


def test_new_bracket_is_day_only(tmp_path, monkeypatch):
    book, broker, journal, _ = _book(tmp_path, monkeypatch)
    try:
        assert book.tick() == "ENTRY_SUBMITTED"
        assert _posts(broker)[0]["time_in_force"] == "day"
    finally:
        journal.close()


def test_closed_market_keeps_overnight_breach_visible_then_recovers_at_open(tmp_path, monkeypatch):
    book, broker, journal, cid = prepare_close(tmp_path, monkeypatch)
    # Restore broker protection so only the no-overnight deadline causes the exit.
    broker.parents[cid]["legs"][1]["status"] = "held"
    broker.state["clock"].update(timestamp="2026-10-13T20:01:00Z", is_open=False)
    try:
        assert book.tick() == "EXIT_UNRESOLVED"
        assert position_deletes(broker) == []
        assert journal.last("exit_unresolved")["reason"] == "MARKET_CLOSED"
        book, journal = restart(tmp_path, book, broker, journal)
        broker.state["clock"].update(timestamp="2026-10-14T13:30:00Z", is_open=True)
        assert book.tick() == "FLATTENING"
        for leg in broker.parents[cid]["legs"]:
            leg["status"] = "canceled"
        broker.state["orders"] = []
        assert book.tick() == "FLATTENING"
        assert len(position_deletes(broker)) == 1
    finally:
        journal.close()


def test_close_request_cannot_expand_after_a_concurrent_manual_addition(tmp_path, monkeypatch):
    from urllib.parse import parse_qs, urlsplit
    book, broker, journal, _ = prepare_close(tmp_path, monkeypatch)
    original = broker.call
    sent = []
    def call(method, path, payload=None):
        if method == "DELETE" and path.startswith("/v2/positions/DECK"):
            broker.state["positions"][0]["qty"] = "38"
            sent.append(parse_qs(urlsplit(path).query))
        return original(method, path, payload)
    broker.call = call
    try:
        assert book.tick() == "FLATTENING"
        assert sent == [{"qty": ["19"]}]
        assert journal.last("close_ack")["order"]["qty"] == "19"
        # Our 19-share close completes, leaving only the manual 19 shares.
        broker.state["positions"][0]["qty"] = "19"
        assert book.tick() == "POSITION_MISMATCH"
        assert len(sent) == 1
    finally:
        journal.close()


def test_old_wrong_symbol_close_ack_cannot_create_an_earnings_outcome(tmp_path, monkeypatch):
    book, broker, journal, cid = prepare_close(tmp_path, monkeypatch)
    book._begin_close(book.open_trades()[cid], "PROTECTION_MISSING")
    journal.append("close_ack", client_order_id=cid, attempt=1, order=close_order(
        symbol="CROX", status="filled", filled_qty="19", filled_avg_price="106",
    ))
    broker.state["positions"] = []
    try:
        assert [book.tick() for _ in range(3)] == ["FLATTENING"] * 3
        assert journal.last("position_closed") is None
        assert journal.last("learning_recorded") is None
        assert "recovered-close" not in load_ownership_orders(tmp_path, "paper-account")
    finally:
        journal.close()


@pytest.mark.parametrize("kind", ["earnings_experience", "position_closed"])
@pytest.mark.parametrize("after", [False, True])
def test_finalization_survives_each_durable_append_boundary(tmp_path, monkeypatch, kind, after):
    book, broker, journal, _ = prepare_close(tmp_path, monkeypatch)
    assert book.tick() == "FLATTENING"
    broker.state["positions"] = []
    assert book.tick() == "FLATTENING"
    original = journal.append
    def append(event, **data):
        if event == kind and not after:
            raise RuntimeError("simulated finalization crash")
        original(event, **data)
        if event == kind and after:
            raise RuntimeError("simulated finalization crash")
    journal.append = append
    with pytest.raises(RuntimeError, match="finalization crash"):
        book.tick()
    book, journal = restart(tmp_path, book, broker, journal)
    try:
        for _ in range(4):
            book.tick()
        for event in ("position_closed", "earnings_experience", "learning_recorded"):
            assert sum(row["kind"] == event for row in journal.events) == 1
        assert not book.open_trades()
        assert len(position_deletes(broker)) == 1
    finally:
        journal.close()


def test_legacy_close_without_receipt_is_recovered_not_forgotten(tmp_path, monkeypatch):
    book, broker, journal, cid = prepare_close(tmp_path, monkeypatch)
    assert book.tick() == "FLATTENING"
    broker.state["positions"] = []
    # Older code could commit this event and die before its outcome receipt.
    journal.append("position_closed", client_order_id=cid, symbol="DECK", reason="PROTECTION_MISSING")
    book, journal = restart(tmp_path, book, broker, journal)
    try:
        assert cid in book.open_trades()
        for _ in range(4):
            book.tick()
        for event in ("position_closed", "earnings_experience", "learning_recorded"):
            assert sum(row["kind"] == event for row in journal.events) == 1
        assert len(position_deletes(broker)) == 1
        assert not book.open_trades()
    finally:
        journal.close()


def test_legacy_receipt_gap_with_unavailable_fills_remains_unresolved(tmp_path, monkeypatch):
    book, broker, journal, cid = prepare_close(tmp_path, monkeypatch)
    assert book.tick() == "FLATTENING"
    broker.state["positions"] = []
    journal.append("position_closed", client_order_id=cid, symbol="DECK", reason="PROTECTION_MISSING")
    original = broker.call
    def call(method, path, payload=None):
        if method == "GET" and path.startswith("/v2/orders/"):
            raise ModelError("timeout")
        return original(method, path, payload)
    broker.call = call
    book, journal = restart(tmp_path, book, broker, journal)
    try:
        assert [book.tick() for _ in range(3)] == ["FLATTENING"] * 3
        assert cid in book.open_trades()
        assert journal.last("earnings_experience") is None
        assert journal.last("learning_recorded") is None
        assert len(position_deletes(broker)) == 1
    finally:
        journal.close()
