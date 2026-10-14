"""Earnings Adaptive paper book. Fixtures use Alpaca-shaped payloads; nothing is sent."""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from athena_trading.athena_adapter.contracts import canonical_hash
from athena_trading.athena_adapter.jev import JEV_MODEL, JevDecisionEngine, ModelError, questions
from athena_trading.execution.authority import AuthorityError, ExecutionAuthority, parse_authority
from athena_trading.paper.earnings import (
    EarningsBook, EarningsPolicy, bracket_order, earnings_client_order_id, earnings_questions,
    entry_session, hold_action, load_universe, news_for_decision, plan_entry, policy_from_environment,
    resolve_restart_policy,
)
from athena_trading.paper.learning import LearningStore
from athena_trading.paper.earnings_calendar import EarningsReport, parse_nasdaq_calendar
from athena_trading.paper.journal import PaperJournal
from athena_trading.paper.live import LivePaperAPI, normalize_news_page
from athena_trading.paper.ownership import EARNINGS_ORDER_PREFIX, INTRADAY_ORDER_PREFIX

NOW = datetime(2026, 10, 13, 13, 40, 5, tzinfo=UTC)
STOP_ID = "8f6c1d2e-1b3a-4c5d-9e7f-0a1b2c3d4e5f"
TAKE_ID = "7e5b0c1d-0a29-4b4c-8d6e-9f0a1b2c3d4e"


def jev_response(choice="TAKE_TRADE", confidence=0.9):
    return {"model": JEV_MODEL, "usage": {"input_tokens": 300, "output_tokens": 50},
            "answers": {"entry_decision": {
                "type": "choice", "choice": choice, "confidence": confidence,
                "probabilities": {opt: 0.9 if opt == choice else 0.05
                                  for opt in ("TAKE_TRADE", "NO_TRADE", "INSUFFICIENT_EVIDENCE")},
            }}}


def calendar_rows():
    return [
        {"date": "2026-10-09", "open": "09:30", "close": "16:00"},
        {"date": "2026-10-12", "open": "09:30", "close": "16:00"},
        {"date": "2026-10-13", "open": "09:30", "close": "16:00"},
        {"date": "2026-10-14", "open": "09:30", "close": "16:00"},
        {"date": "2026-10-15", "open": "09:30", "close": "16:00"},
        {"date": "2026-10-16", "open": "09:30", "close": "16:00"},
    ]


def minute_bars(close=104.0):
    start = datetime(2026, 10, 13, 13, 30, tzinfo=UTC)
    return [{
        "t": (start + timedelta(minutes=i)).isoformat(),
        "o": close - 0.4, "h": close + 0.2, "l": close - 0.6, "c": close, "v": 12000,
    } for i in range(10)]


def nasdaq(day_has_deck=True):
    def transport(method, url, headers, payload=None, timeout=5):
        assert method == "GET"
        assert "api.nasdaq.com/api/calendar/earnings" in url
        assert "Mozilla" in headers["User-Agent"]
        if "date=2026-10-13" in url and day_has_deck:
            return {"data": {"asOf": "Tue, 13 Oct 2026 00:00:00 -0400", "rows": [
                {"symbol": "DECK", "name": "Deckers Outdoor Corporation", "time": "time-pre-market",
                 "marketCap": "$15,200,000,000", "fiscalQuarterEnding": "Sep/2026",
                 "epsForecast": "$1.40", "noOfEsts": "12", "lastYearRptDt": "10/24/2025",
                 "lastYearEPS": "$1.25"},
                {"symbol": "ETSY", "name": "Etsy Inc.", "time": "time-not-supplied",
                 "marketCap": "$6,000,000,000", "epsForecast": "$0.50", "noOfEsts": "8"},
                {"symbol": "BRK/B", "name": "Berkshire", "time": "time-pre-market"},
            ]}, "message": None, "status": {"rCode": 200, "bCodeMessage": None}}
        return {"data": {"calendar": {"rows": None}}, "status": {"rCode": 200}}
    return transport


class BookBroker:
    """In-memory Alpaca paper. Payloads follow the nested bracket shape."""

    def __init__(self, close=104.0):
        self.close = close
        self.state = {
            "clock": {"timestamp": NOW.isoformat(), "is_open": True,
                      "next_close": "2026-10-13T20:00:00Z"},
            "account": {"id": "paper-account", "equity": "100000", "last_equity": "100000",
                        "buying_power": "100000", "status": "ACTIVE", "trading_blocked": False,
                        "account_blocked": False, "trade_suspended_by_user": False},
            "positions": [], "orders": [],
        }
        self.calls = []
        self.parents = {}
        self.lose_submit = False
        self.drop_submit = False
        self.hidden = set()
        self.fail_get = None
        self.news_items = []
        self.fail_news = None
        self.news_calls = []
        self.order_by_id = {}

    def news(self, symbols, start, end):
        self.news_calls.append((list(symbols), start.isoformat()))
        if self.fail_news is not None:
            raise self.fail_news
        return list(self.news_items)

    def snapshot(self):
        return copy.deepcopy(self.state)

    def bars(self, symbol, start, end, timeframe, feed):
        if timeframe == "1Day":
            return [{"t": "2026-10-12T20:00:00Z", "o": 100, "h": 103, "l": 99, "c": 100,
                     "v": 2_500_000}]
        return minute_bars(self.close)

    def call(self, method, path, payload=None):
        self.calls.append((method, path, copy.deepcopy(payload)))
        if path.startswith("/v2/calendar"):
            return calendar_rows()
        if path.startswith("/v2/assets/"):
            return {"id": "b0b6dd9d-8b9b-48a9-ba46-b9d54906e415", "class": "us_equity",
                    "exchange": "NASDAQ", "symbol": path.rsplit("/", 1)[-1], "status": "active",
                    "tradable": True, "marginable": True, "shortable": True, "easy_to_borrow": True,
                    "fractionable": True}
        if method == "POST" and path == "/v2/orders":
            if self.drop_submit:
                raise ModelError("timeout")
            order = _accepted_bracket(payload)
            self.parents[payload["client_order_id"]] = order
            self.state["orders"] = [copy.deepcopy(order)]
            if self.lose_submit:
                raise ModelError("timeout")
            return copy.deepcopy(order)
        if path.startswith("/v2/orders:by_client_order_id"):
            client_order_id = path.split("client_order_id=", 1)[1]
            if self.fail_get is not None:
                raise self.fail_get
            if client_order_id in self.hidden or client_order_id not in self.parents:
                raise ModelError("HTTP 404", status=404)
            return copy.deepcopy(self.parents[client_order_id])
        if method == "DELETE" and path.startswith("/v2/orders/"):
            return None
        if method == "DELETE" and path.startswith("/v2/positions/"):
            symbol = urlsplit(path).path.rsplit("/", 1)[-1]
            held = next((item for item in self.state["positions"] if item.get("symbol") == symbol), None)
            position_qty = held.get("qty") if isinstance(held, dict) else "0"
            qty = parse_qs(urlsplit(path).query).get("qty", [str(abs(float(position_qty)))])[0]
            price = held.get("avg_entry_price") if isinstance(held, dict) else None
            order_id = (
                "c0ffee00-0000-4000-8000-000000000001" if symbol == "DECK"
                else "c0ffee00-0000-4000-8000-000000000002"
            )
            ack = {
                "id": order_id,
                "client_order_id": "broker-close-" + symbol,
                "symbol": symbol, "qty": str(abs(float(qty))).removesuffix(".0"),
                "filled_qty": "0", "filled_avg_price": None,
                "created_at": self.state["clock"]["timestamp"],
                "submitted_at": self.state["clock"]["timestamp"],
                "side": "sell" if float(position_qty) > 0 else "buy", "type": "market", "order_class": "simple",
                "time_in_force": "day", "status": "new", "extended_hours": False,
            }
            # The acknowledgement is not the fill. A later read returns the terminal order.
            terminal = dict(ack)
            if qty not in (None, "", "0") and price not in (None, ""):
                terminal.update(status="filled", filled_qty=ack["qty"], filled_avg_price=price)
            self.order_by_id[order_id] = terminal
            return ack
        if method == "GET" and path.startswith("/v2/orders/") and "?" not in path:
            order_id = path.rsplit("/", 1)[-1]
            stored = self.order_by_id.get(order_id)
            if stored is None:
                raise AssertionError((method, path))
            return copy.deepcopy(stored)
        if path.startswith("/v2/orders?"):
            return [copy.deepcopy(order) for order in self.parents.values()]
        raise AssertionError((method, path))


def _accepted_bracket(payload):
    """Shape returned by POST /v2/orders for a new bracket, before either leg is held."""
    return {
        "id": "61e69015-8549-4bfd-b9c3-" + canonical_hash(payload)[-12:],
        "client_order_id": payload["client_order_id"],
        "created_at": "2026-10-13T13:40:01.102282Z",
        "updated_at": "2026-10-13T13:40:01.102282Z",
        "submitted_at": "2026-10-13T13:40:01.098000Z",
        "filled_at": None, "expired_at": None, "canceled_at": None, "failed_at": None,
        "replaced_at": None, "replaced_by": None, "replaces": None,
        "asset_id": "b0b6dd9d-8b9b-48a9-ba46-b9d54906e415",
        "symbol": payload["symbol"], "asset_class": "us_equity", "notional": None,
        "qty": payload["qty"], "filled_qty": "0", "filled_avg_price": None,
        "order_class": payload["order_class"], "order_type": payload["type"],
        "type": payload["type"], "side": payload["side"],
        "time_in_force": payload["time_in_force"], "limit_price": payload["limit_price"],
        "stop_price": None, "status": "new", "extended_hours": payload["extended_hours"],
        "legs": [], "trail_percent": None, "trail_price": None, "hwm": None,
    }


