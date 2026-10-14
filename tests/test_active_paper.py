from __future__ import annotations

import copy
import importlib.util
import math
import os
import sqlite3
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from athena_trading.athena_adapter.jev import (
    JEV_ENDPOINT, JEV_MODEL, JevDecisionEngine, ModelError, questions, request_json,
)
from athena_trading.execution.authority import (
    AuthorityError, ExecutionAuthority, parse_authority,
)
from athena_trading.paper import cloud
from athena_trading.paper.ownership import write_ownership_ledger
from athena_trading.paper.journal import PaperJournal
from athena_trading.paper.learning import maintain, outcome
from athena_trading.paper.live import (
    ActivePaperPilot, DataDeferral, LivePaperAPI, PilotPolicy, policy_from_environment,
    signal_packet,
)

NOW = datetime(2026, 9, 24, 13, 46, 5, tzinfo=UTC)
OPEN = NOW.replace(minute=30, second=0)
POLICY = PilotPolicy("AAPL")


def response(choice="TAKE_TRADE", confidence=0.9):
    return {"model": JEV_MODEL, "usage": {"input_tokens": 300, "output_tokens": 50},
            "answers": {key: {"type": "choice", "choice": choice,
                              "confidence": confidence,
                              "probabilities": {opt: 0.9 if opt == choice else 0.05
                                                for opt in ("TAKE_TRADE", "NO_TRADE", "INSUFFICIENT_EVIDENCE")}}
                        for key in questions()}}


def scored_response(take, confidence, choice="TAKE_TRADE"):
    names = ("TAKE_TRADE", "NO_TRADE", "INSUFFICIENT_EVIDENCE")
    rest = (1.0 - take) / 2.0
    probabilities = {name: take if name == choice else rest for name in names}
    return {"model": JEV_MODEL, "usage": {"input_tokens": 300, "output_tokens": 50},
            "answers": {"entry_decision": {
                "type": "choice", "choice": choice, "confidence": confidence,
                "probabilities": probabilities,
            }}}


def market_bars():
    minute = [{"t": (OPEN + timedelta(minutes=i)).isoformat(), "o": 100, "h": 101,
               "l": 99, "c": 100, "v": 1000} for i in range(15)]
    minute.append({"t": (OPEN + timedelta(minutes=15)).isoformat(), "o": 100.5,
                   "h": 101.8, "l": 100.2, "c": 101.5, "v": 1000})
    daily = [{"t": (OPEN - timedelta(days=i)).isoformat(), "o": 100, "h": 102,
              "l": 98, "c": 100, "v": 2_000_000} for i in range(20, 0, -1)]
    return minute, daily


def snapshot():
    return {"clock": {"timestamp": NOW.isoformat(), "is_open": True,
                      "next_close": NOW.replace(hour=20, minute=0, second=0).isoformat()},
            "account": {"id": "paper-account", "equity": "100000", "last_equity": "100000",
                        "buying_power": "100000", "status": "ACTIVE", "trading_blocked": False},
            "positions": [], "orders": []}


class Broker:
    def __init__(self):
        self.state = snapshot()
        self.calls = []
        self.parent = None
        self.lose_submit_response = False
        self.reject_submit = False
        self.hide_order = False
        self.journal = None

    def snapshot(self):
        return copy.deepcopy(self.state)

    def bars(self, symbol, start, end, timeframe, feed):
        return market_bars()[0 if timeframe == "1Min" else 1]

    def call(self, method, path, payload=None):
        self.calls.append((method, path, copy.deepcopy(payload)))
        if path.startswith("/v2/calendar"):
            return [{"date": "2026-09-23", "open": "09:30", "close": "16:00"},
                    {"date": "2026-09-24", "open": "09:30", "close": "16:00"}]
        if path.startswith("/v2/assets/"):
            return {"status": "active", "tradable": True, "class": "us_equity",
                    "shortable": True, "easy_to_borrow": True}
        if method == "POST":
            if self.reject_submit:
                raise ModelError("HTTP 422", status=422)
            assert self.journal.last("entry_intent"), "reservation must be durable before send"
            self.parent = {**payload, "id": "entry-1", "status": "new", "filled_qty": "0"}
            self.state["orders"] = [copy.deepcopy(self.parent)]
            if self.lose_submit_response:
                raise ModelError("timeout")
            return copy.deepcopy(self.parent)
        if path.startswith("/v2/orders:by_client_order_id"):
            if self.hide_order or self.parent is None:
                raise ModelError("HTTP 404", status=404)
            return copy.deepcopy(self.parent)
        if path.startswith("/v2/orders?"):
            return [copy.deepcopy(self.parent)] if self.parent else []
        if method == "DELETE":
            assert self.journal.last("halt"), "halt must precede any cleanup side effect"
            if path.startswith("/v2/positions/"):
                result = {"id": "close-1", "client_order_id": "broker-close", "symbol": "AAPL",
                          "qty": "1", "side": "sell", "type": "market", "order_class": "simple",
                          "status": "new", "filled_qty": "0"}
                self.state["orders"] = [result]
                return result
            # A cancel acknowledgement deliberately does NOT update broker state in this fixture.
            return None
        raise AssertionError((method, path, payload))


class DecisionHook:
    def __init__(self):
        self.action = "TAKE_TRADE"
        self.after = lambda: None

    def transport(self, *args, **kwargs):
        self.after()
        return response(self.action)


@pytest.fixture
def setup(tmp_path):
    journal = PaperJournal(tmp_path / "paper.sqlite")
    broker, actor = Broker(), DecisionHook()
    broker.journal = journal
    adjudicator = JevDecisionEngine("fixture-key", transport=actor.transport)
    pilot = ActivePaperPilot(broker, adjudicator, journal, POLICY)
    yield pilot, broker, actor, journal
    journal.close()


def test_active_jev_veto_prevents_paper_order(setup):
    pilot, broker, _, journal = setup
    pilot.jev = JevDecisionEngine("fixture-key", transport=lambda *a, **k: response("NO_TRADE"))
    assert pilot.tick() == "JEV_VETO"
    assert not any(method == "POST" for method, _, _ in broker.calls)
    assert journal.last("adjudication")["receipt"]["accepted"] is False


@pytest.mark.parametrize("next_day", [False, True])
def test_cloud_session_stops_if_close_was_missed_or_day_changed(setup, next_day):
    pilot, broker, _, journal = setup
    pilot.session_date = date(2026, 9, 24)
    broker.state["clock"]["is_open"] = next_day
    broker.state["clock"]["timestamp"] = "2026-09-25T13:46:05Z" if next_day else "2026-09-24T20:01:00Z"
    assert pilot.tick() == "COMPLETE"
    assert journal.last("decision_started") is None
    assert not any(method == "POST" for method, _, _ in broker.calls)


def test_supported_jev_order_is_protected_reserved_and_not_a_fill(setup):
    pilot, broker, _, journal = setup
    assert pilot.tick() == "ENTRY_SUBMITTED"
    assert pilot.tick() == "ENTRY_WORKING"
    assert not broker.state["positions"]
    order = journal.last("entry_intent")["order"]
    assert order["qty"] == "1" and order["order_class"] == "bracket"
    assert order["type"] == "limit" and order["extended_hours"] is False
    assert order["stop_loss"]["stop_price"] == "99.00"
    assert sum(m == "POST" for m, _, _ in broker.calls) == 1


def test_lost_submit_response_recovers_without_resubmission(setup):
    pilot, broker, actor, journal = setup
    broker.lose_submit_response = True
    with pytest.raises(ModelError):
        pilot.tick()
    recovered = ActivePaperPilot(broker, pilot.jev, journal, POLICY)
    assert recovered.tick() == "ENTRY_WORKING"
    assert sum(m == "POST" for m, _, _ in broker.calls) == 1


def test_model_error_never_places_order_or_repeats_same_bar(setup):
    pilot, broker, _, journal = setup

    def unavailable(*args, **kwargs):
        raise ModelError("HTTP 429")

    pilot.jev = JevDecisionEngine("fixture-key", transport=unavailable)
    with pytest.raises(ModelError):
        pilot.tick()
    assert pilot.tick() == "ALREADY_REVIEWED"
    assert not journal.last("entry_intent")
    assert not any(m == "POST" for m, _, _ in broker.calls)


def test_jev_abstention_never_submits_an_order(setup):
    pilot, broker, actor, journal = setup
    actor.action = "NO_TRADE"
    assert pilot.tick() == "JEV_VETO"
    assert journal.last("adjudication")["receipt"]["accepted"] is False
    assert not any(m == "POST" for m, _, _ in broker.calls)


@pytest.mark.parametrize("change,expected", [
    (lambda s: s["clock"].update(timestamp=(NOW + timedelta(minutes=3)).isoformat()), "STALE_AFTER_ADJUDICATION"),
    (lambda s: s["clock"].update(is_open=False), "SESSION_BLOCKED"),
    (lambda s: s["account"].update(buying_power="1"), "RISK_CHANGED"),
    (lambda s: s["account"].update(trading_blocked=True), "ACCOUNT_BLOCKED"),
    (lambda s: s["account"].update(status="INACTIVE"), "ACCOUNT_BLOCKED"),
    (lambda s: s["account"].update(equity="99000"), "COMPLETE"),
])
def test_risk_rechecks_after_jev_acceptance(setup, change, expected):
    pilot, broker, actor, journal = setup
    actor.after = lambda: change(broker.state)
    assert pilot.tick() == expected
    assert not journal.last("entry_intent")
    assert not any(m == "POST" for m, _, _ in broker.calls)


def test_preclose_waits_for_cancel_then_fill_and_confirmed_flat(setup):
    pilot, broker, _, journal = setup
    pilot.tick()
    broker.parent.update(status="filled", filled_qty="1")
    broker.state["positions"] = [{"symbol": "AAPL", "qty": "1"}]
    broker.state["orders"] = [{"id": "stop", "symbol": "AAPL", "type": "stop", "side": "sell", "qty": "1"}]
    broker.state["clock"]["timestamp"] = NOW.replace(hour=19, minute=46).isoformat()
    assert pilot.tick() == "FLATTENING"
    assert not any(path.startswith("/v2/positions/") for _, path, _ in broker.calls)
    assert not journal.last("flat_confirmed")
    broker.state["orders"] = []  # broker, not DELETE acknowledgement, confirms cancellation
    assert pilot.tick() == "FLATTENING"
    assert broker.state["positions"]  # close acknowledgement is not a fill either
    assert pilot.tick() == "FLATTENING"
    assert sum(path.startswith("/v2/positions/") for _, path, _ in broker.calls) == 1
    broker.state.update(positions=[], orders=[])
    assert pilot.tick() == "FLATTENING"
    assert pilot.tick() == "COMPLETE"
    assert journal.last("flat_confirmed")


def test_partial_fill_halts_and_is_not_counted_as_full_position(setup):
    pilot, broker, _, journal = setup
    pilot.tick()
    broker.parent.update(status="partially_filled", filled_qty="0.5")
    broker.state["orders"] = [copy.deepcopy(broker.parent)]
    broker.state["positions"] = [{"symbol": "AAPL", "qty": "0.5"}]
    assert pilot.tick() == "FLATTENING"
    assert journal.last("halt")["reason"] == "PARTIAL_ENTRY"
    assert not journal.last("flat_confirmed")


