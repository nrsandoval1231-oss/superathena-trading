"""Paper broker adapter: fixture submit/cancel/track, Alpaca fail-closed."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from athena_trading.execution.authority import ExecutionAuthority
from athena_trading.execution.broker import BrokerError, OrderStatus
from athena_trading.execution.intent import PaperDecision, order_intent_from_decision
from athena_trading.orb_m.constitution import Constitution, ManagementParameters
from athena_trading.orb_m.market import Bar, PriorSession
from athena_trading.orb_m.session import run_symbol_session
from athena_trading.paper.alpaca import (
    PAPER_API_BASE, AlpacaPaperBroker, AlpacaPaperError, MissingCredentialsError,
)
from athena_trading.paper.fixture import FixtureBroker
from athena_trading.paper.session import cancel_order, track_order

BASE = datetime(2026, 3, 2, 14, 30, tzinfo=UTC)
PARAMS = ManagementParameters(
    pass_below=0.10, standard_above=0.20, high_conviction_above=0.90,
)
PRIOR = PriorSession(
    previous_close=100.0, atr14=2.0,
    average_daily_volume=5_000_000.0,
    average_opening_volume=20_000.0,
)
CONSTITUTION = Constitution(slippage_bps=0.0)


def bar(minute, o, h, low, c, volume=2000.0):
    return Bar(BASE + timedelta(minutes=minute), minute, o, h, low, c, volume)


def _intent():
    bars = []
    for minute in range(15):
        bars.append(bar(minute, 100.0, 101.0 if minute == 3 else 100.5,
                        99.0 if minute == 4 else 99.5, 100.2))
    bars += [
        bar(15, 100.5, 101.2, 100.4, 101.1),
        bar(16, 101.2, 101.4, 101.1, 101.3),
        bar(17, 101.3, 101.5, 98.0, 98.5),
    ]
    result = run_symbol_session(bars, PRIOR, CONSTITUTION, PARAMS)
    episode = next(ep for ep in result.episodes if ep.result is not None)
    decision = PaperDecision(
        "AAPL", episode.signal, episode.quality, PRIOR.atr14, episode.result.entry_price,
    )
    return order_intent_from_decision(
        decision, CONSTITUTION, PARAMS,
        equity=100_000.0, authority=ExecutionAuthority.PAPER,
    )


def test_fixture_submit_cancel_track():
    broker = FixtureBroker()
    intent = _intent()
    submitted = broker.submit(intent)
    assert submitted.status is OrderStatus.NEW
    assert submitted.symbol == "AAPL"
    assert submitted.side == "BUY"
    tracked = track_order(broker, submitted.broker_order_id)
    assert tracked.status is OrderStatus.NEW
    canceled = cancel_order(broker, submitted.broker_order_id)
    assert canceled.status is OrderStatus.CANCELED
    assert broker.track(submitted.broker_order_id).status is OrderStatus.CANCELED
    assert submitted.broker_order_id in broker.cancels


def test_fixture_unknown_order_fails_closed():
    broker = FixtureBroker()
    with pytest.raises(BrokerError, match="unknown order"):
        broker.track("missing")
    with pytest.raises(BrokerError, match="unknown order"):
        broker.cancel("missing")


def test_alpaca_from_env_fails_closed_without_keys(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
    with pytest.raises(MissingCredentialsError, match="required"):
        AlpacaPaperBroker.from_env()


def test_alpaca_constructor_fails_closed_on_blank_keys():
    with pytest.raises(MissingCredentialsError):
        AlpacaPaperBroker("", "secret")
    with pytest.raises(MissingCredentialsError):
        AlpacaPaperBroker("key", "")


def test_alpaca_adapter_rejects_a_non_paper_url():
    with pytest.raises(ValueError, match="paper endpoint"):
        AlpacaPaperBroker("key", "secret", base_url="https://api.alpaca.markets")


def test_alpaca_submit_cancel_track_against_injected_transport():
    intent = _intent()
    calls: list[tuple[str, str, bytes | None]] = []

    def transport(method, url, headers, body):
        calls.append((method, url, body))
        assert url.startswith(PAPER_API_BASE)
        assert headers["APCA-API-KEY-ID"] == "paper-key"
        assert "APCA-API-SECRET-KEY" in headers
        if method == "POST":
            payload = json.loads(body.decode("utf-8"))
            assert payload["symbol"] == "AAPL"
            assert payload["side"] == "buy"
            assert payload["type"] == "market"
            assert payload["time_in_force"] == "day"
            return 200, json.dumps({
                "id": "ord-1",
                "client_order_id": payload["client_order_id"],
                "status": "new",
                "symbol": "AAPL",
                "side": "buy",
                "qty": payload["qty"],
                "filled_qty": "0",
                "filled_avg_price": None,
            }).encode()
        if method == "DELETE":
            return 204, b""
        if method == "GET":
            return 200, json.dumps({
                "id": "ord-1",
                "client_order_id": intent.client_order_id,
                "status": "canceled",
                "symbol": "AAPL",
                "side": "buy",
                "qty": str(intent.quantity),
                "filled_qty": "0",
                "filled_avg_price": None,
            }).encode()
        raise AssertionError(method)

    broker = AlpacaPaperBroker("paper-key", "paper-secret", transport=transport)
    submitted = broker.submit(intent)
    assert submitted.status is OrderStatus.NEW
    assert submitted.broker_order_id == "ord-1"
    canceled = broker.cancel("ord-1")
    assert canceled.status is OrderStatus.CANCELED
    assert [call[0] for call in calls] == ["POST", "DELETE", "GET"]


def test_alpaca_unknown_status_fails_closed():
    def transport(method, url, headers, body):
        return 200, json.dumps({
            "id": "ord-1", "client_order_id": "x", "status": "mystery",
            "symbol": "AAPL", "side": "buy", "qty": "1",
        }).encode()

    broker = AlpacaPaperBroker("paper-key", "paper-secret", transport=transport)
    intent = _intent()
    with pytest.raises(AlpacaPaperError, match="unusable"):
        broker.submit(intent)