def _leg(client_order_id, **overrides):
    leg = {
        "id": TAKE_ID, "client_order_id": client_order_id,
        "created_at": "2026-10-13T13:40:05.100000Z", "updated_at": "2026-10-13T13:40:05.100000Z",
        "submitted_at": "2026-10-13T13:40:05.100000Z", "filled_at": None, "expired_at": None,
        "canceled_at": None, "failed_at": None, "replaced_at": None, "replaced_by": None,
        "replaces": None, "symbol": "DECK", "asset_class": "us_equity", "notional": None,
        "qty": "19", "filled_qty": "0", "filled_avg_price": None, "order_class": "bracket",
        "order_type": "limit", "type": "limit", "side": "sell", "time_in_force": "gtc",
        "limit_price": "108.00", "stop_price": None, "status": "new", "extended_hours": False,
        "legs": None,
    }
    leg.update(overrides)
    return leg


def fill_bracket(broker, client_order_id, *, stop_status="held"):
    parent = broker.parents[client_order_id]
    qty = parent["qty"]
    parent.update(status="filled", filled_qty=qty, filled_avg_price=parent["limit_price"],
                  filled_at="2026-10-13T13:40:04.880000Z",
                  updated_at="2026-10-13T13:40:04.880000Z")
    take = _leg(client_order_id + "-tp", id=TAKE_ID, qty=qty, status="new", type="limit",
                order_type="limit", limit_price="108.00", stop_price=None)
    stop = _leg(client_order_id + "-stop", id=STOP_ID, qty=qty, status=stop_status, type="stop",
                order_type="stop", limit_price=None, stop_price="102.00",
                filled_at="2026-10-13T13:40:10Z" if stop_status == "filled" else None)
    parent["legs"] = [take, stop]
    broker.state["orders"] = [copy.deepcopy(take)]
    broker.state["positions"] = [{
        "asset_id": "b0b6dd9d-8b9b-48a9-ba46-b9d54906e415",
        "symbol": "DECK", "exchange": "NASDAQ", "asset_class": "us_equity",
        "avg_entry_price": parent["limit_price"], "qty": qty, "side": "long",
        "market_value": "1976.00", "cost_basis": "1976.00", "unrealized_pl": "0",
        "unrealized_plpc": "0", "current_price": parent["limit_price"],
        "lastday_price": "100.00", "change_today": "0.04", "qty_available": qty,
    }]


@pytest.fixture(autouse=True)
def _shared_learning_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ATHENA_STATE_DIR", str(tmp_path / "athena-state"))


def _book(tmp_path, monkeypatch, *, close=104.0, choice="TAKE_TRADE", policy=None, names=("DECK", "CROX"),
         folder=None):
    monkeypatch.delenv("ATHENA_EARNINGS_STATE_DIR", raising=False)
    root = folder or tmp_path
    root.mkdir(parents=True, exist_ok=True)
    universe = root / "universe_75.txt"
    universe.write_text("\n".join(names) + "\n")
    journal = PaperJournal(root / "book.sqlite")
    broker = BookBroker(close=close)
    calls = {"n": 0}

    def transport(*args, **kwargs):
        calls["n"] += 1
        return jev_response(choice)

    jev = JevDecisionEngine("fixture-key", transport=transport)
    policy = policy or EarningsPolicy(str(universe))
    book = EarningsBook(broker, jev, journal, policy, calendar_transport=nasdaq())
    return book, broker, journal, calls


def _posts(broker):
    return [payload for method, path, payload in broker.calls if method == "POST" and path == "/v2/orders"]


def test_live_authority_is_rejected_and_absent_cannot_submit(tmp_path, monkeypatch):
    with pytest.raises(AuthorityError):
        parse_authority("LIVE")
    book, broker, journal, _calls = _book(tmp_path, monkeypatch)
    book.authority = ExecutionAuthority.ABSENT
    with pytest.raises(AuthorityError):
        book._commit(
            {}, {}, {"price": 1, "shares": 1, "side": "buy"},
            EarningsReport("DECK", "2026-10-13", "BMO"),
            account_id="paper-account", observed_at=NOW, session_day="2026-10-13", verdict_hash="x",
        )
    assert _posts(broker) == []
    journal.close()


def test_gap_band_stop_target_and_risk_caps():
    kwargs = dict(
        open_risk=0, open_notional=0, equity=100_000, buying_power=100_000,
        per_trade_risk=50, total_risk=150, max_notional_per_trade=2000, max_notional_total=6000,
        gap_low=0.04, gap_high=0.12, stop_gap_fraction=0.5, target_r=2,
    )
    long = plan_entry(price=104, prior_close=100, **kwargs)
    assert long["direction"] == "LONG" and long["shares"] == 19
    assert long["stop"] == 102 and long["target"] == 108 and long["risk"] == 38
    assert plan_entry(price=103.99, prior_close=100, **kwargs) is None
    assert plan_entry(price=112, prior_close=100, **kwargs)["gap_fraction"] == pytest.approx(0.12)
    assert plan_entry(price=112.02, prior_close=100, **kwargs) is None
    short = plan_entry(price=96, prior_close=100, **kwargs)
    assert short["direction"] == "SHORT" and short["stop"] == 98 and short["target"] == 92
    assert plan_entry(price=3000, prior_close=2880, **kwargs) is None
    blocked = plan_entry(price=104, prior_close=100, **{**kwargs, "open_risk": 150})
    assert blocked is None
    order = bracket_order("DECK", long)
    assert order["time_in_force"] == "day" and order["extended_hours"] is False
    assert order["order_class"] == "bracket" and order["qty"] == "19"


def test_hold_and_entry_session_follow_the_report_clock():
    sessions = ["2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16"]
    bmo = EarningsReport("DECK", "2026-10-13", "BMO")
    amc = EarningsReport("DECK", "2026-10-13", "AMC")
    assert entry_session(bmo, sessions) == "2026-10-13"
    assert entry_session(amc, sessions) == "2026-10-14"
    close_at = datetime(2026, 10, 15, 20, 0, tzinfo=UTC)
    early = datetime(2026, 10, 15, 18, 0, tzinfo=UTC)
    late = datetime(2026, 10, 15, 19, 50, tzinfo=UTC)
    assert hold_action("2026-10-13", "2026-10-14", sessions, 3, is_open=True, now=early,
                       close_at=close_at, close_buffer_minutes=15) == "FLATTEN"
    assert hold_action("2026-10-15", "2026-10-15", sessions, 1, is_open=True, now=early,
                       close_at=close_at, close_buffer_minutes=15) == "HOLD"
    assert hold_action("2026-10-13", "2026-10-15", sessions, 3, is_open=True, now=late,
                       close_at=close_at, close_buffer_minutes=15) == "FLATTEN"
    missed = datetime(2026, 10, 16, 14, 0, tzinfo=UTC)
    assert hold_action("2026-10-13", "2026-10-16", sessions, 3, is_open=True, now=missed,
                       close_at=datetime(2026, 10, 16, 20, 0, tzinfo=UTC),
                       close_buffer_minutes=15) == "FLATTEN"
    assert hold_action("2026-10-13", "2026-10-16", sessions, 3, is_open=False, now=missed,
                       close_at=datetime(2026, 10, 16, 20, 0, tzinfo=UTC),
                       close_buffer_minutes=15) == "WAIT"


def test_client_order_id_is_stable_and_prefixed():
    first = earnings_client_order_id("paper-account", "DECK", "2026-10-13")
    assert first == earnings_client_order_id("paper-account", "DECK", "2026-10-13")
    assert first.startswith(EARNINGS_ORDER_PREFIX) and not first.startswith(INTRADAY_ORDER_PREFIX)
    assert first != earnings_client_order_id("paper-account", "DECK", "2026-10-14")
    assert len(first) <= 48


def test_nasdaq_calendar_parses_both_shapes_and_skips_unknown_time():
    payload = {"data": {"rows": [
        {"symbol": "deck", "time": "time-pre-market"},
        {"symbol": "NKE", "time": "time-after-hours"},
        {"symbol": "ETSY", "time": "time-not-supplied"},
        {"symbol": "BRK/B", "time": "TIME-PRE-MARKET"},
        {"symbol": "", "time": "time-pre-market"},
    ]}}
    reports, skipped = parse_nasdaq_calendar(payload, report_date="2026-10-13")
    assert [(item.symbol, item.when) for item in reports] == [
        ("DECK", "BMO"), ("NKE", "AMC"), ("BRK.B", "BMO"),
    ]
    assert {item["reason"] for item in skipped} >= {"TIME_UNKNOWN", "BAD_SYMBOL"}
    nested, _skipped = parse_nasdaq_calendar(
        {"data": {"calendar": {"rows": [{"symbol": "CROX", "time": "time-after-hours"}]}}},
        report_date="2026-10-12",
    )
    assert nested == [EarningsReport("CROX", "2026-10-12", "AMC")]
    assert parse_nasdaq_calendar({"data": {"rows": None}}, report_date="2026-10-13") == ([], [])
    assert parse_nasdaq_calendar({"data": {}}, report_date="2026-10-13") == ([], [])
    with pytest.raises(ValueError):
        parse_nasdaq_calendar({"data": {"rows": "nope"}}, report_date="2026-10-13")