def test_missing_protection_halts_independently_of_jev(setup):
    pilot, broker, _, journal = setup
    pilot.tick()
    broker.parent.update(status="filled", filled_qty="1")
    broker.state.update(orders=[], positions=[{"symbol": "AAPL", "qty": "1"}])
    assert pilot.tick() == "FLATTENING"
    assert journal.last("halt")["reason"] == "PROTECTION_MISSING"


def test_existing_unowned_exposure_is_not_touched(setup):
    pilot, broker, _, journal = setup
    broker.state["positions"] = [{"symbol": "MSFT", "qty": "1"}]
    with pytest.raises(ValueError, match="dedicated"):
        pilot.tick()
    assert not broker.calls
    assert not journal.last("binding")


def test_cleanup_refuses_different_account_even_with_matching_symbol(setup):
    pilot, broker, _, journal = setup
    pilot.tick()
    broker.state["account"]["id"] = "other-account"
    broker.state["positions"] = [{"symbol": "AAPL", "qty": "1"}]
    before = len(broker.calls)
    with pytest.raises(ValueError, match="different account"):
        pilot.flatten_step(broker.snapshot())
    assert len(broker.calls) == before


def test_partially_filled_stop_does_not_protect_its_original_quantity(setup):
    pilot, broker, _, journal = setup
    pilot.tick()
    broker.parent.update(status="filled", filled_qty="1")
    broker.state["positions"] = [{"symbol": "AAPL", "qty": "1"}]
    broker.state["orders"] = [{"id": "stop", "symbol": "AAPL", "type": "stop", "side": "sell",
                               "qty": "1", "filled_qty": "0.5", "status": "new",
                               "stop_price": "99"}]
    assert pilot.tick() == "FLATTENING"
    assert journal.last("halt")["reason"] == "PROTECTION_MISSING"


def _alpaca_leg(client_order_id, **overrides):
    """One Alpaca order leg. No account id; those are not part of this payload."""
    leg = {
        "id": "leg",
        "client_order_id": client_order_id,
        "created_at": "2026-10-13T14:30:05.100000Z",
        "updated_at": "2026-10-13T14:30:05.100000Z",
        "submitted_at": "2026-10-13T14:30:05.100000Z",
        "filled_at": None,
        "expired_at": None,
        "canceled_at": None,
        "failed_at": None,
        "replaced_at": None,
        "replaced_by": None,
        "replaces": None,
        "symbol": "AAPL",
        "asset_class": "us_equity",
        "notional": None,
        "qty": "1",
        "filled_qty": "0",
        "filled_avg_price": None,
        "order_class": "bracket",
        "order_type": "limit",
        "type": "limit",
        "side": "sell",
        "time_in_force": "day",
        "limit_price": "106.50",
        "stop_price": None,
        "status": "new",
        "extended_hours": False,
        "legs": None,
    }
    leg.update(overrides)
    return leg


def _fill_bracket(broker, *, stop_status="held", stop_price="99", stop_qty="1", stop_filled="0"):
    """Filled bracket whose flat open-order list contains only the take-profit."""
    submitted = broker.parent
    client_order_id = submitted["client_order_id"]
    take_profit = _alpaca_leg(client_order_id + "-tp", id="tp-leg", status="new", type="limit",
                              order_type="limit", limit_price="106.50", stop_price=None)
    stop = _alpaca_leg(
        client_order_id + "-stop", id="stop-leg", status=stop_status, type="stop",
        order_type="stop", limit_price=None, stop_price=stop_price, qty=stop_qty,
        filled_qty=stop_filled,
        canceled_at="2026-10-13T14:30:10Z" if stop_status == "canceled" else None,
        expired_at="2026-10-13T14:30:10Z" if stop_status == "expired" else None,
    )
    broker.parent = {
        "id": submitted["id"],
        "client_order_id": client_order_id,
        "created_at": "2026-10-13T14:30:01.102282Z",
        "updated_at": "2026-10-13T14:30:04.880000Z",
        "submitted_at": "2026-10-13T14:30:01.098000Z",
        "filled_at": "2026-10-13T14:30:04.880000Z",
        "expired_at": None,
        "canceled_at": None,
        "failed_at": None,
        "replaced_at": None,
        "replaced_by": None,
        "replaces": None,
        "symbol": submitted["symbol"],
        "asset_class": "us_equity",
        "notional": None,
        "qty": submitted["qty"],
        "filled_qty": "1",
        "filled_avg_price": "101.5",
        "order_class": "bracket",
        "order_type": "limit",
        "type": "limit",
        "side": submitted["side"],
        "time_in_force": "day",
        "limit_price": "101.50",
        "stop_price": None,
        "status": "filled",
        "extended_hours": False,
        "legs": [take_profit, stop],
    }
    # What GET /v2/orders?status=open&nested=false returns: the held stop is absent.
    broker.state["orders"] = [take_profit]
    broker.state["positions"] = [{
        "symbol": "AAPL", "exchange": "NASDAQ", "asset_class": "us_equity",
        "avg_entry_price": "101.5", "qty": "1", "side": "long",
        "market_value": "101.5", "cost_basis": "101.5", "current_price": "101.5",
        "lastday_price": "100", "change_today": "0.015",
    }]
    return stop


@pytest.mark.parametrize("stop_status", ["held", "new", "accepted", "pending_new"])
def test_held_bracket_stop_protects_when_open_orders_omit_it(setup, stop_status):
    pilot, broker, _, journal = setup
    pilot.tick()
    _fill_bracket(broker, stop_status=stop_status)
    assert [order["id"] for order in broker.state["orders"]] == ["tp-leg"]
    assert "account_id" not in broker.parent
    before = len(broker.calls)
    assert pilot.tick() == "POSITION_OPEN"
    assert journal.last("halt") is None
    assert not any(method == "DELETE" for method, _, _ in broker.calls[before:])


@pytest.mark.parametrize("stop_status", ["canceled", "rejected", "expired"])
def test_dead_bracket_stop_leg_halts_protection_missing(setup, stop_status):
    pilot, broker, _, journal = setup
    pilot.tick()
    _fill_bracket(broker, stop_status=stop_status)
    assert [order["id"] for order in broker.state["orders"]] == ["tp-leg"]
    assert pilot.tick() == "FLATTENING"
    assert journal.last("halt")["reason"] == "PROTECTION_MISSING"


def test_unpriced_bracket_stop_leg_halts(setup):
    pilot, broker, _, journal = setup
    pilot.tick()
    _fill_bracket(broker, stop_status="held", stop_price=None)
    assert pilot.tick() == "FLATTENING"
    assert journal.last("halt")["reason"] == "PROTECTION_MISSING"


def test_filled_bracket_without_a_stop_leg_halts(setup):
    pilot, broker, _, journal = setup
    pilot.tick()
    _fill_bracket(broker)
    broker.parent["legs"] = [leg for leg in broker.parent["legs"] if leg["type"] != "stop"]
    broker.state["orders"] = [leg for leg in broker.parent["legs"] if leg["type"] == "limit"]
    assert pilot.tick() == "FLATTENING"
    assert journal.last("halt")["reason"] == "PROTECTION_MISSING"


def test_short_remaining_bracket_stop_does_not_cover_the_position(setup):
    pilot, broker, _, journal = setup
    pilot.tick()
    _fill_bracket(broker, stop_status="held", stop_qty="1", stop_filled="0.5")
    assert pilot.tick() == "FLATTENING"
    assert journal.last("halt")["reason"] == "PROTECTION_MISSING"


def test_snapshot_nests_open_orders_and_keeps_working_legs():
    urls = []

    def transport(method, url, headers, payload=None, **kwargs):
        urls.append(url)
        if url.endswith("/v2/clock"):
            return {"timestamp": NOW.isoformat(), "is_open": True}
        if url.endswith("/v2/account"):
            return {"id": "paper-account", "status": "ACTIVE"}
        if url.endswith("/v2/positions"):
            return []
        if "/v2/orders?" in url:
            return [{
                "id": "parent-1",
                "client_order_id": "athp-bracket",
                "symbol": "AAPL",
                "asset_class": "us_equity",
                "qty": "1",
                "filled_qty": "1",
                "type": "limit",
                "order_type": "limit",
                "side": "buy",
                "order_class": "bracket",
                "time_in_force": "day",
                "limit_price": "101.50",
                "status": "filled",
                "extended_hours": False,
                "legs": [
                    _alpaca_leg("athp-bracket-tp", id="tp-leg"),
                    _alpaca_leg("athp-bracket-stop", id="stop-leg", type="stop", order_type="stop",
                                limit_price=None, stop_price="99", status="held"),
                ],
            }]
        raise AssertionError(url)

    broker = LivePaperAPI("key", "secret", transport=transport)
    snap = broker.snapshot()
    assert any("status=open" in url and "nested=true" in url for url in urls)
    assert [order["id"] for order in snap["orders"]] == ["tp-leg", "stop-leg"]
    assert all("account_id" not in order for order in snap["orders"])


def test_flatten_cancels_the_open_parent_and_not_each_leg(setup):
    pilot, broker, _, journal = setup
    pilot.tick()
    stop = _alpaca_leg("athp-stop", id="stop-leg", type="stop", order_type="stop",
                       limit_price=None, stop_price="99", status="held")
    take = _alpaca_leg("athp-tp", id="tp-leg", status="held")
    broker.parent["legs"] = [take, stop]
    broker.state["orders"] = [copy.deepcopy(broker.parent), take, stop]
    broker.state["clock"]["timestamp"] = NOW.replace(hour=19, minute=46).isoformat()
    assert pilot.tick() == "FLATTENING"
    deletes = [path for method, path, _ in broker.calls if method == "DELETE"]
    assert deletes == ["/v2/orders/" + broker.parent["id"]]
    assert journal.last("halt")["reason"] == "SESSION_CLOSE"


def test_halt_survives_cleanup_failure(setup):
    pilot, broker, _, journal = setup
    pilot.tick()
    pilot.halt("OPERATOR_STOP")
    original = broker.call

    def broken(method, path, payload=None):
        if method == "DELETE":
            raise ModelError("network down")
        return original(method, path, payload)

    broker.call = broken
    with pytest.raises(ModelError):
        pilot.tick()
    assert journal.last("halt")["reason"] == "OPERATOR_STOP"
    assert not journal.last("flat_confirmed")


def test_no_duplicate_on_next_tick_after_complete(setup):
    pilot, broker, _, journal = setup
    pilot.tick()
    broker.parent.update(status="canceled")
    broker.state["orders"] = []
    assert pilot.tick() == "FLATTENING"
    assert pilot.tick() == "COMPLETE"
    assert pilot.tick() == "COMPLETE"
    assert sum(m == "POST" for m, _, _ in broker.calls) == 1


@pytest.mark.parametrize("status_code", [404, 422])
def test_finished_leg_delete_is_success_during_flatten(setup, status_code):
    pilot, broker, _, journal = setup
    pilot.tick()
    broker.state["orders"] = [{
        "id": "stop-leg", "symbol": "AAPL", "type": "stop", "side": "sell",
        "qty": "1", "filled_qty": "0", "status": "held", "stop_price": "99",
    }]
    broker.state["clock"]["timestamp"] = NOW.replace(hour=19, minute=46).isoformat()
    original = broker.call

    def call(method, path, payload=None):
        if method == "DELETE" and path.endswith("/stop-leg"):
            raise ModelError(f"HTTP {status_code}", status=status_code)
        return original(method, path, payload)

    broker.call = call
    assert pilot.tick() == "FLATTENING"
    assert journal.last("halt")["reason"] == "SESSION_CLOSE"
    finished = journal.last("cancel_already_finished")
    assert finished["order_id"] == "stop-leg" and finished["status"] == status_code
    assert not journal.last("flat_confirmed")