def test_universe_file_normalizes_and_rejects_an_oversized_list(tmp_path):
    path = tmp_path / "universe_75.txt"
    path.write_text("# screener output\nDECK\nbrk-b\nDECK\n")
    assert load_universe(path) == ["DECK", "BRK.B"]
    path.write_text("\n".join(f"A{i:02d}" for i in range(76)) + "\n")
    with pytest.raises(ValueError, match="75"):
        load_universe(path)


def test_policy_rejects_a_wider_band_and_live_sized_caps(tmp_path, monkeypatch):
    path = str(tmp_path / "universe_75.txt")
    with pytest.raises(ValueError):
        EarningsPolicy(path, gap_high=0.2)
    with pytest.raises(ValueError):
        EarningsPolicy(path, per_trade_risk=500)
    monkeypatch.setenv("ATHENA_EARNINGS_PER_TRADE_RISK", "40")
    monkeypatch.setenv("ATHENA_JEV_MIN_PTAKE", "0.7")
    monkeypatch.setenv("ATHENA_SYMBOL", "spy")
    policy = policy_from_environment(path, "iex")
    assert policy.per_trade_risk == 40 and policy.support_min == 0.7
    assert policy.excluded_symbol == "SPY" and policy.gap_low == 0.04 and policy.gap_high == 0.12


def test_supported_gap_submits_one_day_bracket_and_recovers_next_day(tmp_path, monkeypatch):
    book, broker, journal, calls = _book(tmp_path, monkeypatch)
    assert book.tick() == "ENTRY_SUBMITTED"
    posted = _posts(broker)
    assert len(posted) == 1
    order = posted[0]
    assert order["symbol"] == "DECK" and order["qty"] == "19"
    assert order["type"] == "limit" and order["time_in_force"] == "day"
    assert order["extended_hours"] is False and order["order_class"] == "bracket"
    assert order["limit_price"] == "104.00"
    assert order["stop_loss"] == {"stop_price": "102.00"}
    assert order["take_profit"] == {"limit_price": "108.00"}
    assert order["client_order_id"].startswith("athe-")
    assert journal.last("entry_ack")["order"]["status"] == "new"
    assert journal.last("entry_ack")["order"]["filled_qty"] == "0"
    ledger = json.loads((tmp_path / "ownership.json").read_text())
    assert ledger["prefix"] == "athe-" and ledger["symbols"] == ["DECK"]
    assert any(event["reason"] == "TIME_UNKNOWN" for event in journal.events if event["kind"] == "calendar_skip")
    fill_bracket(broker, order["client_order_id"])
    assert book.tick() == "POSITION_OPEN"
    assert journal.last("entry_intent")["apde_state"] == "EXPLORE"
    restarted = EarningsBook(
        broker, book.jev, journal, book.policy, calendar_transport=nasdaq(),
    )
    broker.state["clock"]["timestamp"] = "2026-10-14T13:50:00Z"
    broker.state["clock"]["next_close"] = "2026-10-14T20:00:00Z"
    assert restarted.tick() == "FLATTENING"
    assert journal.last("trade_exit")["reason"] == "OVERNIGHT_RECOVERY"
    assert len(_posts(broker)) == 1
    assert calls["n"] == 1
    journal.close()


def test_held_stop_counts_as_protection_and_a_missing_stop_flattens_only_that_symbol(tmp_path, monkeypatch):
    book, broker, journal, calls = _book(tmp_path, monkeypatch)
    book.tick()
    client_order_id = _posts(broker)[0]["client_order_id"]
    fill_bracket(broker, client_order_id, stop_status="canceled")
    broker.state["orders"].append({
        "id": "athp-stop-id", "client_order_id": "athp-aapl-stop", "symbol": "AAPL",
        "qty": "1", "filled_qty": "0", "side": "sell", "type": "stop", "status": "held",
        "stop_price": "99", "time_in_force": "day", "order_class": "bracket",
    })
    calls["n"] = 0
    book.jev = JevDecisionEngine("fixture-key", transport=lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("protective exit must not call Jev")))
    assert book.tick() == "FLATTENING"
    assert journal.last("trade_exit")["reason"] == "PROTECTION_MISSING"
    deleted = [path for method, path, _ in broker.calls if method == "DELETE"]
    assert deleted
    assert all("AAPL" not in path and "athp-stop-id" not in path for path in deleted)
    assert calls["n"] == 0
    journal.close()


def test_overdue_hold_flattens_and_survives_the_book_file(tmp_path, monkeypatch):
    book, broker, journal, _calls = _book(tmp_path, monkeypatch)
    book.tick()
    client_order_id = _posts(broker)[0]["client_order_id"]
    fill_bracket(broker, client_order_id)
    broker.state["clock"]["timestamp"] = "2026-10-15T19:50:00Z"
    broker.state["clock"]["next_close"] = "2026-10-15T20:00:00Z"
    assert book.tick() == "FLATTENING"
    assert journal.last("trade_exit")["reason"] == "OVERNIGHT_RECOVERY"
    for leg in broker.parents[client_order_id]["legs"]:
        leg["status"] = "canceled"
    broker.state["orders"] = []
    assert book.tick() == "FLATTENING"
    assert any(urlsplit(path).path == "/v2/positions/DECK" for method, path, _ in broker.calls if method == "DELETE")
    broker.state["positions"] = []
    assert book.tick() == "FLATTENING"
    assert book.tick() == "NO_CANDIDATE"
    assert journal.last("position_closed")["client_order_id"] == client_order_id
    assert journal.last("earnings_experience")["eligible_for_intraday_study"] is False
    ledger = json.loads((tmp_path / "ownership.json").read_text())
    assert ledger["symbols"] == []
    journal.close()


def test_lost_submit_and_a_second_process_do_not_resend(tmp_path, monkeypatch):
    book, broker, journal, _calls = _book(tmp_path, monkeypatch)
    broker.lose_submit = True
    with pytest.raises(ModelError):
        book.tick()
    assert len(_posts(broker)) == 1
    broker.lose_submit = False
    recovered = EarningsBook(broker, book.jev, journal, book.policy, calendar_transport=nasdaq())
    assert recovered.tick() == "ENTRY_WORKING"
    assert len(_posts(broker)) == 1
    journal.close()


def test_two_flat_404s_close_the_reservation_without_a_new_order(tmp_path, monkeypatch):
    book, broker, journal, _calls = _book(tmp_path, monkeypatch)
    broker.drop_submit = True
    with pytest.raises(ModelError):
        book.tick()
    assert journal.last("entry_ack") is None
    assert len(_posts(broker)) == 1
    broker.drop_submit = False
    assert book.tick() == "ORDER_NOT_FOUND_RECHECK"
    assert book.tick() == "ENTRY_NOT_CREATED"
    assert len(_posts(broker)) == 1
    assert journal.last("entry_not_created")["reason"] == "BROKER_ORDER_NOT_FOUND"
    journal.close()


def test_jev_veto_and_a_bad_answer_do_not_order_or_flatten(tmp_path, monkeypatch):
    book, broker, journal, _calls = _book(tmp_path, monkeypatch, choice="NO_TRADE")
    assert book.tick() == "JEV_VETO"
    assert journal.last("adjudication")["receipt"]["accepted"] is False
    assert _posts(broker) == []
    journal.close()

    universe = tmp_path / "universe_75.txt"
    journal = PaperJournal(tmp_path / "bad.sqlite")
    broker = BookBroker()

    def bad(*args, **kwargs):
        payload = jev_response()
        payload["answers"]["entry_decision"]["probabilities"] = {
            "TAKE_TRADE": 0.9, "NO_TRADE": 0.9, "INSUFFICIENT_EVIDENCE": 0.9,
        }
        return payload

    book = EarningsBook(
        broker, JevDecisionEngine("fixture-key", transport=bad), journal,
        EarningsPolicy(str(universe)), calendar_transport=nasdaq(),
    )
    assert book.tick() == "JEV_VETO"
    assert journal.last("jev_veto")["accepted"] is False
    assert _posts(broker) == []
    assert journal.last("trade_exit") is None
    journal.close()