def test_delete_server_error_still_fails_flatten(setup):
    pilot, broker, _, journal = setup
    pilot.tick()
    broker.state["orders"] = [{
        "id": "stop-leg", "symbol": "AAPL", "type": "stop", "side": "sell",
        "qty": "1", "filled_qty": "0", "status": "new", "stop_price": "99",
    }]
    broker.state["clock"]["timestamp"] = NOW.replace(hour=19, minute=46).isoformat()
    original = broker.call

    def call(method, path, payload=None):
        if method == "DELETE":
            raise ModelError("HTTP 500", status=500)
        return original(method, path, payload)

    broker.call = call
    with pytest.raises(ModelError):
        pilot.tick()
    assert journal.last("cancel_already_finished") is None
    assert journal.last("halt")["reason"] == "SESSION_CLOSE"


@pytest.mark.parametrize("leg_type,expected", [
    ("limit", "TAKE_PROFIT_FILLED"),
    ("stop", "STOP_FILLED"),
])
def test_bracket_fill_keeps_position_exited_and_journals_the_leg(setup, leg_type, expected):
    pilot, broker, _, journal = setup
    pilot.tick()
    _fill_bracket(broker)
    broker.state["positions"] = []
    for leg in broker.parent["legs"]:
        if leg["type"] == leg_type:
            leg.update(status="filled", filled_qty="1")
        else:
            leg.update(status="canceled")
    assert pilot.tick() == "FLATTENING"
    assert journal.last("halt")["reason"] == "POSITION_EXITED"
    assert journal.last("bracket_exit")["reason"] == expected


def test_flat_confirmation_reads_nested_order_history(setup):
    pilot, broker, _, journal = setup
    pilot.tick()
    broker.parent.update(status="canceled")
    broker.state["orders"] = []
    assert pilot.tick() == "FLATTENING"
    assert pilot.tick() == "COMPLETE"
    history = [path for _method, path, _payload in broker.calls if "nested=" in path]
    assert history and "nested=true" in history[-1]
    assert isinstance(journal.last("flat_confirmed")["order_history"], list)


@pytest.mark.parametrize("choice,confidence,accepted", [
    ("TAKE_TRADE", .9, True), ("TAKE_TRADE", .1, False),
    ("INSUFFICIENT_EVIDENCE", .9, False), ("NO_TRADE", .9, False),
])
def test_jev_gates_and_exact_http_contract(choice, confidence, accepted):
    calls = []

    def transport(method, endpoint, headers, payload, *, timeout):
        calls.append((method, endpoint, payload, timeout))
        return response(choice, confidence)

    judge = JevDecisionEngine("fixture-key", transport=transport)
    result = judge.decide({"candidate_direction": "LONG", "observations": {"breakout": "above"}})
    assert result.accepted is accepted
    assert result.receipt["execution_authorized"] is False
    assert calls[0][0:2] == ("POST", JEV_ENDPOINT)
    assert calls[0][2]["model"] == JEV_MODEL
    assert calls[0][3] == 4
    assert "fixture-key" not in result.receipt_json
    receipt = result.receipt
    receipt["accepted"] = not accepted
    assert result.receipt["accepted"] is accepted  # immutable detached receipt


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(model="jev-latest"),
    lambda r: r["answers"].pop("entry_decision"),
    lambda r: r["answers"]["entry_decision"].update(type="noul"),
    lambda r: r["answers"]["entry_decision"].update(choice="NO_TRADE"),
    lambda r: r["answers"]["entry_decision"].update(confidence=float("nan")),
    lambda r: r["answers"]["entry_decision"].update(confidence=True),
    lambda r: r["answers"]["entry_decision"]["probabilities"].update(TAKE_TRADE=1.5),
    lambda r: r["answers"]["entry_decision"]["probabilities"].update(TAKE_TRADE=.5),
    lambda r: r["answers"]["entry_decision"]["probabilities"].update(other=0),
    lambda r: r["usage"].update(input_tokens=-1),
])
def test_invalid_jev_response_is_never_approval(mutate):
    raw = response()
    mutate(raw)
    judge = JevDecisionEngine("fixture-key", transport=lambda *a, **k: raw)
    with pytest.raises(ModelError):
        judge.decide({"candidate_direction": "LONG", "observations": {}})


def test_current_data_ignores_incomplete_bar_and_excludes_today_daily():
    minute, daily = market_bars()
    expected = signal_packet(minute, daily, now=NOW, session_open=OPEN, policy=POLICY)
    minute.append({**minute[-1], "t": NOW.replace(second=0).isoformat(), "c": 999, "h": 999})
    daily.append({**daily[-1], "t": OPEN.isoformat(), "h": 999})
    actual = signal_packet(minute, daily, now=NOW, session_open=OPEN, policy=POLICY)
    assert actual == expected


@pytest.mark.parametrize("change", [
    lambda bars: bars.append(copy.deepcopy(bars[0])),
    lambda bars: bars[-1].update(c=float("nan")),
])
def test_invalid_bar_input_blocks_signal(change):
    minute, daily = market_bars()
    change(minute)
    with pytest.raises(ValueError):
        signal_packet(minute, daily, now=NOW, session_open=OPEN, policy=POLICY)


def test_stale_bar_is_not_replayed_as_current_signal():
    minute, daily = market_bars()
    with pytest.raises(DataDeferral, match="STALE_BAR"):
        signal_packet(minute, daily, now=NOW + timedelta(minutes=3), session_open=OPEN, policy=POLICY)


def test_stale_bar_waits_without_halt_or_order(setup):
    pilot, broker, _, journal = setup
    broker.state["clock"]["timestamp"] = (NOW + timedelta(minutes=3)).isoformat()
    assert pilot.tick() == "STALE_BAR"
    assert pilot.tick() == "STALE_BAR"
    assert not journal.last("halt")
    assert not journal.last("entry_intent")
    assert not any(method == "POST" for method, _, _ in broker.calls)


def test_missing_opening_minute_waits_without_halt_or_order(setup):
    pilot, broker, _, journal = setup
    minute, daily = market_bars()
    gapped = [bar for index, bar in enumerate(minute) if index != 4]

    def bars(symbol, start, end, timeframe, feed):
        return gapped if timeframe == "1Min" else daily

    broker.bars = bars
    assert pilot.tick() == "OPENING_RANGE_INCOMPLETE"
    assert pilot.tick() == "OPENING_RANGE_INCOMPLETE"
    assert not journal.last("halt")
    assert not journal.last("entry_intent")
    assert not any(method == "POST" for method, _, _ in broker.calls)


def test_daily_loss_still_halts_without_an_order(setup):
    pilot, broker, actor, journal = setup
    actor.after = lambda: broker.state["account"].update(equity="99000")
    assert pilot.tick() == "COMPLETE"
    assert journal.last("halt")["reason"] == "DAILY_LOSS_LIMIT"
    assert not journal.last("entry_intent")
    assert not any(method == "POST" for method, _, _ in broker.calls)


def _posts(broker):
    return sum(method == "POST" for method, _, _ in broker.calls)


def test_two_flat_404s_end_a_never_created_order_without_resubmit(setup):
    pilot, broker, _, journal = setup
    broker.reject_submit = True
    broker.hide_order = True
    with pytest.raises(ModelError, match="HTTP 422"):
        pilot.tick()
    assert journal.last("entry_intent")
    assert not journal.last("entry_ack")
    assert _posts(broker) == 1
    assert pilot.tick() == "ORDER_NOT_FOUND_RECHECK"
    assert journal.last("order_lookup_miss")["reason"] == "BROKER_ORDER_NOT_FOUND"
    assert not journal.last("entry_not_created")
    assert pilot.tick() == "ENTRY_NOT_CREATED"
    assert journal.last("entry_not_created")["reason"] == "BROKER_ORDER_NOT_FOUND"
    reserved = journal.last("entry_intent")["order"]["client_order_id"]
    assert journal.last("entry_not_created")["client_order_id"] == reserved
    again = ActivePaperPilot(broker, pilot.jev, journal, POLICY)
    assert again.tick() == "ENTRY_NOT_CREATED"
    assert _posts(broker) == 1
    assert not journal.last("flat_confirmed")


def test_404_with_a_position_stays_unresolved_and_does_not_resubmit(setup):
    pilot, broker, _, journal = setup
    broker.reject_submit = True
    broker.hide_order = True
    with pytest.raises(ModelError, match="HTTP 422"):
        pilot.tick()
    broker.state["positions"] = [{"symbol": "AAPL", "qty": "1"}]
    with pytest.raises(ValueError, match="exposure remains"):
        pilot.tick()
    assert not journal.last("entry_not_created")
    assert _posts(broker) == 1


def test_acknowledged_order_404_is_not_dropped_or_resent(setup):
    pilot, broker, _, journal = setup
    assert pilot.tick() == "ENTRY_SUBMITTED"
    broker.hide_order = True
    broker.state["orders"] = []
    with pytest.raises(ValueError, match="acknowledged entry disappeared"):
        pilot.tick()
    assert journal.last("entry_ack")
    assert not journal.last("entry_not_created")
    assert _posts(broker) == 1


def test_journal_detects_edits_and_enforces_single_writer(tmp_path):
    path = tmp_path / "paper.sqlite"
    journal = PaperJournal(path)
    journal.append("halt", reason="test")
    with pytest.raises(ValueError, match="another paper runner"):
        PaperJournal(path)
    journal.close()
    db = sqlite3.connect(path)
    db.execute("UPDATE events SET payload=? WHERE seq=1", ('{"kind":"approved"}',))
    db.commit()
    db.close()
    with pytest.raises(ValueError, match="integrity"):
        PaperJournal(path)


def test_broker_requests_pinned_endpoints_and_paginates_data():
    calls = []

    def transport(method, url, headers, payload=None, **kwargs):
        calls.append(url)
        if "data.alpaca.markets" in url:
            return {"bars": {"AAPL": [{"t": len(calls)}]},
                    "next_page_token": "page2" if "page_token" not in url else None}
        return {}

    broker = LivePaperAPI("key", "secret", transport=transport)
    broker.call("POST", "/v2/orders", {"symbol": "AAPL"})
    assert len(broker.bars("AAPL", OPEN, NOW, "1Min", "iex")) == 2
    assert calls[0] == "https://paper-api.alpaca.markets/v2/orders"
    assert "feed=iex" in calls[1] and "page_token=page2" in calls[2]


def test_broker_reads_retry_transient_failures_and_posts_do_not(monkeypatch):
    sleeps = []
    monkeypatch.setattr("athena_trading.paper.live.time.sleep", lambda delay: sleeps.append(delay))
    calls = []

    def transport(method, url, headers, payload=None, **kwargs):
        calls.append((method, url))
        if method == "POST":
            raise ModelError("HTTP 503", status=503)
        if sum(item[0] == "GET" for item in calls) < 3:
            raise ModelError("HTTP 429", status=429)
        return {"ok": True}

    broker = LivePaperAPI("key", "secret", transport=transport)
    with pytest.raises(ModelError) as post_error:
        broker.call("POST", "/v2/orders", {"symbol": "AAPL", "qty": "1"})
    assert post_error.value.status == 503
    assert [method for method, _ in calls] == ["POST"]
    assert broker.call("GET", "/v2/clock") == {"ok": True}
    assert [method for method, _ in calls] == ["POST", "GET", "GET", "GET"]
    assert len(sleeps) == 2
    assert all(0.25 <= delay <= 1.0 for delay in sleeps)


@pytest.mark.parametrize("failure", [
    ModelError("request failed: TimeoutError"),
    ModelError("HTTP 500", status=500),
])
def test_broker_get_retries_timeouts_and_server_errors(monkeypatch, failure):
    monkeypatch.setattr("athena_trading.paper.live.time.sleep", lambda *_args: None)
    calls = {"n": 0}

    def transport(method, url, headers, payload=None, **kwargs):
        assert method == "GET" and kwargs.get("timeout") == 5
        calls["n"] += 1
        if calls["n"] == 1:
            raise failure
        return {"bars": {"AAPL": [{"t": "one"}]}}

    broker = LivePaperAPI("key", "secret", transport=transport)
    assert broker.bars("AAPL", OPEN, NOW, "1Min", "iex") == [{"t": "one"}]
    assert calls["n"] == 2


def test_broker_get_does_not_retry_a_client_error(monkeypatch):
    monkeypatch.setattr("athena_trading.paper.live.time.sleep", lambda *_args: None)
    calls = []

    def transport(method, url, headers, payload=None, **kwargs):
        calls.append(method)
        raise ModelError("HTTP 400", status=400)

    broker = LivePaperAPI("key", "secret", transport=transport)
    with pytest.raises(ModelError):
        broker.call("GET", "/v2/account")
    assert calls == ["GET"]


def test_request_json_names_a_timeout(monkeypatch):
    class Opener:
        def open(self, request, timeout):
            raise URLError(TimeoutError("timed out"))

    monkeypatch.setattr("athena_trading.athena_adapter.jev.build_opener", lambda *_args: Opener())
    with pytest.raises(ModelError) as error:
        request_json("GET", "https://paper-api.alpaca.markets/v2/clock", {})
    assert str(error.value) == "request failed: TimeoutError"
    assert error.value.status is None


def test_http_errors_never_echo_provider_body_or_secret(monkeypatch):
    class Opener:
        def open(self, request, timeout):
            raise HTTPError(request.full_url, 401, "sensitive-key", {}, None)

    monkeypatch.setattr("athena_trading.athena_adapter.jev.build_opener", lambda *a: Opener())
    with pytest.raises(ModelError) as error:
        request_json("GET", JEV_ENDPOINT, {"Authorization": "Bearer sensitive-key"})
    assert str(error.value) == "HTTP 401"


def test_restart_can_exit_without_either_model(setup):
    pilot, broker, _, journal = setup
    pilot.tick()
    recovered = ActivePaperPilot(broker, None, journal, POLICY)
    broker.state["clock"]["timestamp"] = NOW.replace(hour=19, minute=46).isoformat()
    assert recovered.tick() == "FLATTENING"
    assert journal.last("halt")["reason"] == "SESSION_CLOSE"
    assert any(m == "DELETE" for m, _, _ in broker.calls)


def test_rejected_entry_never_becomes_position(setup):
    pilot, broker, _, journal = setup
    pilot.tick()
    broker.parent.update(status="rejected")
    broker.state["orders"] = []
    assert pilot.tick() == "FLATTENING"
    assert pilot.tick() == "COMPLETE"
    assert not broker.state["positions"]
    assert journal.last("halt")["reason"] == "ENTRY_TERMINATED"


def test_close_partial_fill_does_not_trigger_second_close(setup):
    pilot, broker, _, journal = setup
    pilot.tick()
    broker.parent.update(status="filled", filled_qty="1")
    broker.state.update(orders=[], positions=[{"symbol": "AAPL", "qty": "1"}])
    pilot.halt("OPERATOR_STOP")
    assert pilot.tick() == "FLATTENING"
    broker.state["orders"][0].update(status="partially_filled", filled_qty="0.5")
    broker.state["positions"][0]["qty"] = "0.5"
    assert pilot.tick() == "FLATTENING"
    assert sum(p.startswith("/v2/positions/") for _, p, _ in broker.calls) == 1
    assert not journal.last("flat_confirmed")


def test_corrupt_recovered_order_never_causes_resubmission(setup):
    pilot, broker, _, _ = setup
    pilot.tick()
    broker.parent["symbol"] = "MSFT"
    with pytest.raises(ValueError, match="reserved entry"):
        pilot.tick()
    assert sum(m == "POST" for m, _, _ in broker.calls) == 1


def test_prior_daily_data_must_include_previous_broker_session(setup):
    pilot, broker, _, journal = setup
    pilot.daily = market_bars()[1][:-1]
    with pytest.raises(ValueError, match="daily data is stale"):
        pilot.tick()
    assert not journal.last("decision_started")


def test_client_order_id_changes_with_session_date(tmp_path):
    ids = []
    for offset in (0, 1):
        journal = PaperJournal(tmp_path / f"day-{offset}.sqlite")
        broker = Broker()
        broker.journal = journal
        shifted_now = NOW + timedelta(days=offset)
        broker.state["clock"]["timestamp"] = shifted_now.isoformat()
        broker.state["clock"]["next_close"] = shifted_now.replace(hour=20).isoformat()
        original_call = broker.call

        def call(method, path, payload=None, *, day_offset=offset, original=original_call):
            if path.startswith("/v2/calendar"):
                return [{"date": (NOW + timedelta(days=day_offset - i)).date().isoformat(),
                         "open": "09:30", "close": "16:00"} for i in (1, 0)]
            return original(method, path, payload)

        def bars(symbol, start, end, timeframe, feed, *, day_offset=offset):
            values = market_bars()[0 if timeframe == "1Min" else 1]
            for item in values:
                item["t"] = (datetime.fromisoformat(item["t"]) + timedelta(days=day_offset)).isoformat()
            return values

        broker.call, broker.bars = call, bars
        jev = JevDecisionEngine("fixture", transport=lambda *a, **k: response())
        pilot = ActivePaperPilot(broker, jev, journal, POLICY)
        assert pilot.tick() == "ENTRY_SUBMITTED"
        ids.append(journal.last("entry_intent")["order"]["client_order_id"])
        journal.close()
    assert ids[0] != ids[1]


def test_short_candidate_has_correct_bracket_direction():
    minute, daily = market_bars()
    minute[-1].update(o=99.5, h=99.8, l=98.2, c=98.5)
    packet, order = signal_packet(minute, daily, now=NOW, session_open=OPEN, policy=POLICY)
    assert packet["candidate_direction"] == "SHORT"
    assert order["side"] == "sell"
    assert float(order["take_profit"]["limit_price"]) < float(order["limit_price"]) < float(order["stop_loss"]["stop_price"])