def test_model_outage_does_not_flatten_an_open_earnings_position(tmp_path, monkeypatch):
    universe = tmp_path / "universe_75.txt"
    universe.write_text("DECK\nCROX\n")
    journal = PaperJournal(tmp_path / "book.sqlite")
    broker = BookBroker()
    calls = {"n": 0}

    def transport(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return jev_response()
        raise ModelError("HTTP 503", status=503)

    def calendar(method, url, headers, payload=None, timeout=5):
        body = nasdaq()(method, url, headers, payload, timeout)
        if "date=2026-10-13" in url:
            body["data"]["rows"].append(
                {"symbol": "CROX", "time": "time-pre-market", "name": "Crocs", "epsForecast": "$2"},
            )
        return body

    policy = EarningsPolicy(str(universe), max_new_entries_per_day=2)
    book = EarningsBook(
        broker, JevDecisionEngine("fixture-key", transport=transport), journal, policy,
        calendar_transport=calendar,
    )
    assert book.tick() == "ENTRY_SUBMITTED"
    fill_bracket(broker, _posts(broker)[0]["client_order_id"])
    assert book.tick() == "JEV_UNAVAILABLE"
    assert broker.state["positions"][0]["symbol"] == "DECK"
    assert not any(method == "DELETE" and "DECK" in path for method, path, _ in broker.calls)
    journal.close()


def test_read_timeout_while_open_is_not_a_flatten(tmp_path, monkeypatch):
    book, broker, journal, _calls = _book(tmp_path, monkeypatch)
    book.tick()
    fill_bracket(broker, _posts(broker)[0]["client_order_id"])
    broker.fail_get = ModelError("request failed: TimeoutError")
    with pytest.raises(ModelError, match="TimeoutError"):
        book.tick()
    assert broker.state["positions"]
    assert not any(method == "DELETE" for method, _path, _payload in broker.calls)
    journal.close()


def test_partial_fill_and_quantity_mismatch_do_not_adopt_the_position(tmp_path, monkeypatch):
    book, broker, journal, _calls = _book(tmp_path, monkeypatch)
    book.tick()
    client_order_id = _posts(broker)[0]["client_order_id"]
    parent = broker.parents[client_order_id]
    parent.update(status="partially_filled", filled_qty="1")
    broker.state["positions"] = [{
        "symbol": "DECK", "qty": "1", "side": "long", "asset_class": "us_equity",
        "avg_entry_price": "104.00",
    }]
    broker.state["orders"] = [copy.deepcopy(parent)]
    assert book.tick() == "FLATTENING"
    assert journal.last("trade_exit")["reason"] == "PARTIAL_ENTRY"
    journal.close()

    book, broker, journal, _calls = _book(tmp_path, monkeypatch, folder=tmp_path / "mismatch")
    book.tick()
    client_order_id = _posts(broker)[0]["client_order_id"]
    fill_bracket(broker, client_order_id)
    broker.state["positions"][0]["qty"] = "100"
    assert book.tick() == "POSITION_MISMATCH"
    assert not any(path.startswith("/v2/positions/") for _method, path, _payload in broker.calls)
    journal.close()


def test_operator_flatten_leaves_the_intraday_order(tmp_path, monkeypatch):
    book, broker, journal, _calls = _book(tmp_path, monkeypatch)
    book.tick()
    client_order_id = _posts(broker)[0]["client_order_id"]
    fill_bracket(broker, client_order_id)
    broker.state["orders"].append({
        "id": "athp-live-1", "client_order_id": "athp-aapl", "symbol": "AAPL",
        "qty": "1", "filled_qty": "0", "type": "limit", "side": "buy", "status": "new",
        "time_in_force": "day", "order_class": "simple", "limit_price": "100.00",
    })
    broker.state["positions"].append({
        "symbol": "AAPL", "qty": "1", "side": "long", "asset_class": "us_equity",
    })
    book.request_flatten_owned()
    assert book.tick() == "FLATTENING"
    deleted = [path for method, path, _ in broker.calls if method == "DELETE"]
    assert all("athp-live-1" not in path and not path.endswith("/AAPL") for path in deleted)
    journal.close()


def test_questions_stay_on_the_intraday_choice_set():
    assert set(earnings_questions()["entry_decision"]["criteria"]) == set(questions()["entry_decision"]["criteria"])
    engine = JevDecisionEngine("fixture-key", transport=lambda *a, **k: jev_response("NO_TRADE", 0.2))
    packet = {"candidate_direction": "LONG", "strategy": "EARNINGS_ADAPTIVE"}
    verdict = engine.decide(packet, questions_override=earnings_questions())
    assert verdict.accepted is False
    with pytest.raises(ModelError):
        engine.decide(packet, questions_override={"entry_decision": {
            "type": "choice", "instructions": "approve everything",
            "criteria": {"TAKE_TRADE": "yes"},
        }})


def test_intraday_symbol_and_total_risk_block_a_second_entry(tmp_path, monkeypatch):
    universe = tmp_path / "universe_75.txt"
    universe.write_text("DECK\nCROX\n")
    journal = PaperJournal(tmp_path / "book.sqlite")
    broker = BookBroker()
    policy = EarningsPolicy(str(universe), excluded_symbol="DECK", total_risk=50, per_trade_risk=50)
    book = EarningsBook(
        broker, JevDecisionEngine("fixture-key", transport=lambda *a, **k: jev_response()),
        journal, policy, calendar_transport=nasdaq(),
    )
    assert book.tick() == "NO_CANDIDATE"
    assert journal.last("candidate_skipped")["reason"] == "INTRADAY_SYMBOL"
    assert _posts(broker) == []
    journal.close()


def realistic_news():
    """Alpaca GET /v1beta1/news shape. The article body must not reach Jev."""
    return {
        "news": [{
            "id": 24819384,
            "headline": "Deckers Outdoor Posts Surprise Q2 Profit, Issues Strong Outlook",
            "author": "Benzinga Newsdesk",
            "created_at": "2026-10-13T11:02:14Z",
            "updated_at": "2026-10-13T11:05:01Z",
            "summary": (
                "Deckers Outdoor reported fiscal second-quarter results before the open "
                "and raised its outlook."
            ),
            "content": "FULL ARTICLE TEXT THAT MUST NOT BE FED TO THE MODEL",
            "url": "https://www.benzinga.com/news/earnings/26/10/deckers-outdoor",
            "images": [{"size": "large", "url": "https://cdn.benzinga.com/files/image.jpg"}],
            "symbols": ["DECK"],
            "source": "benzinga",
        }],
        "next_page_token": None,
    }


def test_out_of_band_gap_is_reconsidered_on_a_later_completed_bar(tmp_path, monkeypatch):
    """A 3.9% print is temporary. A later 4.2% bar inside the window can still be sent."""
    book, broker, journal, calls = _book(tmp_path, monkeypatch, close=103.9)
    assert book.tick() == "NO_CANDIDATE"
    assert calls["n"] == 0
    assert _posts(broker) == []
    assert journal.last("candidate_skipped")["reason"] == "GAP_OR_RISK"
    assert book.tick() == "WAITING"
    assert calls["n"] == 0
    assert sum(event["kind"] == "candidate_skipped" for event in journal.events) == 1

    broker.close = 104.2
    broker.state["clock"]["timestamp"] = "2026-10-13T13:41:05+00:00"

    def bars(symbol, start, end, timeframe, feed):
        if timeframe == "1Day":
            return [{"t": "2026-10-12T20:00:00Z", "o": 100, "h": 103, "l": 99, "c": 100, "v": 2_500_000}]
        return minute_bars(103.9) + [{
            "t": "2026-10-13T13:40:00+00:00", "o": 104.0, "h": 104.4, "l": 103.8, "c": 104.2, "v": 14000,
        }]

    broker.bars = bars
    assert book.tick() == "ENTRY_SUBMITTED"
    assert calls["n"] == 1
    assert _posts(broker)[0]["limit_price"] == "104.20"
    assert sum(event["kind"] == "decision_started" for event in journal.events) == 1
    journal.close()


def test_preview_expected_and_negated_headlines_are_not_confirmed_releases():
    start = datetime(2026, 10, 12, 20, tzinfo=UTC)
    session_open = datetime(2026, 10, 13, 13, 30, tzinfo=UTC)

    def item(headline, summary, created="2026-10-13T12:10:00Z"):
        return {
            "id": headline, "headline": headline, "summary": summary, "created_at": created,
            "source": "benzinga", "symbols": ["DECK"],
        }

    preview = item(
        "DECK earnings preview: what analysts expect before the company reports",
        "Analysts expect earnings growth.",
    )
    status, fed = news_for_decision([preview], "DECK", start, session_open)
    assert status == "unconfirmed"
    assert fed[0]["source"] == "benzinga" and fed[0]["created_at"] == preview["created_at"]
    expected = item("DECK earnings expected after the close", "The company is set to report tonight.")
    assert news_for_decision([expected], "DECK", start, session_open)[0] == "unconfirmed"
    negated = item("DECK did not report earnings", "The release was delayed.")
    assert news_for_decision([negated], "DECK", start, session_open)[0] == "unconfirmed"
    split = item("DECK announces a 6-for-1 stock split", "The split is effective next month.")
    assert news_for_decision([split], "DECK", start, session_open)[0] == "unconfirmed"
    dividend = item("DECK declares a special dividend", "The distribution is not an earnings release.")
    assert news_for_decision([dividend], "DECK", start, session_open)[0] == "unconfirmed"
    released = item(
        "Deckers Outdoor Posts Surprise Q2 Profit, Issues Strong Outlook",
        "Deckers Outdoor reported fiscal second-quarter results before the open.",
    )
    status, fed = news_for_decision([released], "DECK", start, session_open)
    assert status == "confirmed"
    assert fed[0]["id"] == released["id"]


def test_news_confirmation_uses_a_preopen_report_and_ignores_a_later_headline():
    start = datetime(2026, 10, 12, 20, tzinfo=UTC)
    session_open = datetime(2026, 10, 13, 13, 30, tzinfo=UTC)
    late = {
        "id": 9, "headline": "Deckers Outdoor reports record earnings", "summary": "After the bell.",
        "created_at": "2026-10-13T13:35:00Z", "source": "benzinga", "symbols": ["DECK"],
    }
    status, fed = news_for_decision([late], "DECK", start, session_open)
    assert status == "unconfirmed"
    assert fed[0]["headline"].startswith("Deckers")
    assert news_for_decision(None, "DECK", start, session_open) == ("unavailable", [])
    partner = {
        "id": 8, "headline": "Deckers Outdoor names a retail partner", "summary": "A store opening.",
        "created_at": "2026-10-13T12:00:00Z", "source": "benzinga", "symbols": ["DECK"],
    }
    status, fed = news_for_decision([partner], "DECK", start, session_open)
    assert status == "unconfirmed"


def test_alpaca_news_is_fed_to_jev_and_a_failed_pull_still_enters(tmp_path, monkeypatch):
    book, broker, journal, _calls = _book(tmp_path, monkeypatch)
    broker.news_items = normalize_news_page(realistic_news())
    assert book.tick() == "ENTRY_SUBMITTED"
    fed = journal.last("news_fed")
    assert fed["news"] == "confirmed"
    assert fed["items"][0]["headline"].startswith("Deckers Outdoor Posts")
    assert "FULL ARTICLE" not in json.dumps(journal.events)
    packet = journal.last("decision_started")["packet"]
    assert packet["observations"]["news"] == "confirmed"
    assert packet["observations"]["news_items"][0]["summary"].startswith("Deckers Outdoor reported")
    assert any("DECK" in symbols for symbols, _at in broker.news_calls)
    journal.close()

    book, broker, journal, _calls = _book(tmp_path, monkeypatch, folder=tmp_path / "down")
    broker.fail_news = ModelError("HTTP 503", status=503)
    assert book.tick() == "ENTRY_SUBMITTED"
    assert journal.last("news_unavailable")["session"] == "2026-10-13"
    assert journal.last("news_fed")["news"] == "unavailable"
    assert journal.last("decision_started")["packet"]["observations"]["news_items"] == []
    journal.close()


def test_news_rate_limit_uses_the_get_retry(monkeypatch):
    monkeypatch.setattr("athena_trading.paper.live.time.sleep", lambda *_args: None)
    calls = {"n": 0}

    def transport(method, url, headers, payload=None, timeout=5):
        assert method == "GET"
        assert url.startswith("https://data.alpaca.markets/v1beta1/news?")
        assert "symbols=DECK" in url
        assert "2026-10-12" in url
        assert headers["APCA-API-KEY-ID"] == "paper-key"
        assert headers["APCA-API-SECRET-KEY"] == "paper-secret"
        calls["n"] += 1
        if calls["n"] == 1:
            raise ModelError("HTTP 429", status=429)
        return realistic_news()

    api = LivePaperAPI("paper-key", "paper-secret", transport=transport)
    items = api.news(
        ["DECK"], datetime(2026, 10, 12, 20, tzinfo=UTC), datetime(2026, 10, 13, 13, 40, tzinfo=UTC),
    )
    assert calls["n"] == 2
    assert items[0]["id"] == 24819384
    assert "content" not in items[0]
    assert "FULL ARTICLE" not in json.dumps(items)
    with pytest.raises(ValueError, match="unusable"):
        normalize_news_page({"news": "nope"})


def test_restart_manages_an_open_position_when_the_models_probe_fails(tmp_path, monkeypatch):
    universe = tmp_path / "universe_75.txt"
    universe.write_text("DECK\nCROX\n")
    journal = PaperJournal(tmp_path / "book.sqlite")
    broker = BookBroker()

    def calendar(method, url, headers, payload=None, timeout=5):
        body = nasdaq()(method, url, headers, payload, timeout)
        if "date=2026-10-13" in url:
            body["data"]["rows"].append(
                {"symbol": "CROX", "time": "time-pre-market", "name": "Crocs", "epsForecast": "$2"},
            )
        return body

    policy = EarningsPolicy(str(universe), max_new_entries_per_day=2)
    first = EarningsBook(
        broker, JevDecisionEngine("fixture-key", transport=lambda *a, **k: jev_response()),
        journal, policy, calendar_transport=calendar,
    )
    assert first.tick() == "ENTRY_SUBMITTED"
    client_order_id = _posts(broker)[0]["client_order_id"]
    fill_bracket(broker, client_order_id)
    journal.close()

    probes = {"n": 0}

    def probe():
        probes["n"] += 1
        raise ModelError("HTTP 503", status=503)

    restarted = PaperJournal(tmp_path / "book.sqlite")
    book = EarningsBook(
        broker, None, restarted, policy, calendar_transport=calendar, model_probe=probe,
    )
    assert book.tick() == "JEV_UNAVAILABLE"
    assert probes["n"] == 1
    assert restarted.last("jev_unavailable")["reason"].startswith("HTTP 503")
    assert broker.state["positions"][0]["symbol"] == "DECK"
    assert not any(method == "DELETE" for method, _path, _payload in broker.calls)
    assert len(_posts(broker)) == 1
    assert book.tick() == "JEV_UNAVAILABLE"
    assert probes["n"] == 2
    assert sum(event["kind"] == "jev_unavailable" for event in restarted.events) == 1
    restarted.close()


def _earnings_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_athena_earnings.py"
    spec = importlib.util.spec_from_file_location("run_athena_earnings_probe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_run_reconciles_a_missing_stop_before_any_models_probe(tmp_path, monkeypatch):
    book, broker, journal, _calls = _book(tmp_path, monkeypatch)
    book.tick()
    client_order_id = _posts(broker)[0]["client_order_id"]
    fill_bracket(broker, client_order_id, stop_status="canceled")
    for leg in broker.parents[client_order_id]["legs"]:
        leg["status"] = "canceled"
    broker.state["orders"] = []
    journal.close()
    script = _earnings_script()
    urls = []

    def transport(method, url, headers, payload=None, timeout=5):
        urls.append(url)
        raise ModelError("HTTP 503", status=503)

    monkeypatch.setenv("ALPACA_API_KEY", "paper-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "paper-secret")
    monkeypatch.setenv("TYPESAFE_API_KEY", "model-key")
    monkeypatch.setenv("ATHENA_EARNINGS_UNIVERSE", str(tmp_path / "universe_75.txt"))
    monkeypatch.setattr(script.LivePaperAPI, "from_env", lambda: broker)
    monkeypatch.setattr(script, "request_json", transport)
    monkeypatch.setattr(script.time, "sleep", lambda *_args: signal.raise_signal(signal.SIGTERM))
    previous = signal.getsignal(signal.SIGTERM)
    try:
        code = script.main([
            "--authority", "PAPER", "--journal", str(tmp_path / "book.sqlite"), "--run",
        ])
    finally:
        signal.signal(signal.SIGTERM, previous)
    assert code == 0
    assert urls == []
    assert any(urlsplit(path).path == "/v2/positions/DECK" for method, path, _ in broker.calls if method == "DELETE")
    reopened = PaperJournal(tmp_path / "book.sqlite")
    try:
        assert reopened.last("trade_exit")["reason"] == "PROTECTION_MISSING"
    finally:
        reopened.close()


def test_preflight_still_reports_jev(tmp_path, monkeypatch, capsys):
    universe = tmp_path / "universe_75.txt"
    universe.write_text("DECK\n")
    script = _earnings_script()
    urls = []

    def transport(method, url, headers, payload=None, timeout=5):
        urls.append(url)
        return {"models": [{"id": JEV_MODEL}]}

    monkeypatch.setenv("ALPACA_API_KEY", "paper-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "paper-secret")
    monkeypatch.setenv("TYPESAFE_API_KEY", "model-key")
    monkeypatch.setenv("ATHENA_EARNINGS_UNIVERSE", str(universe))
    monkeypatch.setattr(script.LivePaperAPI, "from_env", lambda: BookBroker())
    monkeypatch.setattr(script, "request_json", transport)
    code = script.main([
        "--authority", "PAPER", "--journal", str(tmp_path / "preflight.sqlite"), "--preflight",
    ])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["decision_model"] == JEV_MODEL
    assert payload["orders_submitted"] == 0
    assert any(url.startswith("https://api.typesafe.ai/v1/models") for url in urls)


def test_stop_fill_is_stored_as_an_earnings_episode_and_not_an_intraday_rule(tmp_path, monkeypatch):
    book, broker, journal, _calls = _book(tmp_path, monkeypatch)
    assert book.tick() == "ENTRY_SUBMITTED"
    client_order_id = _posts(broker)[0]["client_order_id"]
    fill_bracket(broker, client_order_id)
    parent = broker.parents[client_order_id]
    for leg in parent["legs"]:
        if leg["type"] == "stop":
            leg.update(status="filled", filled_qty=parent["qty"], filled_avg_price="102.00",
                       filled_at="2026-10-13T14:10:00Z")
        else:
            leg.update(status="canceled", filled_qty="0")
    broker.state["positions"] = []
    broker.state["orders"] = []
    assert book.tick() == "FLATTENING"
    assert book.tick() in {"NO_CANDIDATE", "DAILY_ENTRY_DONE"}
    episode_id = journal.last("learning_recorded")["client_order_ids"]
    assert episode_id == [client_order_id]
    store = LearningStore(tmp_path / "athena-state")
    try:
        episodes = [item for item in store.experiences() if item["arm"] == "earnings"]
        assert len(episodes) == 1
        episode = episodes[0]
        assert episode["eligible"] is False
        assert episode["symbol"] == "DECK"
        assert episode["quantity"] == parent["qty"]
        assert episode["result"] == "LOSS"
        assert episode["gross_r"] == -1.0
        assert episode["question_hash"] == canonical_hash(earnings_questions())
        assert episode["question_hash"] != canonical_hash(questions())
        assert episode["decision"]["receipt"]["accepted"] is True
        context = store.context(
            episode["account"], "DECK", "LONG", datetime(2026, 10, 13, 18, tzinfo=UTC),
        )
        assert context["recent_experiences"] == []
    finally:
        store.close()
    assert book.tick() in {"NO_CANDIDATE", "DAILY_ENTRY_DONE"}
    store = LearningStore(tmp_path / "athena-state")
    try:
        assert len([item for item in store.experiences() if item["arm"] == "earnings"]) == 1
    finally:
        store.close()
    journal.close()


def _partial_fill(broker, client_order_id):
    parent = broker.parents[client_order_id]
    take = next(leg for leg in parent["legs"] if leg["type"] == "limit")
    stop = next(leg for leg in parent["legs"] if leg["type"] == "stop")
    take.update(status="partially_filled", filled_qty="5", filled_avg_price="108.00")
    stop.update(qty="14", filled_qty="0", status="held", stop_price="102.00")
    broker.state["positions"][0]["qty"] = "14"
    broker.state["orders"] = [copy.deepcopy(stop)]
    return parent


def test_partial_take_profit_remains_manageable_after_restart(tmp_path, monkeypatch):
    book, broker, journal, _calls = _book(tmp_path, monkeypatch)
    book.tick()
    client_order_id = _posts(broker)[0]["client_order_id"]
    fill_bracket(broker, client_order_id)
    _partial_fill(broker, client_order_id)
    assert book.tick() == "POSITION_OPEN"
    assert journal.last("trade_halt") is None
    journal.close()

    restarted = PaperJournal(tmp_path / "book.sqlite")
    book = EarningsBook(
        broker, None, restarted, EarningsPolicy(str(tmp_path / "universe_75.txt")),
        calendar_transport=nasdaq(),
    )
    assert book.tick() == "POSITION_OPEN"
    for leg in broker.parents[client_order_id]["legs"]:
        if leg["type"] == "stop":
            leg["status"] = "canceled"
        else:
            leg["status"] = "filled"
    broker.state["orders"] = []
    assert book.tick() == "FLATTENING"
    assert restarted.last("trade_exit")["reason"] == "PROTECTION_MISSING"
    assert any(urlsplit(path).path == "/v2/positions/DECK" for method, path, _ in broker.calls if method == "DELETE")
    restarted.close()

    root = tmp_path / "hold"
    book, broker, journal, _calls = _book(tmp_path, monkeypatch, folder=root)
    book.tick()
    client_order_id = _posts(broker)[0]["client_order_id"]
    fill_bracket(broker, client_order_id)
    _partial_fill(broker, client_order_id)
    journal.close()
    restarted = PaperJournal(root / "book.sqlite")
    book = EarningsBook(
        broker, None, restarted, EarningsPolicy(str(root / "universe_75.txt")),
        calendar_transport=nasdaq(),
    )
    broker.state["clock"]["timestamp"] = "2026-10-15T19:50:00Z"
    broker.state["clock"]["next_close"] = "2026-10-15T20:00:00Z"
    assert book.tick() == "FLATTENING"
    assert restarted.last("trade_exit")["reason"] == "OVERNIGHT_RECOVERY"
    for leg in broker.parents[client_order_id]["legs"]:
        leg["status"] = "canceled"
    broker.state["orders"] = []
    assert book.tick() == "FLATTENING"
    assert any(urlsplit(path).path == "/v2/positions/DECK" for method, path, _ in broker.calls if method == "DELETE")
    restarted.close()


def test_acknowledged_close_order_is_not_treated_as_unowned(tmp_path, monkeypatch):
    book, broker, journal, _calls = _book(tmp_path, monkeypatch)
    book.tick()
    client_order_id = _posts(broker)[0]["client_order_id"]
    fill_bracket(broker, client_order_id, stop_status="canceled")
    for leg in broker.parents[client_order_id]["legs"]:
        leg["status"] = "canceled"
    broker.state["orders"] = []
    assert book.tick() == "FLATTENING"
    close_order = copy.deepcopy(journal.last("close_ack")["order"])
    close_order["status"] = "accepted"
    broker.state["orders"] = [close_order]
    assert book.tick() == "FLATTENING"
    position_deletes = [
        urlsplit(path).path for method, path, _ in broker.calls
        if method == "DELETE" and urlsplit(path).path == "/v2/positions/DECK"
    ]
    assert position_deletes == ["/v2/positions/DECK"]
    assert not any(close_order["id"] in path for method, path, _ in broker.calls if method == "DELETE")
    journal.close()

    restarted = PaperJournal(tmp_path / "book.sqlite")
    book = EarningsBook(
        broker, None, restarted, EarningsPolicy(str(tmp_path / "universe_75.txt")),
        calendar_transport=nasdaq(),
    )
    assert book.tick() == "FLATTENING"
    assert [
        urlsplit(path).path for method, path, _ in broker.calls
        if method == "DELETE" and urlsplit(path).path == "/v2/positions/DECK"
    ] == ["/v2/positions/DECK"]
    restarted.close()


def test_restart_honors_a_tighter_cap_and_refuses_other_changes(tmp_path, monkeypatch, capsys):
    book, broker, journal, _calls = _book(tmp_path, monkeypatch)
    broker.state["clock"]["is_open"] = False
    assert book.tick() == "WAITING"
    journal.close()
    script = _earnings_script()

    def models(method, url, headers, payload=None, timeout=5):
        return {"models": [{"id": JEV_MODEL}]}

    monkeypatch.setenv("ALPACA_API_KEY", "paper-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "paper-secret")
    monkeypatch.setenv("TYPESAFE_API_KEY", "model-key")
    monkeypatch.setenv("ATHENA_EARNINGS_UNIVERSE", str(tmp_path / "universe_75.txt"))
    monkeypatch.setenv("ATHENA_EARNINGS_PER_TRADE_RISK", "10")
    monkeypatch.setenv("ATHENA_EARNINGS_TOTAL_RISK", "10")
    monkeypatch.setattr(script.LivePaperAPI, "from_env", lambda: broker)
    monkeypatch.setattr(script, "request_json", models)
    code = script.main([
        "--authority", "PAPER", "--journal", str(tmp_path / "book.sqlite"), "--preflight",
    ])
    assert code == 0
    reported = json.loads(capsys.readouterr().out)
    assert reported["per_trade_risk"] == 10
    assert reported["total_risk"] == 10

    universe = str(tmp_path / "universe_75.txt")
    tightened = resolve_restart_policy(
        EarningsPolicy(universe), EarningsPolicy(universe, per_trade_risk=10, total_risk=10),
    )
    journal = PaperJournal(tmp_path / "book.sqlite")
    broker.state["clock"]["is_open"] = True
    broker.state["clock"]["timestamp"] = NOW.isoformat()
    book = EarningsBook(broker, JevDecisionEngine("fixture-key", transport=lambda *a, **k: jev_response()),
                        journal, tightened, calendar_transport=nasdaq())
    assert book.tick() == "ENTRY_SUBMITTED"
    assert _posts(broker)[-1]["qty"] == "5"
    assert journal.last("policy_tightened")["policy"]["per_trade_risk"] == 10
    journal.close()

    with pytest.raises(ValueError, match="loosen"):
        resolve_restart_policy(
            EarningsPolicy(universe, per_trade_risk=10, total_risk=10), EarningsPolicy(universe),
        )
    with pytest.raises(ValueError, match="feed"):
        resolve_restart_policy(EarningsPolicy(universe), EarningsPolicy(universe, feed="sip"))
    monkeypatch.setenv("ATHENA_FEED", "sip")
    monkeypatch.delenv("ATHENA_EARNINGS_PER_TRADE_RISK", raising=False)
    monkeypatch.delenv("ATHENA_EARNINGS_TOTAL_RISK", raising=False)
    code = script.main([
        "--authority", "PAPER", "--journal", str(tmp_path / "book.sqlite"), "--preflight",
    ])
    assert code == 2
    assert "feed" in capsys.readouterr().err


def test_order_is_not_submitted_after_the_entry_deadline(tmp_path, monkeypatch):
    book, broker, journal, _calls = _book(tmp_path, monkeypatch)
    broker.state["clock"]["timestamp"] = "2026-10-13T13:59:59+00:00"

    def bars(symbol, start, end, timeframe, feed):
        if timeframe == "1Day":
            return [{"t": "2026-10-12T20:00:00Z", "o": 100, "h": 103, "l": 99, "c": 100, "v": 2_500_000}]
        return [{
            "t": "2026-10-13T13:58:00+00:00", "o": 103.6, "h": 104.2, "l": 103.4, "c": 104.0, "v": 12000,
        }]

    def late(*args, **kwargs):
        broker.state["clock"]["timestamp"] = "2026-10-13T14:00:01+00:00"
        return jev_response()

    broker.bars = bars
    book.jev = JevDecisionEngine("fixture-key", transport=late)
    assert book.tick() == "SESSION_BLOCKED"
    assert _posts(broker) == []
    assert journal.last("entry_intent") is None
    assert journal.last("adjudication")["receipt"]["accepted"] is True
    journal.close()


def test_daily_loss_halt_expires_and_an_operator_halt_does_not(tmp_path, monkeypatch):
    book, broker, journal, _calls = _book(tmp_path, monkeypatch)
    broker.state["account"]["equity"] = "99500"
    assert book.tick() == "ENTRIES_BLOCKED"
    assert journal.last("entries_halt")["reason"] == "DAILY_LOSS_LIMIT"
    assert journal.last("entries_halt")["session"] == "2026-10-13"
    assert _posts(broker) == []
    broker.state["account"]["equity"] = "100000"
    broker.state["clock"]["timestamp"] = "2026-10-14T13:40:05+00:00"
    broker.state["clock"]["next_close"] = "2026-10-14T20:00:00Z"
    assert book.tick() == "NO_CANDIDATE"
    journal.close()
    restarted = PaperJournal(tmp_path / "book.sqlite")
    book = EarningsBook(
        broker, JevDecisionEngine("fixture-key", transport=lambda *a, **k: jev_response()),
        restarted, EarningsPolicy(str(tmp_path / "universe_75.txt")), calendar_transport=nasdaq(),
    )
    assert book.tick() == "NO_CANDIDATE"
    restarted.close()

    root = tmp_path / "operator"
    book, broker, journal, _calls = _book(tmp_path, monkeypatch, folder=root)
    book.request_flatten_owned()
    broker.state["clock"]["timestamp"] = "2026-10-14T13:40:05+00:00"
    broker.state["clock"]["next_close"] = "2026-10-14T20:00:00Z"
    assert book.tick() == "ENTRIES_BLOCKED"
    journal.close()
    restarted = PaperJournal(root / "book.sqlite")
    book = EarningsBook(
        broker, None, restarted, EarningsPolicy(str(root / "universe_75.txt")),
        calendar_transport=nasdaq(),
    )
    assert book.tick() == "ENTRIES_BLOCKED"
    restarted.close()


def test_news_refreshes_after_an_empty_premarket_pull(tmp_path, monkeypatch):
    book, broker, journal, _calls = _book(tmp_path, monkeypatch)
    pulls = {"n": 0}
    headline = normalize_news_page(realistic_news())
    headline[0]["created_at"] = "2026-10-13T13:10:00Z"

    def news(symbols, start, end):
        pulls["n"] += 1
        broker.news_calls.append((list(symbols), start.isoformat()))
        if pulls["n"] == 1:
            return []
        return headline

    broker.news = news
    broker.state["clock"]["is_open"] = False
    broker.state["clock"]["timestamp"] = "2026-10-13T12:50:00+00:00"
    assert book.tick() == "WAITING"
    broker.state["clock"]["timestamp"] = "2026-10-13T13:15:00+00:00"
    assert book.tick() == "WAITING"
    assert pulls["n"] == 2
    broker.state["clock"]["is_open"] = True
    broker.state["clock"]["timestamp"] = NOW.isoformat()
    assert book.tick() == "ENTRY_SUBMITTED"
    assert pulls["n"] == 3
    assert journal.last("news_fed")["news"] == "confirmed"
    assert journal.last("news_fed")["items"][0]["headline"].startswith("Deckers Outdoor")
    assert sum(event["kind"] == "news_context" for event in journal.events) == 3
    journal.close()


def test_earnings_entry_stops_when_intraday_reserved_the_symbol(tmp_path, monkeypatch):
    intraday = PaperJournal(tmp_path / "athena-state" / "2026-10-13.sqlite")
    intraday.append("entry_intent", order={
        "client_order_id": "athp-deck", "symbol": "DECK", "side": "buy", "qty": "1",
        "limit_price": "100", "stop_loss": {"stop_price": "99"},
    })
    intraday.close()
    book, broker, journal, calls = _book(tmp_path, monkeypatch)
    assert book.tick() == "SHARED_RISK_BLOCKED"
    assert calls["n"] == 1
    assert _posts(broker) == []
    assert journal.last("opportunity")["reason"] == "SYMBOL_ALREADY_RESERVED"
    assert journal.last("entry_intent") is None
    journal.close()


def test_empty_locked_intraday_journal_does_not_block_earnings_entry(tmp_path, monkeypatch):
    """An open intraday runner with no reservation must not stop an earnings entry."""
    state = tmp_path / "athena-state"
    state.mkdir()
    ready, release = tmp_path / "ready", tmp_path / "release"
    script = """
import os, time
from pathlib import Path
from athena_trading.paper.journal import PaperJournal
journal = PaperJournal(Path(os.environ["HELD"]))
journal.append("binding", binding={"arm": "intraday"})
Path(os.environ["READY"]).write_text("up")
deadline = time.time() + 30
while not Path(os.environ["RELEASE"]).exists():
    if time.time() > deadline:
        break
    time.sleep(0.02)
journal.close()
"""
    env = os.environ.copy()
    env.update(HELD=str(state / "2026-10-13.sqlite"), READY=str(ready), RELEASE=str(release))
    env["PYTHONPATH"] = os.pathsep.join(["src", env.get("PYTHONPATH", "")])
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        cwd=str(Path(__file__).resolve().parents[1]), env=env,
    )
    try:
        deadline = time.time() + 20
        while not ready.exists():
            if time.time() > deadline or proc.poll() is not None:
                raise AssertionError("intraday peer did not become ready")
            time.sleep(0.02)
        book, broker, journal, _calls = _book(tmp_path, monkeypatch)
        assert book.tick() == "ENTRY_SUBMITTED"
        assert _posts(broker)
    finally:
        release.write_text("go")
        proc.wait(timeout=20)
        if "journal" in locals():
            journal.close()


def test_earnings_entry_sees_an_intraday_reservation_while_that_journal_is_open(
    tmp_path, monkeypatch,
):
    held = PaperJournal(tmp_path / "athena-state" / "2026-10-13.sqlite")
    held.append("entry_intent", order={
        "client_order_id": "athp-deck", "symbol": "DECK", "side": "buy", "qty": "1",
        "limit_price": "100", "stop_loss": {"stop_price": "99"},
    })
    book, broker, journal, _calls = _book(tmp_path, monkeypatch)
    assert book.tick() == "SHARED_RISK_BLOCKED"
    assert journal.last("opportunity")["reason"] == "SYMBOL_ALREADY_RESERVED"
    assert _posts(broker) == []
    held.close()
    journal.close()


def _operator_halt(events):
    return any(
        event["kind"] == "entries_halt" and event.get("reason") == "OPERATOR_FLATTEN"
        for event in events
    )


def test_operator_flatten_persists_after_a_prior_session_daily_halt(tmp_path, monkeypatch):
    """An older daily-loss halt must not swallow the operator halt."""
    book, broker, journal, _calls = _book(tmp_path, monkeypatch)
    journal.append(
        "entries_halt", reason="DAILY_LOSS_LIMIT", session="2026-10-12",
        at=datetime(2026, 10, 12, 19, tzinfo=UTC),
    )
    book.request_flatten_owned()
    assert _operator_halt(journal.events)
    assert book.tick() == "ENTRIES_BLOCKED"
    assert _posts(broker) == []
    journal.close()

    restarted_journal = PaperJournal(tmp_path / "book.sqlite")
    restarted = EarningsBook(
        broker, JevDecisionEngine("fixture-key", transport=lambda *a, **k: jev_response()),
        restarted_journal, EarningsPolicy(str(tmp_path / "universe_75.txt")),
        calendar_transport=nasdaq(),
    )
    assert restarted.tick() == "ENTRIES_BLOCKED"
    assert _posts(broker) == []
    broker.state["clock"]["timestamp"] = "2026-10-14T13:40:05Z"
    broker.state["clock"]["next_close"] = "2026-10-14T20:00:00Z"
    assert restarted.tick() == "ENTRIES_BLOCKED"
    assert _posts(broker) == []
    restarted_journal.close()


def test_cli_flatten_owned_records_operator_halt_after_a_prior_daily_loss(tmp_path, monkeypatch):
    book, broker, journal, _calls = _book(tmp_path, monkeypatch)
    journal.append(
        "entries_halt", reason="DAILY_LOSS_LIMIT", session="2026-10-12",
        at=datetime(2026, 10, 12, 19, tzinfo=UTC),
    )
    journal.close()
    script = _earnings_script()
    real_book = script.EarningsBook

    def book_with_calendar(*args, **kwargs):
        kwargs["calendar_transport"] = nasdaq()
        return real_book(*args, **kwargs)

    monkeypatch.setenv("ALPACA_API_KEY", "paper-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "paper-secret")
    monkeypatch.setenv("ATHENA_EARNINGS_UNIVERSE", str(tmp_path / "universe_75.txt"))
    monkeypatch.setattr(script, "EarningsBook", book_with_calendar)
    monkeypatch.setattr(script.LivePaperAPI, "from_env", lambda: broker)
    monkeypatch.setattr(script.time, "sleep", lambda *_args: signal.raise_signal(signal.SIGTERM))
    previous = signal.getsignal(signal.SIGTERM)
    try:
        code = script.main([
            "--authority", "PAPER", "--journal", str(tmp_path / "book.sqlite"),
            "--flatten-owned",
        ])
    finally:
        signal.signal(signal.SIGTERM, previous)
    assert code == 0
    assert _posts(broker) == []
    reopened = PaperJournal(tmp_path / "book.sqlite")
    try:
        assert _operator_halt(reopened.events)
        resumed = EarningsBook(
            broker, JevDecisionEngine("fixture-key", transport=lambda *a, **k: jev_response()),
            reopened, EarningsPolicy(str(tmp_path / "universe_75.txt")),
            calendar_transport=nasdaq(),
        )
        assert resumed.tick() == "ENTRIES_BLOCKED"
        broker.state["clock"]["timestamp"] = "2026-10-14T13:40:05Z"
        broker.state["clock"]["next_close"] = "2026-10-14T20:00:00Z"
        assert resumed.tick() == "ENTRIES_BLOCKED"
        assert _posts(broker) == []
    finally:
        reopened.close()


def _both_reports():
    def transport(method, url, headers, payload=None, timeout=5):
        body = nasdaq()(method, url, headers, payload, timeout)
        if "date=2026-10-13" in url:
            body["data"]["rows"].append(
                {"symbol": "CROX", "time": "time-pre-market", "name": "Crocs", "epsForecast": "$2"},
            )
        return body
    return transport


def _occupy(broker, client_order_id, *, stop_status="held"):
    parent = broker.parents[client_order_id]
    symbol = parent["symbol"]
    qty = parent["qty"]
    suffix = "000000000001" if symbol == "DECK" else "000000000002"
    parent.update(
        status="filled", filled_qty=qty, filled_avg_price=parent["limit_price"],
        filled_at="2026-10-13T13:40:04.880000Z",
    )
    take = _leg(
        client_order_id + "-tp", id="11111111-1111-4111-8111-" + suffix, symbol=symbol,
        qty=qty, status="new", type="limit", order_type="limit", limit_price="108.00",
        stop_price=None,
    )
    stop = _leg(
        client_order_id + "-stop", id="22222222-2222-4222-8222-" + suffix, symbol=symbol,
        qty=qty, status=stop_status, type="stop", order_type="stop", limit_price=None,
        stop_price="102.00",
    )
    parent["legs"] = [take, stop]
    broker.state["positions"] = [
        item for item in broker.state["positions"] if item.get("symbol") != symbol
    ]
    broker.state["positions"].append({
        "symbol": symbol, "qty": qty, "side": "long", "asset_class": "us_equity",
        "avg_entry_price": parent["limit_price"],
    })
    return parent


def _open_two_symbols(tmp_path, monkeypatch):
    universe = tmp_path / "universe_75.txt"
    universe.write_text("DECK\nCROX\n")
    journal = PaperJournal(tmp_path / "book.sqlite")
    broker = BookBroker()
    policy = EarningsPolicy(str(universe), max_new_entries_per_day=2)
    book = EarningsBook(
        broker, JevDecisionEngine("fixture-key", transport=lambda *a, **k: jev_response()),
        journal, policy, calendar_transport=_both_reports(),
    )
    assert book.tick() == "ENTRY_SUBMITTED"
    deck_id = _posts(broker)[0]["client_order_id"]
    _occupy(broker, deck_id)
    assert book.tick() == "ENTRY_SUBMITTED"
    crox_id = _posts(broker)[1]["client_order_id"]
    _occupy(broker, crox_id, stop_status="canceled")
    for client_order_id in (deck_id, crox_id):
        for leg in broker.parents[client_order_id]["legs"]:
            leg["status"] = "canceled"
    broker.state["orders"] = []
    return book, broker, journal, deck_id, crox_id


def _lose_deck_close(broker):
    """Broker accepts the DECK close, then the response never reaches the book."""
    original = broker.call
    lost = {"order": None}

    def call(method, path, payload=None):
        if method == "DELETE" and urlsplit(path).path == "/v2/positions/DECK" and lost["order"] is None:
            order = original(method, path, payload)
            lost["order"] = copy.deepcopy(order)
            broker.state["orders"].append(copy.deepcopy(order))
            raise ModelError("timeout")
        return original(method, path, payload)

    broker.call = call
    return lost


def test_lost_close_response_waits_and_still_protects_the_other_symbol(tmp_path, monkeypatch):
    book, broker, journal, deck_id, crox_id = _open_two_symbols(tmp_path, monkeypatch)
    lost = _lose_deck_close(broker)
    with pytest.raises(ModelError, match="timeout"):
        book.tick()
    assert journal.last("close_intent")["client_order_id"] == deck_id
    assert not any(
        event["kind"] == "close_ack" and event.get("client_order_id") == deck_id
        for event in journal.events
    )
    assert lost["order"]["id"]
    deck_deletes = [
        urlsplit(path).path for method, path, _payload in broker.calls
        if method == "DELETE" and urlsplit(path).path == "/v2/positions/DECK"
    ]
    assert deck_deletes == ["/v2/positions/DECK"]
    journal.close()

    restarted_journal = PaperJournal(tmp_path / "book.sqlite")
    restarted = EarningsBook(
        broker, None, restarted_journal, book.policy, calendar_transport=_both_reports(),
    )
    assert restarted.tick() == "FLATTENING"
    assert any(
        event["kind"] == "close_ack" and event.get("client_order_id") == deck_id
        and event["order"]["id"] == lost["order"]["id"]
        for event in restarted_journal.events
    )
    assert [
        urlsplit(path).path for method, path, _payload in broker.calls
        if method == "DELETE" and urlsplit(path).path == "/v2/positions/DECK"
    ] == ["/v2/positions/DECK"]
    assert not any(
        method == "DELETE" and lost["order"]["id"] in path
        for method, path, _payload in broker.calls
    )
    assert any(
        method == "DELETE" and urlsplit(path).path == "/v2/positions/CROX"
        for method, path, _payload in broker.calls
    )
    assert restarted_journal.last("trade_exit")["client_order_id"] == crox_id
    assert restarted_journal.last("trade_exit")["reason"] == "PROTECTION_MISSING"
    restarted_journal.close()


def test_uncertain_close_does_not_block_or_adopt_unrelated_orders(tmp_path, monkeypatch):
    book, broker, journal, deck_id, _crox_id = _open_two_symbols(tmp_path, monkeypatch)
    lost = _lose_deck_close(broker)
    with pytest.raises(ModelError, match="timeout"):
        book.tick()
    extra = {
        "id": "c0ffee00-0000-4000-8000-000000000099",
        "client_order_id": "broker-close-extra", "symbol": "DECK", "qty": "19",
        "filled_qty": "0", "side": "sell", "type": "market", "order_class": "simple",
        "time_in_force": "day", "status": "new", "extended_hours": False,
    }
    unrelated = {
        "id": "abababab-0000-4000-8000-0000000000ab",
        "client_order_id": "manual-limit", "symbol": "DECK", "qty": "1",
        "filled_qty": "0", "side": "sell", "type": "limit", "order_class": "simple",
        "time_in_force": "day", "status": "new", "limit_price": "110.00",
    }
    broker.state["orders"] = [copy.deepcopy(lost["order"]), extra, unrelated]
    journal.close()
    restarted_journal = PaperJournal(tmp_path / "book.sqlite")
    restarted = EarningsBook(
        broker, None, restarted_journal, book.policy, calendar_transport=_both_reports(),
    )
    assert restarted.tick() == "FLATTENING"
    assert not any(
        event["kind"] == "close_ack" and event.get("client_order_id") == deck_id
        for event in restarted_journal.events
    )
    deleted = [urlsplit(path).path for method, path, _payload in broker.calls if method == "DELETE"]
    assert "/v2/positions/DECK" in deleted
    assert deleted.count("/v2/positions/DECK") == 1
    assert "/v2/positions/CROX" in deleted
    assert all(extra["id"] not in path and unrelated["id"] not in path for path in deleted)
    restarted_journal.close()


def test_terminal_market_close_fill_is_refreshed_before_the_earnings_outcome(tmp_path, monkeypatch):
    """A zero-fill acknowledgement is not the close. 19 shares from 104 to 106 is $38."""
    book, broker, journal, _calls = _book(tmp_path, monkeypatch)
    assert book.tick() == "ENTRY_SUBMITTED"
    client_order_id = _posts(broker)[0]["client_order_id"]
    fill_bracket(broker, client_order_id)
    for leg in broker.parents[client_order_id]["legs"]:
        leg["status"] = "canceled"
    broker.state["orders"] = []
    assert book.tick() == "FLATTENING"
    assert any(urlsplit(path).path == "/v2/positions/DECK" for method, path, _payload in broker.calls if method == "DELETE")
    close_id = journal.last("close_ack")["order"]["id"]
    broker.state["positions"] = []
    broker.state["orders"] = []
    broker.order_by_id = {
        close_id: {
            "id": close_id, "client_order_id": "broker-close-DECK", "symbol": "DECK",
            "qty": "19", "filled_qty": "0", "filled_avg_price": None, "side": "sell",
            "type": "market", "order_class": "simple", "status": "new",
        },
    }
    original = broker.call

    def call(method, path, payload=None):
        if method == "GET" and path == "/v2/orders/" + close_id:
            return copy.deepcopy(broker.order_by_id[close_id])
        return original(method, path, payload)

    broker.call = call
    assert book.tick() == "FLATTENING"
    book.tick()
    assert journal.last("position_closed") is None
    assert journal.last("earnings_experience") is None
    assert journal.last("learning_recorded") is None
    store = LearningStore(tmp_path / "athena-state")
    try:
        assert store.experiences() == []
    finally:
        store.close()
    journal.close()

    restarted_journal = PaperJournal(tmp_path / "book.sqlite")
    restarted = EarningsBook(
        broker, None, restarted_journal, EarningsPolicy(str(tmp_path / "universe_75.txt")),
        calendar_transport=nasdaq(),
    )
    restarted.tick()
    assert restarted_journal.last("position_closed") is None
    broker.order_by_id[close_id] = {
        "id": close_id, "client_order_id": "broker-close-DECK", "symbol": "DECK",
        "qty": "19", "filled_qty": "19", "filled_avg_price": "106.00", "side": "sell",
        "type": "market", "order_class": "simple", "status": "filled",
    }
    restarted.tick()
    restarted.tick()
    experience = restarted_journal.last("earnings_experience")
    assert experience["client_order_id"] == client_order_id
    assert experience["close_orders"][0]["filled_qty"] == "19"
    assert experience["close_orders"][0]["filled_avg_price"] == "106.00"
    assert restarted_journal.last("learning_recorded")["client_order_ids"] == [client_order_id]
    store = LearningStore(tmp_path / "athena-state")
    try:
        episodes = [item for item in store.experiences() if item["arm"] == "earnings"]
        assert len(episodes) == 1
        assert episodes[0]["result"] != "UNMEASURED"
        assert episodes[0]["gross_pnl"] == "38.00"
        assert episodes[0]["quantity"] == "19"
    finally:
        store.close()
    restarted_journal.close()