def _runner():
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_athena_paper.py"
    spec = importlib.util.spec_from_file_location("run_athena_paper_resilience", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _flat_snapshot():
    return {"positions": [], "orders": [], "clock": {"is_open": True}, "account": {}}


def test_typesafe_startup_failure_keeps_a_flat_day_runnable(tmp_path, monkeypatch):
    script = _runner()
    day = date(2026, 9, 24)
    journal_path = tmp_path / f"{day.isoformat()}.sqlite"
    monkeypatch.setenv("ALPACA_API_KEY", "paper-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "paper-secret")
    monkeypatch.setenv("TYPESAFE_API_KEY", "model-key")

    class FlatBroker:
        def snapshot(self):
            return _flat_snapshot()

    def unavailable(*args, **kwargs):
        raise ModelError("HTTP 503", status=503)

    monkeypatch.setattr(script.LivePaperAPI, "from_env", lambda: FlatBroker())
    monkeypatch.setattr(script, "request_json", unavailable)
    monkeypatch.setattr(script.time, "sleep", lambda *_args: None)
    code = script.main([
        "--symbol", "AAPL", "--authority", "PAPER", "--feed", "iex",
        "--journal", str(journal_path), "--run",
    ])
    assert code == 2
    journal = PaperJournal(journal_path)
    try:
        assert journal.last("halt") is None
        assert journal.last("entry_intent") is None
    finally:
        journal.close()
    task = cloud.next_session(tmp_path, day)
    assert task == cloud.SessionTask(journal_path)


def test_startup_failure_with_visible_exposure_still_halts(tmp_path, monkeypatch):
    script = _runner()
    day = date(2026, 9, 24)
    journal_path = tmp_path / f"{day.isoformat()}.sqlite"
    monkeypatch.setenv("ALPACA_API_KEY", "paper-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "paper-secret")
    monkeypatch.setenv("TYPESAFE_API_KEY", "model-key")

    class ExposedBroker:
        def snapshot(self):
            return {"positions": [{"symbol": "AAPL", "qty": "1"}], "orders": [],
                    "clock": {"is_open": True}, "account": {}}

    def unavailable(*_args, **_kwargs):
        raise ModelError("HTTP 503", status=503)

    monkeypatch.setattr(script.LivePaperAPI, "from_env", lambda: ExposedBroker())
    monkeypatch.setattr(script, "request_json", unavailable)
    monkeypatch.setattr(script.time, "sleep", lambda *_args: None)
    assert script.main([
        "--symbol", "AAPL", "--authority", "PAPER", "--journal", str(journal_path), "--run",
    ]) == 2
    journal = PaperJournal(journal_path)
    try:
        assert journal.last("halt")["reason"] == "RUNNER_ERROR"
        assert journal.last("entry_intent") is None
    finally:
        journal.close()
    assert cloud.next_session(tmp_path, day) is None


def test_failure_after_reservation_halts_and_does_not_resubmit(tmp_path, monkeypatch):
    script = _runner()
    day = date(2026, 9, 24)
    journal_path = tmp_path / f"{day.isoformat()}.sqlite"
    journal = PaperJournal(journal_path)
    journal.append("binding", binding={
        "account_id": "paper-account", "policy": asdict(POLICY),
    })
    journal.append("entry_intent", session=day.isoformat(), order={
        "client_order_id": "athp-reserved", "symbol": "AAPL", "side": "buy", "qty": "1",
    })
    journal.close()
    calls = []

    class Broker:
        def snapshot(self):
            return {"positions": [], "orders": [], "account": {"id": "paper-account"},
                    "clock": {"timestamp": NOW.isoformat(), "is_open": True,
                              "next_close": NOW.replace(hour=20).isoformat()}}

        def call(self, method, path, payload=None):
            calls.append(method)
            raise ModelError("HTTP 404", status=404)

    monkeypatch.setenv("ALPACA_API_KEY", "paper-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "paper-secret")
    monkeypatch.setenv("TYPESAFE_API_KEY", "model-key")
    monkeypatch.setattr(script.LivePaperAPI, "from_env", lambda: Broker())
    def fail_tick(self):
        raise RuntimeError("broker down during recovery")

    clock = {"now": 0}

    def monotonic():
        clock["now"] += 1_000
        return clock["now"]

    monkeypatch.setattr(script.ActivePaperPilot, "tick", fail_tick)
    monkeypatch.setattr(script.time, "sleep", lambda *_args: None)
    monkeypatch.setattr(script.time, "monotonic", monotonic)
    assert script.main([
        "--symbol", "AAPL", "--authority", "PAPER", "--journal", str(journal_path), "--run",
    ]) == 2
    journal = PaperJournal(journal_path)
    try:
        assert journal.last("halt")["reason"] == "RUNNER_ERROR"
        assert not journal.last("entry_not_created")
    finally:
        journal.close()
    assert "POST" not in calls
    task = cloud.next_session(tmp_path, day)
    assert task.recovery and task.path == journal_path


def test_one_transient_tick_does_not_halt_or_flatten_an_open_trade(tmp_path, monkeypatch, capsys):
    script = _runner()
    day = date(2026, 9, 24)
    journal_path = tmp_path / f"{day.isoformat()}.sqlite"
    journal = PaperJournal(journal_path)
    journal.append("binding", binding={"account_id": "paper-account", "policy": asdict(POLICY)})
    journal.append("entry_intent", session=day.isoformat(), order={
        "client_order_id": "athp-open", "symbol": "AAPL", "side": "buy", "qty": "1",
    })
    journal.close()
    flatten_halts = []

    class Broker:
        def snapshot(self):
            return {"positions": [{"symbol": "AAPL", "qty": "1"}], "orders": [],
                    "account": {"id": "paper-account"},
                    "clock": {"timestamp": NOW.isoformat(), "is_open": True,
                              "next_close": NOW.replace(hour=20).isoformat()}}

        def call(self, method, path, payload=None):
            raise ModelError("HTTP 404", status=404)

    ticks = {"n": 0}

    def tick(self):
        ticks["n"] += 1
        if ticks["n"] == 1:
            raise ModelError("request failed: TimeoutError")
        raise SystemExit

    def flatten_step(self, snapshot):
        flatten_halts.append(None if self.journal.last("halt") is None else self.journal.last("halt")["reason"])
        return True

    monkeypatch.setenv("ALPACA_API_KEY", "paper-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "paper-secret")
    monkeypatch.setenv("TYPESAFE_API_KEY", "model-key")
    monkeypatch.setattr(script.LivePaperAPI, "from_env", lambda: Broker())
    monkeypatch.setattr(script.ActivePaperPilot, "tick", tick)
    monkeypatch.setattr(script.ActivePaperPilot, "flatten_step", flatten_step)
    monkeypatch.setattr(script.time, "sleep", lambda *_args: None)
    with pytest.raises(SystemExit):
        script.main([
            "--symbol", "AAPL", "--authority", "PAPER", "--journal", str(journal_path), "--run",
        ])
    assert ticks["n"] == 2
    assert "TRANSIENT_TICK" in capsys.readouterr().err
    # Shutdown cleanup may run after the process is already leaving. The blip did not halt.
    assert flatten_halts == [None]
    journal = PaperJournal(journal_path)
    try:
        assert journal.last("halt") is None
    finally:
        journal.close()


@pytest.mark.parametrize("step", [1.0, 61.0])
def test_open_trade_halts_after_three_transient_ticks_or_the_time_budget(
    tmp_path, monkeypatch, step,
):
    script = _runner()
    day = date(2026, 9, 24)
    journal_path = tmp_path / f"{day.isoformat()}.sqlite"
    journal = PaperJournal(journal_path)
    journal.append("binding", binding={"account_id": "paper-account", "policy": asdict(POLICY)})
    journal.append("entry_intent", session=day.isoformat(), order={
        "client_order_id": "athp-open", "symbol": "AAPL", "side": "buy", "qty": "1",
    })
    journal.close()
    ticks = {"n": 0}

    class Broker:
        def snapshot(self):
            return {"positions": [{"symbol": "AAPL", "qty": "1"}], "orders": [],
                    "account": {"id": "paper-account"},
                    "clock": {"timestamp": NOW.isoformat(), "is_open": True,
                              "next_close": NOW.replace(hour=20).isoformat()}}

        def call(self, method, path, payload=None):
            raise ModelError("HTTP 404", status=404)

    def tick(self):
        ticks["n"] += 1
        raise ModelError("HTTP 503", status=503)

    clock = {"now": 0.0}

    def monotonic():
        clock["now"] += step
        return clock["now"]

    monkeypatch.setenv("ALPACA_API_KEY", "paper-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "paper-secret")
    monkeypatch.setenv("TYPESAFE_API_KEY", "model-key")
    monkeypatch.setattr(script.LivePaperAPI, "from_env", lambda: Broker())
    monkeypatch.setattr(script.ActivePaperPilot, "tick", tick)
    monkeypatch.setattr(script.time, "sleep", lambda *_args: None)
    monkeypatch.setattr(script.time, "monotonic", monotonic)
    assert script.main([
        "--symbol", "AAPL", "--authority", "PAPER", "--journal", str(journal_path), "--run",
    ]) == 2
    journal = PaperJournal(journal_path)
    try:
        assert journal.last("halt")["reason"] == "RUNNER_ERROR"
    finally:
        journal.close()
    assert ticks["n"] == (2 if step >= script.TRANSIENT_TICK_BUDGET_SECONDS else script.TRANSIENT_TICK_LIMIT)


def test_jev_thresholds_default_and_read_environment(monkeypatch, tmp_path):
    policy = PilotPolicy("SPY")
    assert (policy.support_min, policy.confidence_min, policy.fallback_after_open_minutes) == (0.6, 0.5, 120)
    packet = {"candidate_direction": "LONG", "observations": {}}

    def accepted(take, confidence, **overrides):
        engine = JevDecisionEngine(
            "fixture-key", transport=lambda *args, **kwargs: scored_response(take, confidence),
            **overrides,
        )
        return engine.decide(packet).accepted

    # Reported best on 2026-10-12. No bar or adjudication fixture for that session is in the repo.
    assert accepted(0.74, 0.61) is True
    assert accepted(0.74, 0.61, support_min=0.8, confidence_min=0.6) is False
    assert accepted(0.6, 0.5) is True
    assert accepted(0.59, 0.5) is False
    assert accepted(0.6, 0.49) is False

    monkeypatch.setenv("ATHENA_JEV_MIN_PTAKE", "0.74")
    monkeypatch.setenv("ATHENA_JEV_MIN_CONFIDENCE", "0.61")
    monkeypatch.setenv("ATHENA_FALLBACK_AFTER_OPEN_MINUTES", "90")
    loaded = policy_from_environment("SPY", "iex")
    assert (loaded.support_min, loaded.confidence_min, loaded.fallback_after_open_minutes) == (0.74, 0.61, 90)
    monkeypatch.setenv("ATHENA_JEV_MIN_PTAKE", "nope")
    with pytest.raises(ValueError, match="ATHENA_JEV_MIN_PTAKE"):
        policy_from_environment("SPY")
    monkeypatch.setenv("ATHENA_JEV_MIN_PTAKE", "0.6")
    monkeypatch.setenv("ATHENA_FALLBACK_AFTER_OPEN_MINUTES", "0")
    with pytest.raises(ValueError, match="fallback cutoff"):
        policy_from_environment("SPY")

    script = _runner()
    seen = {}
    monkeypatch.setenv("ALPACA_API_KEY", "paper-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "paper-secret")
    monkeypatch.setenv("TYPESAFE_API_KEY", "model-key")
    monkeypatch.setenv("ATHENA_JEV_MIN_PTAKE", "0.62")
    monkeypatch.setenv("ATHENA_JEV_MIN_CONFIDENCE", "0.51")
    monkeypatch.delenv("ATHENA_FALLBACK_AFTER_OPEN_MINUTES", raising=False)

    class FlatBroker:
        def snapshot(self):
            return _flat_snapshot()

    def capture(api_key, *, support_min, confidence_min):
        seen["support_min"] = support_min
        seen["confidence_min"] = confidence_min
        return object()

    monkeypatch.setattr(script.LivePaperAPI, "from_env", lambda: FlatBroker())
    monkeypatch.setattr(script, "JevDecisionEngine", capture)
    monkeypatch.setattr(script, "request_json", lambda *args, **kwargs: {"models": ["jev-1.13.0"]})
    assert script.main([
        "--symbol", "SPY", "--authority", "PAPER", "--feed", "iex",
        "--journal", str(tmp_path / "preflight.sqlite"), "--preflight",
    ]) == 0
    assert seen == {"support_min": 0.62, "confidence_min": 0.51}


def _fallback_pilot(tmp_path, transport, policy, minute=None):
    journal = PaperJournal(tmp_path / "paper.sqlite")
    broker = Broker()
    broker.journal = journal
    if minute is not None:
        daily = market_bars()[1]

        def bars(symbol, start, end, timeframe, feed):
            return minute if timeframe == "1Min" else daily

        broker.bars = bars
    pilot = ActivePaperPilot(
        broker, JevDecisionEngine("fixture-key", transport=transport), journal, policy,
    )
    return pilot, broker, journal


def test_stale_fallback_does_not_submit_a_remembered_take(tmp_path):
    minute, _daily = market_bars()
    planned = [(0.55, 0.90), (0.59, 0.85)]
    calls = {"n": 0}

    def transport(*args, **kwargs):
        take, confidence = planned[calls["n"]]
        calls["n"] += 1
        return scored_response(take, confidence)

    policy = PilotPolicy("AAPL", fallback_after_open_minutes=30)
    pilot, broker, journal = _fallback_pilot(tmp_path, transport, policy, minute)
    assert pilot.tick() == "JEV_VETO"
    minute.append({
        "t": (OPEN + timedelta(minutes=16)).isoformat(),
        "o": 101.6, "h": 102.4, "l": 101.4, "c": 102.2, "v": 1000,
    })
    broker.state["clock"]["timestamp"] = (OPEN + timedelta(minutes=17, seconds=5)).isoformat()
    assert pilot.tick() == "JEV_VETO"
    broker.state["clock"]["timestamp"] = (OPEN + timedelta(minutes=31)).isoformat()
    assert pilot.tick() == "FALLBACK_NO_TRADE"
    assert _posts(broker) == 0
    assert calls["n"] == 2
    assert journal.last("fallback_entry") is None
    assert journal.last("entry_intent") is None
    assert journal.last("fallback_no_trade")["reason"] == "STALE_BAR"
    remembered = [event["signal_at"] for event in journal.events if event["kind"] == "fallback_candidate"]
    assert remembered == [
        (OPEN + timedelta(minutes=15)).isoformat(),
        (OPEN + timedelta(minutes=16)).isoformat(),
    ]
    journal.close()


def test_fallback_submits_only_while_the_same_setup_is_fresh(tmp_path):
    minute, _daily = market_bars()
    policy = PilotPolicy("AAPL", fallback_after_open_minutes=17)
    pilot, broker, journal = _fallback_pilot(
        tmp_path, lambda *args, **kwargs: scored_response(0.55, 0.9), policy, minute,
    )
    assert pilot.tick() == "JEV_VETO"
    broker.state["clock"]["timestamp"] = (OPEN + timedelta(minutes=17, seconds=5)).isoformat()
    assert pilot.tick() == "ENTRY_SUBMITTED"
    assert _posts(broker) == 1
    assert journal.last("fallback_entry")["reason"] == "NO_ORDER_BY_CUTOFF"
    assert journal.last("entry_intent")["fallback"] is True
    assert journal.last("entry_intent")["order"]["limit_price"] == "101.50"
    assert journal.last("entry_intent")["order"]["qty"] == "1"
    journal.close()


def test_old_long_is_not_sent_when_the_fresh_bar_is_short(tmp_path):
    minute, _daily = market_bars()
    calls = {"n": 0}

    def transport(*args, **kwargs):
        calls["n"] += 1
        return scored_response(0.55, 0.9) if calls["n"] == 1 else response("NO_TRADE")

    policy = PilotPolicy("AAPL", fallback_after_open_minutes=30)
    pilot, broker, journal = _fallback_pilot(tmp_path, transport, policy, minute)
    assert pilot.tick() == "JEV_VETO"
    minute.append({
        "t": (OPEN + timedelta(minutes=29)).isoformat(),
        "o": 99.0, "h": 99.2, "l": 98.1, "c": 98.5, "v": 1000,
    })
    broker.state["clock"]["timestamp"] = (OPEN + timedelta(minutes=30, seconds=5)).isoformat()
    assert pilot.tick() == "JEV_VETO"
    assert calls["n"] == 2
    assert _posts(broker) == 0
    assert journal.last("entry_intent") is None
    assert journal.last("fallback_entry") is None
    skipped = journal.last("fallback_no_trade")
    assert skipped["reason"] == "DIRECTION_CHANGED"
    assert skipped["remembered_direction"] == "LONG"
    assert skipped["current_direction"] == "SHORT"
    journal.close()


def test_fallback_is_skipped_after_a_trade(tmp_path):
    minute, _daily = market_bars()
    minute.append({
        "t": (OPEN + timedelta(minutes=18)).isoformat(),
        "o": 101.6, "h": 102.4, "l": 101.4, "c": 102.2, "v": 1000,
    })
    policy = PilotPolicy("AAPL", fallback_after_open_minutes=20)
    pilot, broker, journal = _fallback_pilot(
        tmp_path, lambda *args, **kwargs: response(), policy, minute,
    )
    broker.state["clock"]["timestamp"] = (OPEN + timedelta(minutes=19, seconds=20)).isoformat()
    assert pilot.tick() == "ENTRY_SUBMITTED"
    broker.state["clock"]["timestamp"] = (OPEN + timedelta(minutes=20, seconds=10)).isoformat()
    assert pilot.tick() == "ENTRY_WORKING"
    assert journal.last("fallback_entry") is None
    assert journal.last("fallback_candidate") is None
    assert _posts(broker) == 1
    journal.close()


def test_fallback_does_not_promote_no_trade(tmp_path):
    policy = PilotPolicy("AAPL", fallback_after_open_minutes=30)
    pilot, broker, journal = _fallback_pilot(
        tmp_path, lambda *args, **kwargs: response("NO_TRADE"), policy,
    )
    assert pilot.tick() == "JEV_VETO"
    broker.state["clock"]["timestamp"] = (OPEN + timedelta(minutes=31)).isoformat()
    assert pilot.tick() == "STALE_BAR"
    assert journal.last("fallback_candidate") is None
    assert journal.last("fallback_entry") is None
    assert _posts(broker) == 0
    journal.close()


def test_equivalent_setup_keeps_a_slot_for_a_new_direction(tmp_path):
    minute, _daily = market_bars()
    calls = {"n": 0}

    def transport(*args, **kwargs):
        calls["n"] += 1
        return scored_response(0.55, 0.9)

    policy = PilotPolicy("AAPL", fallback_after_open_minutes=30, max_adjudications=1)
    pilot, broker, journal = _fallback_pilot(tmp_path, transport, policy, minute)
    assert pilot.tick() == "JEV_VETO"
    minute.append({
        "t": (OPEN + timedelta(minutes=16)).isoformat(),
        "o": 101.6, "h": 102.4, "l": 101.4, "c": 102.2, "v": 1000,
    })
    broker.state["clock"]["timestamp"] = (OPEN + timedelta(minutes=17, seconds=5)).isoformat()
    assert pilot.tick() == "JEV_VETO"
    assert calls["n"] == 2
    minute.append({
        "t": (OPEN + timedelta(minutes=17)).isoformat(),
        "o": 102.0, "h": 102.4, "l": 101.6, "c": 102.1, "v": 1000,
    })
    broker.state["clock"]["timestamp"] = (OPEN + timedelta(minutes=18, seconds=5)).isoformat()
    assert pilot.tick() == "ALREADY_REVIEWED"
    assert calls["n"] == 2
    assert journal.last("opportunity")["reason"] == "EQUIVALENT_SETUP"
    minute.append({
        "t": (OPEN + timedelta(minutes=18)).isoformat(),
        "o": 99.2, "h": 99.4, "l": 98.2, "c": 98.5, "v": 1000,
    })
    broker.state["clock"]["timestamp"] = (OPEN + timedelta(minutes=19, seconds=5)).isoformat()
    assert pilot.tick() == "ADJUDICATION_BUDGET"
    assert calls["n"] == 2
    assert journal.last("opportunity")["stage"] == "budget_limited"
    assert _posts(broker) == 0
    broker.state["clock"]["timestamp"] = (OPEN + timedelta(minutes=31)).isoformat()
    assert pilot.tick() == "FALLBACK_NO_TRADE"
    assert journal.last("fallback_entry") is None
    assert journal.last("entry_intent") is None
    assert _posts(broker) == 0
    journal.close()


def test_journaled_take_is_not_sent_when_the_bar_is_stale(tmp_path):
    minute, daily = market_bars()
    packet, _order = signal_packet(minute, daily, now=NOW, session_open=OPEN, policy=POLICY)
    engine = JevDecisionEngine(
        "fixture-key", transport=lambda *args, **kwargs: scored_response(0.55, 0.9),
    )
    verdict = engine.decide(packet)
    assert verdict.accepted is False
    journal = PaperJournal(tmp_path / "paper.sqlite")
    journal.append(
        "decision_started", session="2026-09-24", signal_at=packet["signal_at"],
        packet=packet, market_inputs={"bars": minute, "daily": daily},
    )
    journal.append("adjudication", receipt=verdict.receipt)
    broker = Broker()
    broker.journal = journal
    broker.state["clock"]["timestamp"] = (OPEN + timedelta(minutes=31)).isoformat()

    def transport(*args, **kwargs):
        raise AssertionError("fallback reuses the journaled adjudication")

    policy = PilotPolicy("AAPL", fallback_after_open_minutes=30)
    pilot = ActivePaperPilot(
        broker, JevDecisionEngine("fixture-key", transport=transport), journal, policy,
    )
    assert pilot.tick() == "FALLBACK_NO_TRADE"
    assert _posts(broker) == 0
    assert journal.last("fallback_entry") is None
    assert journal.last("entry_intent") is None
    assert journal.last("fallback_no_trade")["reason"] == "STALE_BAR"
    journal.close()


def test_saved_policy_without_fallback_field_still_resumes(tmp_path):
    saved = asdict(PilotPolicy("AAPL"))
    saved.update(support_min=0.8, confidence_min=0.6, version="athena-jev-paper-pilot-v2")
    del saved["fallback_after_open_minutes"]
    restored = PilotPolicy(**saved)
    assert (restored.support_min, restored.confidence_min) == (0.8, 0.6)
    assert restored.fallback_after_open_minutes == 120
    journal = PaperJournal(tmp_path / "paper.sqlite")
    journal.append("binding", binding={"account_id": "paper-account", "policy": saved})
    broker = Broker()
    broker.journal = journal
    pilot = ActivePaperPilot(
        broker, JevDecisionEngine("fixture-key", transport=lambda *args, **kwargs: response("NO_TRADE")),
        journal, restored,
    )
    assert pilot.tick() == "JEV_VETO"
    journal.close()


def test_fallback_and_runner_stay_paper_only(tmp_path):
    with pytest.raises(AuthorityError, match="LIVE"):
        parse_authority("LIVE")
    assert "LIVE" not in {item.value for item in ExecutionAuthority}
    policy = PilotPolicy("AAPL", fallback_after_open_minutes=30)
    pilot, broker, journal = _fallback_pilot(
        tmp_path, lambda *args, **kwargs: scored_response(0.55, 0.9), policy,
    )
    assert pilot.tick() == "JEV_VETO"
    pilot.authority = ExecutionAuthority.ABSENT
    broker.state["clock"]["timestamp"] = (OPEN + timedelta(minutes=31)).isoformat()
    with pytest.raises(AuthorityError, match="ABSENT"):
        pilot.tick()
    assert _posts(broker) == 0
    assert journal.last("entry_intent") is None
    assert journal.last("fallback_entry") is None
    journal.close()
    script = _runner()
    with pytest.raises(SystemExit) as raised:
        script.main([
            "--symbol", "AAPL", "--authority", "LIVE",
            "--journal", str(tmp_path / "live.sqlite"), "--run",
        ])
    assert raised.value.code == 2


def _mass(total, take=0.9, confidence=0.9):
    body = scored_response(take, confidence)
    rest = (total - take) / 2.0
    body["answers"]["entry_decision"]["probabilities"] = {
        "TAKE_TRADE": take,
        "NO_TRADE": rest,
        "INSUFFICIENT_EVIDENCE": rest,
    }
    return body


def _replace_probability(name, value):
    body = response()
    body["answers"]["entry_decision"]["probabilities"][name] = value
    return body


def _drop_probability_label():
    body = response()
    del body["answers"]["entry_decision"]["probabilities"]["NO_TRADE"]
    return body


@pytest.mark.parametrize("total", [0.999, 1.01])
def test_near_unit_probability_sums_pass_after_renormalizing(total):
    raw = _mass(total)
    judge = JevDecisionEngine("fixture-key", transport=lambda *args, **kwargs: raw)
    result = judge.decide({"candidate_direction": "LONG", "observations": {}})
    assert result.accepted is True
    assert result.receipt["execution_authorized"] is False
    check = result.receipt["probability_checks"]["entry_decision"]
    assert check["renormalized"] is True
    assert check["raw"]["TAKE_TRADE"] == pytest.approx(0.9)
    assert math.fsum(check["used"].values()) == 1.0
    assert check["used"]["TAKE_TRADE"] == pytest.approx(0.9 / total)
    stored = result.receipt["response"]["answers"]["entry_decision"]["probabilities"]
    assert stored["TAKE_TRADE"] == pytest.approx(0.9)


def test_gate_compares_the_renormalized_take_probability():
    raw = _mass(1.01, take=0.60, confidence=0.9)
    judge = JevDecisionEngine("fixture-key", transport=lambda *args, **kwargs: raw)
    result = judge.decide({"candidate_direction": "LONG", "observations": {}})
    check = result.receipt["probability_checks"]["entry_decision"]
    assert check["renormalized"] is True
    assert check["used"]["TAKE_TRADE"] < 0.6
    assert math.fsum(check["used"].values()) == 1.0
    assert result.accepted is False
    assert result.receipt["execution_authorized"] is False


@pytest.mark.parametrize("factory", [
    lambda: _mass(0.9, take=0.8),
    lambda: _replace_probability("TAKE_TRADE", -0.1),
    lambda: _replace_probability("TAKE_TRADE", float("nan")),
    _drop_probability_label,
])
def test_bad_probability_mass_is_never_an_approval(factory):
    raw = factory()
    judge = JevDecisionEngine("fixture-key", transport=lambda *args, **kwargs: raw)
    with pytest.raises(ModelError):
        judge.decide({"candidate_direction": "LONG", "observations": {}})


@pytest.mark.parametrize("total", [0.999, 1.01])
def test_near_unit_sum_still_submits_and_journals_raw_probabilities(setup, total):
    pilot, broker, _, journal = setup
    pilot.jev = JevDecisionEngine("fixture-key", transport=lambda *args, **kwargs: _mass(total))
    assert pilot.tick() == "ENTRY_SUBMITTED"
    kinds = [event["kind"] for event in journal.events]
    assert kinds.index("jev_response") < kinds.index("adjudication")
    raw_take = journal.last("jev_response")["response"]["answers"]["entry_decision"]["probabilities"]
    check = journal.last("adjudication")["receipt"]["probability_checks"]["entry_decision"]
    assert raw_take["TAKE_TRADE"] == pytest.approx(0.9)
    assert check["raw"]["TAKE_TRADE"] == pytest.approx(0.9)
    assert check["raw"]["NO_TRADE"] == pytest.approx((total - 0.9) / 2)
    assert check["raw"]["INSUFFICIENT_EVIDENCE"] == pytest.approx((total - 0.9) / 2)
    assert check["renormalized"] is True
    assert math.fsum(check["used"].values()) == 1.0
    assert journal.last("jev_veto") is None
    assert _posts(broker) == 1


@pytest.mark.parametrize("factory,reason,stored_take", [
    (lambda: _mass(0.9, take=0.8), "sum to one", 0.8),
    (lambda: _replace_probability("TAKE_TRADE", -0.1), "finite", -0.1),
    (lambda: _replace_probability("TAKE_TRADE", float("nan")), "finite", "NaN"),
    (_drop_probability_label, "option keys", 0.9),
])
def test_bad_jev_answer_vetoes_one_setup_and_the_runner_continues(
    setup, factory, reason, stored_take,
):
    pilot, broker, _, journal = setup
    calls = {"n": 0}

    def transport(*args, **kwargs):
        calls["n"] += 1
        return factory()

    pilot.jev = JevDecisionEngine("fixture-key", transport=transport)
    assert pilot.tick() == "JEV_VETO"
    assert pilot.tick() == "ALREADY_REVIEWED"
    assert calls["n"] == 1
    veto = journal.last("jev_veto")
    assert veto["accepted"] is False
    assert reason in veto["reason"]
    kinds = [event["kind"] for event in journal.events]
    assert kinds.index("jev_response") < kinds.index("jev_veto")
    assert "adjudication" not in kinds
    stored = journal.last("jev_response")["response"]["answers"]["entry_decision"]["probabilities"]
    if isinstance(stored_take, float):
        assert stored.get("TAKE_TRADE") == pytest.approx(stored_take)
    else:
        assert stored.get("TAKE_TRADE") == stored_take
    assert journal.last("entry_intent") is None
    assert journal.last("fallback_candidate") is None
    assert journal.last("halt") is None
    assert _posts(broker) == 0


def test_runner_keeps_going_and_a_later_take_trade_still_submits(setup):
    pilot, broker, _, journal = setup
    minute, daily = market_bars()
    calls = {"n": 0}

    def bars(symbol, start, end, timeframe, feed):
        return minute if timeframe == "1Min" else daily

    def transport(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return _mass(0.9, take=0.8)
        return response()

    broker.bars = bars
    pilot.jev = JevDecisionEngine("fixture-key", transport=transport)
    assert pilot.tick() == "JEV_VETO"
    assert journal.last("jev_veto")["accepted"] is False
    minute.append({
        "t": (OPEN + timedelta(minutes=16)).isoformat(),
        "o": 101.6, "h": 102.4, "l": 101.4, "c": 102.2, "v": 1000,
    })
    broker.state["clock"]["timestamp"] = (OPEN + timedelta(minutes=17, seconds=5)).isoformat()
    assert pilot.tick() == "ENTRY_SUBMITTED"
    assert journal.last("entry_intent")["fallback"] is False
    assert journal.last("entry_intent")["order"]["limit_price"] == "102.20"
    assert calls["n"] == 2
    assert _posts(broker) == 1
    assert journal.last("halt") is None


def test_bad_answer_does_not_block_the_daily_fallback(tmp_path):
    minute, _daily = market_bars()
    calls = {"n": 0}

    def transport(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return _mass(1.01, take=0.60, confidence=0.9)
        return _mass(0.9, take=0.8)

    policy = PilotPolicy("AAPL", fallback_after_open_minutes=30)
    pilot, broker, journal = _fallback_pilot(tmp_path, transport, policy, minute)
    assert pilot.tick() == "JEV_VETO"
    check = journal.last("adjudication")["receipt"]["probability_checks"]["entry_decision"]
    assert check["renormalized"] is True
    assert journal.last("fallback_candidate")["take_probability"] == pytest.approx(check["used"]["TAKE_TRADE"])
    assert journal.last("fallback_candidate")["signal_at"] == (OPEN + timedelta(minutes=15)).isoformat()
    minute.append({
        "t": (OPEN + timedelta(minutes=16)).isoformat(),
        "o": 101.6, "h": 102.4, "l": 101.4, "c": 102.2, "v": 1000,
    })
    broker.state["clock"]["timestamp"] = (OPEN + timedelta(minutes=17, seconds=5)).isoformat()
    assert pilot.tick() == "JEV_VETO"
    assert journal.last("jev_veto")["accepted"] is False
    assert journal.last("entry_intent") is None
    candidates = [event for event in journal.events if event["kind"] == "fallback_candidate"]
    assert [event["signal_at"] for event in candidates] == [(OPEN + timedelta(minutes=15)).isoformat()]
    broker.state["clock"]["timestamp"] = (OPEN + timedelta(minutes=31)).isoformat()
    assert pilot.tick() == "FALLBACK_NO_TRADE"
    assert journal.last("fallback_entry") is None
    assert journal.last("entry_intent") is None
    assert journal.last("fallback_no_trade")["reason"] == "STALE_BAR"
    assert journal.last("fallback_no_trade")["remembered_signal_at"] == (
        OPEN + timedelta(minutes=15)
    ).isoformat()
    assert calls["n"] == 2
    assert _posts(broker) == 0
    journal.close()


def test_earnings_prefix_does_not_block_or_get_flattened(setup):
    """An athe- order and its position are the earnings book, not unowned exposure."""
    pilot, broker, _, journal = setup
    broker.state["positions"] = [{
        "asset_id": "b0b6dd9d-8b9b-48a9-ba46-b9d54906e415",
        "symbol": "DECK", "exchange": "NASDAQ", "asset_class": "us_equity",
        "avg_entry_price": "142.15", "qty": "4", "side": "long",
        "market_value": "568.60", "cost_basis": "568.60", "current_price": "142.15",
    }]
    broker.state["orders"] = [{
        "id": "8f6c1d2e-1b3a-4c5d-9e7f-0a1b2c3d4e5f",
        "client_order_id": "athe-deckreport-stop",
        "symbol": "DECK", "asset_class": "us_equity", "qty": "4", "filled_qty": "0",
        "side": "sell", "type": "stop", "order_type": "stop", "order_class": "bracket",
        "time_in_force": "gtc", "status": "held", "stop_price": "130.00",
        "limit_price": None, "extended_hours": False, "legs": None,
    }]
    assert pilot.tick() == "ENTRY_SUBMITTED"
    assert journal.last("entry_intent")["order"]["symbol"] == "AAPL"
    broker.parent.update(status="filled", filled_qty="1")
    broker.state["positions"] = [
        {"symbol": "AAPL", "qty": "1", "side": "long"},
        {"symbol": "DECK", "qty": "4", "side": "long", "asset_class": "us_equity"},
    ]
    broker.state["orders"] = [
        {"id": "aapl-stop", "client_order_id": "athp-aapl-stop", "symbol": "AAPL",
         "qty": "1", "filled_qty": "0", "side": "sell", "type": "stop", "status": "new",
         "stop_price": "99"},
        {"id": "8f6c1d2e-1b3a-4c5d-9e7f-0a1b2c3d4e5f", "client_order_id": "athe-deckreport-stop",
         "symbol": "DECK", "qty": "4", "filled_qty": "0", "side": "sell", "type": "stop",
         "status": "held", "stop_price": "130.00"},
    ]
    broker.state["clock"]["timestamp"] = NOW.replace(hour=19, minute=46).isoformat()
    assert pilot.tick() == "FLATTENING"
    deleted = [path for method, path, _ in broker.calls if method == "DELETE"]
    assert deleted
    assert all("DECK" not in path and "8f6c1d2e" not in path for path in deleted)
    assert journal.last("halt")["reason"] == "SESSION_CLOSE"


def test_earnings_ledger_hides_a_naked_position_and_not_our_symbol(setup, monkeypatch, tmp_path):
    monkeypatch.setenv("ATHENA_EARNINGS_STATE_DIR", str(tmp_path))
    (tmp_path / "ownership.json").write_text(
        '{"arm":"earnings","prefix":"athe-","symbols":["MSFT"],'
        '"orders":[{"symbol":"MSFT","client_order_id":"athe-msft"}]}'
    )
    pilot, broker, _, journal = setup
    broker.state["positions"] = [{
        "symbol": "MSFT", "qty": "2", "side": "long", "asset_class": "us_equity",
        "avg_entry_price": "410.00", "current_price": "412.00",
    }]
    assert pilot.tick() == "ENTRY_SUBMITTED"
    assert journal.last("entry_intent")["order"]["symbol"] == "AAPL"

    fresh = PaperJournal(tmp_path / "other.sqlite")
    other = ActivePaperPilot(broker, pilot.jev, fresh, POLICY)
    broker.state["positions"] = [{"symbol": "AAPL", "qty": "1", "side": "long"}]
    broker.state["orders"] = []
    (tmp_path / "ownership.json").write_text(
        '{"arm":"earnings","prefix":"athe-","symbols":["AAPL"],"orders":[]}'
    )
    with pytest.raises(ValueError, match="dedicated"):
        other.tick()
    fresh.close()


def test_unknown_symbol_is_still_unowned(setup, monkeypatch, tmp_path):
    monkeypatch.setenv("ATHENA_EARNINGS_STATE_DIR", str(tmp_path))
    (tmp_path / "ownership.json").write_text(
        '{"arm":"earnings","prefix":"athe-","symbols":["DECK"],"orders":[]}'
    )
    pilot, broker, _, _journal = setup
    broker.state["positions"] = [{"symbol": "QQQ", "qty": "1", "side": "long"}]
    with pytest.raises(ValueError, match="dedicated"):
        pilot.tick()


def _earnings_history_rows():
    """Concurrent earnings fills that share the paper account, including a nested leg."""
    return [
        {
            "id": "deck-earn-1", "client_order_id": "athe-deck-parent", "symbol": "DECK",
            "side": "buy", "type": "limit", "status": "filled", "qty": "19",
            "filled_qty": "19", "filled_avg_price": "104.00", "order_class": "bracket",
            "legs": [{
                "id": "deck-earn-stop", "client_order_id": "athe-deck-parent-stop",
                "symbol": "DECK", "side": "sell", "type": "stop", "status": "filled",
                "qty": "19", "filled_qty": "19", "filled_avg_price": "102.00",
                "order_class": "bracket", "legs": None,
            }],
        },
        {
            "id": "deck-ledger-1", "client_order_id": "manual-deck-close", "symbol": "DECK",
            "side": "sell", "type": "market", "status": "filled", "qty": "4",
            "filled_qty": "4", "filled_avg_price": "105.00", "order_class": "simple",
            "legs": None,
        },
    ]


def _prepare_flat_history(tmp_path, monkeypatch, extra_orders):
    journal = PaperJournal(tmp_path / "2026-09-24.sqlite")
    broker, actor = Broker(), DecisionHook()
    broker.journal = journal
    pilot = ActivePaperPilot(
        broker, JevDecisionEngine("fixture-key", transport=actor.transport), journal, POLICY,
    )
    assert pilot.tick() == "ENTRY_SUBMITTED"
    _fill_bracket(broker, stop_status="canceled")
    assert pilot.tick() == "FLATTENING"
    broker.state["orders"] = []
    for leg in broker.parent["legs"]:
        leg.update(status="canceled", filled_qty="0", filled_avg_price=None)
    assert pilot.tick() == "FLATTENING"
    assert journal.last("close_ack")["order"]["id"] == "close-1"
    broker.state["positions"] = []
    broker.state["orders"] = []
    close = {
        "id": "close-1", "client_order_id": "broker-close", "symbol": "AAPL",
        "side": "sell", "type": "market", "status": "filled", "qty": "1",
        "filled_qty": "1", "filled_avg_price": "99.00", "order_class": "simple",
        "legs": None,
    }
    earnings_dir = tmp_path / "earnings-state"
    write_ownership_ledger(
        earnings_dir, {"DECK"},
        [{"symbol": "DECK", "client_order_id": "athe-deck-parent"}],
    )
    monkeypatch.setenv("ATHENA_EARNINGS_STATE_DIR", str(earnings_dir))
    original = broker.call

    def call(method, path, payload=None):
        result = original(method, path, payload)
        if isinstance(path, str) and path.startswith("/v2/orders?"):
            return [copy.deepcopy(broker.parent), close, *copy.deepcopy(extra_orders)]
        return result

    broker.call = call
    return pilot, broker, journal


def test_earnings_fills_do_not_corrupt_the_intraday_outcome(tmp_path, monkeypatch):
    pilot, _broker, journal = _prepare_flat_history(tmp_path, monkeypatch, _earnings_history_rows())
    # The generated close is attributable by exact journal-published provenance,
    # not merely because another earnings trade has this symbol in its live book.
    write_ownership_ledger(
        tmp_path / "earnings-state", {"DECK"}, [],
        historical_orders=[_earnings_history_rows()[1]], account_id="paper-account",
    )
    assert pilot.tick() == "FLATTENING"
    assert pilot.tick() == "COMPLETE"
    flat = journal.last("flat_confirmed")
    assert any(order["symbol"] == "DECK" for order in flat["account_order_history"])
    assert all(order.get("symbol") != "DECK" for order in flat["order_history"])
    parent = next(order for order in flat["order_history"] if order["id"] == "entry-1")
    assert parent["legs"]
    assert any(order["id"] == "close-1" for order in flat["order_history"])
    episode = outcome(journal, NOW + timedelta(hours=2))
    assert episode["symbol"] == "AAPL"
    assert episode["quantity"] == "1"
    assert Decimal(episode["gross_pnl"]) == Decimal("-2.50")
    journal.close()
    maintain(tmp_path, datetime(2026, 9, 25, 1, tzinfo=UTC))
    assert cloud.next_session(tmp_path, date(2026, 9, 25)) == cloud.SessionTask(
        tmp_path / "2026-09-25.sqlite",
    )


def test_unexplained_terminal_order_is_not_dropped_from_account_history(tmp_path, monkeypatch):
    pilot, _broker, journal = _prepare_flat_history(tmp_path, monkeypatch, [{
        "id": "qqq-stranger", "client_order_id": "manual-qqq", "symbol": "QQQ",
        "side": "buy", "type": "market", "status": "filled", "qty": "3",
        "filled_qty": "3", "filled_avg_price": "400.00", "order_class": "simple",
        "legs": None,
    }])
    assert pilot.tick() == "FLATTENING"
    with pytest.raises(ValueError, match="unexplained"):
        pilot.tick()
    assert journal.last("flat_confirmed") is None
    journal.close()


def _hold_empty_book(path: Path, ready: Path, release: Path) -> subprocess.Popen:
    script = """
import os, time
from pathlib import Path
from athena_trading.paper.journal import PaperJournal
journal = PaperJournal(Path(os.environ["HELD"]))
journal.append("binding", binding={"arm": "peer"})
Path(os.environ["READY"]).write_text("up")
deadline = time.time() + 30
while not Path(os.environ["RELEASE"]).exists():
    if time.time() > deadline:
        break
    time.sleep(0.02)
journal.close()
"""
    env = os.environ.copy()
    env.update(HELD=str(path), READY=str(ready), RELEASE=str(release))
    env["PYTHONPATH"] = os.pathsep.join(["src", env.get("PYTHONPATH", "")])
    return subprocess.Popen(
        [sys.executable, "-c", script],
        cwd=str(Path(__file__).resolve().parents[1]), env=env,
    )


def _wait_ready(path: Path, proc: subprocess.Popen) -> None:
    deadline = time.time() + 20
    while time.time() < deadline:
        if path.exists():
            return
        if proc.poll() is not None:
            raise AssertionError("peer exited before it was ready")
        time.sleep(0.02)
    raise AssertionError("peer did not become ready")


def test_empty_locked_earnings_book_does_not_block_intraday_entry(setup, tmp_path, monkeypatch):
    pilot, broker, _actor, journal = setup
    earnings = tmp_path / "earnings-peer"
    earnings.mkdir()
    ready, release = tmp_path / "ready", tmp_path / "release"
    proc = _hold_empty_book(earnings / "book.sqlite", ready, release)
    monkeypatch.setenv("ATHENA_EARNINGS_STATE_DIR", str(earnings))
    try:
        _wait_ready(ready, proc)
        assert pilot.tick() == "ENTRY_SUBMITTED"
        assert _posts(broker) == 1
    finally:
        release.write_text("go")
        proc.wait(timeout=20)
    journal.close()


def test_acknowledged_earnings_order_is_not_charged_against_buying_power_twice(
    setup, tmp_path, monkeypatch,
):
    """Broker buying power already reflects an acknowledged order that is in the snapshot."""
    pilot, broker, _actor, journal = setup
    root = tmp_path / "earnings-peer"
    book = PaperJournal(root / "book.sqlite")
    book.append("entry_intent", order={
        "client_order_id": "athe-deck", "symbol": "DECK", "side": "buy", "qty": "19",
        "limit_price": "100", "stop_loss": {"stop_price": "98"},
    })
    book.append("entry_ack", client_order_id="athe-deck", order={
        "id": "earn-1", "client_order_id": "athe-deck", "status": "accepted",
    })
    book.close()
    monkeypatch.setenv("ATHENA_EARNINGS_STATE_DIR", str(root))
    broker.state["account"]["buying_power"] = "500"
    broker.state["orders"] = [{
        "id": "earn-1", "client_order_id": "athe-deck", "symbol": "DECK", "side": "buy",
        "qty": "19", "filled_qty": "0", "status": "new", "type": "limit",
    }]
    assert pilot.tick() == "ENTRY_SUBMITTED"
    assert _posts(broker) == 1
    assert journal.last("opportunity")["reason"] == "ENTRY_SUBMITTED"
    journal.close()


def test_stale_snapshot_and_local_reservation_still_consume_buying_power(
    setup, tmp_path, monkeypatch,
):
    pilot, broker, _actor, journal = setup
    root = tmp_path / "earnings-peer"
    book = PaperJournal(root / "book.sqlite")
    book.append("entry_intent", order={
        "client_order_id": "athe-deck", "symbol": "DECK", "side": "buy", "qty": "19",
        "limit_price": "100", "stop_loss": {"stop_price": "98"},
    })
    book.append("entry_ack", client_order_id="athe-deck", order={
        "id": "earn-1", "client_order_id": "athe-deck", "status": "accepted",
    })
    book.append("entry_intent", order={
        "client_order_id": "athe-msft", "symbol": "MSFT", "side": "buy", "qty": "70",
        "limit_price": "100", "stop_loss": {"stop_price": "98"},
    })
    book.close()
    monkeypatch.setenv("ATHENA_EARNINGS_STATE_DIR", str(root))
    broker.state["account"]["buying_power"] = "1000"
    assert pilot.tick() == "SHARED_RISK_BLOCKED"
    assert journal.last("opportunity")["reason"] == "BUYING_POWER"
    assert _posts(broker) == 0
    journal.close()


def test_persistent_fresh_setup_is_not_changed_by_the_minute(tmp_path):
    """The same opening-range setup stays eligible when only the completed bar time moves."""
    minute, _daily = market_bars()
    calls = {"n": 0}

    def transport(*args, **kwargs):
        calls["n"] += 1
        return scored_response(0.55, 0.90)

    policy = PilotPolicy("AAPL", fallback_after_open_minutes=120)
    pilot, broker, journal = _fallback_pilot(tmp_path, transport, policy, minute)
    assert pilot.tick() == "JEV_VETO"
    minute.append({
        "t": (OPEN + timedelta(minutes=16)).isoformat(),
        "o": 101.5, "h": 101.8, "l": 100.2, "c": 101.5, "v": 1000,
    })
    broker.state["clock"]["timestamp"] = (OPEN + timedelta(minutes=17, seconds=5)).isoformat()
    assert pilot.tick() == "JEV_VETO"
    assert calls["n"] == 2
    minute.append({
        "t": (OPEN + timedelta(minutes=119)).isoformat(),
        "o": 101.5, "h": 101.8, "l": 100.2, "c": 101.5, "v": 1000,
    })
    broker.state["clock"]["timestamp"] = (OPEN + timedelta(minutes=120, seconds=5)).isoformat()
    assert pilot.tick() == "ENTRY_SUBMITTED"
    assert calls["n"] == 2
    assert _posts(broker) == 1
    assert journal.last("fallback_no_trade") is None
    order = journal.last("entry_intent")["order"]
    assert order["qty"] == "1"
    assert order["limit_price"] == "101.50"
    assert order["time_in_force"] == "day"
    journal.close()


def test_entry_timeout_records_one_unfilled_outcome_after_restart(setup):
    pilot, broker, _actor, journal = setup
    assert pilot.tick() == "ENTRY_SUBMITTED"
    identity = journal.last("entry_intent")["order"]["client_order_id"]
    broker.state["clock"]["timestamp"] = (NOW + timedelta(seconds=61)).isoformat()
    assert pilot.tick() == "FLATTENING"
    assert journal.last("halt")["reason"] == "ENTRY_TIMEOUT"
    broker.parent.update(status="canceled", filled_qty="0")
    broker.state["orders"] = []
    broker.state["positions"] = []
    restarted = ActivePaperPilot(broker, pilot.jev, journal, POLICY)
    assert restarted.tick() == "FLATTENING"
    assert restarted.tick() == "COMPLETE"
    unfilled = [
        event for event in journal.events
        if event["kind"] == "opportunity" and event["stage"] == "unfilled"
    ]
    assert len(unfilled) == 1
    assert unfilled[0]["client_order_id"] == identity
    assert unfilled[0]["reason"] == "ENTRY_TIMEOUT"
    again = ActivePaperPilot(broker, pilot.jev, journal, POLICY)
    assert again.tick() == "COMPLETE"
    assert sum(
        event["kind"] == "opportunity" and event["stage"] == "unfilled" for event in journal.events
    ) == 1
    journal.close()
