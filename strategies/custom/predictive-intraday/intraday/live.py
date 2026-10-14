"""One active live-data paper pilot using ORB input and Jev decisions.

One share, one entry per session. This is the intraday execution slice. An
earnings position on the same paper account is not this runner's exposure when
its client order id starts with ``athe-`` or the earnings ledger lists the
symbol. This runner still flattens only its own symbol.

A TAKE_TRADE label clears the gate at p(TAKE_TRADE) >= 0.6 and confidence >= 0.5
unless the operator overrides those floors. Probability mass within 0.02 of 1 is
renormalized before that comparison. At the fallback cutoff, a remembered
TAKE_TRADE is submitted only when the fresh completed bar is still that same
setup. A stale bar records a no-trade. A fresh bar in another direction does
not send the old order; that new setup is judged on its own, and a no-trade is
recorded when it does not qualify. Equivalent repeats of one opening-range
setup do not each spend an adjudication. A malformed Jev answer vetoes that
setup only and is not an approval. Risk, the bracket, and PAPER authority
still apply.
"""
from __future__ import annotations

import math
import os
import random
import re
import time
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from ..athena_adapter.contracts import canonical_hash
from ..athena_adapter.jev import (
    JEV_MODEL, JevDecisionEngine, ModelError, journalable_response, request_json,
)
from ..execution.authority import ExecutionAuthority, require_paper
from ..orb_m.constitution import Constitution
from ..orb_m.entry import build_risk_frame, detect_breakout, freeze_opening_range
from ..orb_m.market import Bar, average_true_range
from ..paper.alpaca import PAPER_API_BASE, AlpacaPaperBroker
from ..paper.funnel import record_opportunity
from ..paper.journal import PaperJournal
from ..paper.ownership import (
    earnings_state_dir, intraday_book, load_ownership_orders, load_ownership_symbols,
    terminal_learning_history,
)
from ..paper.shared_risk import (
    SharedBookBusy, SharedExposureUnreadable, authorize_entry, entry_coordination, other_arm_exposure,
    reflected_exposure,
)

NY = ZoneInfo("America/New_York")
TERMINAL = {"filled", "canceled", "expired", "rejected", "replaced"}
# Alpaca keeps a bracket stop leg in status "held". status=open omits that leg.
PROTECTIVE_STOP_STATUSES = frozenset({"held", "new", "accepted", "pending_new"})
# One attempt plus two retries. Order POSTs are not retried.
BROKER_GET_ATTEMPTS = 3
BROKER_GET_BACKOFF_SECONDS = (0.25, 0.75)


class DataDeferral(Exception):
    """Market data cannot support a new entry yet. Wait; do not halt a flat account."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def normalize_news_page(payload: Any) -> list[dict[str, Any]]:
    """Keep headline, summary, time, source, and symbols. Drop article bodies."""
    if not isinstance(payload, dict) or not isinstance(payload.get("news"), list):
        raise ValueError("news payload is unusable")
    items: list[dict[str, Any]] = []
    for row in payload["news"]:
        if not isinstance(row, dict):
            continue
        headline = row.get("headline")
        if not isinstance(headline, str) or not headline.strip():
            continue
        summary = row.get("summary") if isinstance(row.get("summary"), str) else ""
        created = row.get("created_at") if isinstance(row.get("created_at"), str) else ""
        source = row.get("source") if isinstance(row.get("source"), str) else ""
        raw_symbols = row.get("symbols") if isinstance(row.get("symbols"), list) else []
        item: dict[str, Any] = {
            "headline": headline.strip()[:300],
            "summary": summary.strip()[:500],
            "created_at": created,
            "source": source[:80],
            "symbols": [symbol for symbol in raw_symbols if isinstance(symbol, str)][:12],
        }
        if type(row.get("id")) in {int, str}:
            item["id"] = row["id"]
        items.append(item)
        if len(items) >= 50:
            break
    return items


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return result.astimezone(UTC)


def transient_broker_failure(exc: BaseException) -> bool:
    """Timeouts, HTTP 429, and 5xx are worth another read. Other errors are not."""
    if not isinstance(exc, ModelError):
        return False
    status = getattr(exc, "status", None)
    if status == 429 or (isinstance(status, int) and 500 <= status <= 599):
        return True
    return str(exc) == "request failed: TimeoutError"


def _get_backoff(failed_attempt: int) -> float:
    base = BROKER_GET_BACKOFF_SECONDS[min(failed_attempt, len(BROKER_GET_BACKOFF_SECONDS) - 1)]
    return base + random.uniform(0, 0.25)


def bracket_exit_reason(parent: dict[str, Any], entry_side: str) -> str | None:
    """Name a filled take-profit or stop. Anything else is not a planned bracket exit."""
    legs = parent.get("legs") or []
    if not isinstance(legs, list):
        return None
    for leg in legs:
        if not isinstance(leg, dict) or leg.get("status") != "filled":
            continue
        if leg.get("side") not in {"buy", "sell"} or leg.get("side") == entry_side:
            continue
        if leg.get("type") in {"stop", "stop_limit"}:
            return "STOP_FILLED"
        if leg.get("type") == "limit":
            return "TAKE_PROFIT_FILLED"
    return None


def number(value: Any, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise ValueError("boolean is not a market/account number")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError("invalid market/account number")
    return result


def flatten_order_legs(orders: Any) -> list[dict[str, Any]]:
    """Roll nested bracket legs up so cancel and flat checks see every leg."""
    if not isinstance(orders, list):
        raise ValueError("broker open orders are incomplete")
    visible: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(order: Any) -> None:
        if not isinstance(order, dict):
            return
        order_id = order.get("id")
        if isinstance(order_id, str):
            if order_id in seen:
                return
            seen.add(order_id)
        visible.append(order)
        legs = order.get("legs") or []
        if isinstance(legs, list):
            for leg in legs:
                add(leg)

    for order in orders:
        add(order)
    return visible


def working_orders(orders: Any) -> list[dict[str, Any]]:
    """Open orders plus nested legs, without terminal parents or legs."""
    return [order for order in flatten_order_legs(orders) if order.get("status") not in TERMINAL]


def cancel_targets(orders: list[dict[str, Any]], close_ids: set[str]) -> list[dict[str, Any]]:
    """Cancel a working parent once. Its legs go with it."""
    leg_ids: set[str] = set()
    for order in orders:
        if order.get("status") in TERMINAL:
            continue
        for leg in order.get("legs") or []:
            if isinstance(leg, dict) and isinstance(leg.get("id"), str):
                leg_ids.add(leg["id"])
    return [
        order for order in orders
        if order.get("id") not in close_ids and order.get("id") not in leg_ids
    ]


def protective_stop(
    order: Any, *, symbol: str, entry_side: str, position_qty: float,
) -> bool:
    """True when this order is an opposite-side stop that still covers the position."""
    if not isinstance(order, dict):
        return False
    if order.get("symbol") != symbol or order.get("type") not in {"stop", "stop_limit"}:
        return False
    side = order.get("side")
    if side not in {"buy", "sell"} or side == entry_side:
        return False
    if order.get("status") not in PROTECTIVE_STOP_STATUSES:
        return False
    if order.get("stop_price") in (None, ""):
        return False
    try:
        number(order["stop_price"], positive=True)
    except (TypeError, ValueError):
        return False
    remaining = number(order["qty"]) - number(order.get("filled_qty", "0"))
    return remaining >= abs(position_qty)


@dataclass(frozen=True)
class PilotPolicy:
    symbol: str
    feed: str = "iex"
    actor_model: str = JEV_MODEL  # retained field name for old journal recovery
    max_notional: float = 1000.0
    max_stop_risk: float = 10.0
    max_daily_loss_fraction: float = 0.005
    support_min: float = 0.6
    confidence_min: float = 0.5
    fallback_after_open_minutes: int = 120
    max_adjudications: int = 20
    close_buffer_minutes: int = 15
    max_bar_age_seconds: int = 90
    version: str = "athena-jev-paper-pilot-v3"

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", self.symbol):
            raise ValueError("an explicit uppercase equity symbol is required")
        if self.feed not in {"iex", "sip"} or not self.actor_model.strip():
            raise ValueError("invalid feed or Actor model")
        if not 0 < number(self.max_notional) <= 1000 or not 0 < number(self.max_stop_risk) <= 10:
            raise ValueError("pilot caps are $1,000 notional and $10 initial stop risk")
        if not 0 < number(self.max_daily_loss_fraction) <= 0.005:
            raise ValueError("daily account loss cap must be at most 0.5%")
        if not 0 < number(self.support_min) <= 1 or not 0 < number(self.confidence_min) <= 1:
            raise ValueError("invalid Jev thresholds")
        if (type(self.fallback_after_open_minutes) is not int
                or not 1 <= self.fallback_after_open_minutes <= 300):
            raise ValueError("daily fallback cutoff must be 1 to 300 minutes after the open")
        if type(self.max_adjudications) is not int or not 1 <= self.max_adjudications <= 20:
            raise ValueError("at most 20 adjudications per session")
        if self.close_buffer_minutes < 15 or not 1 <= self.max_bar_age_seconds <= 90:
            raise ValueError("invalid session/freshness policy")


def _configured_float(name: str) -> float | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc


def _configured_int(name: str) -> int | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a whole number of minutes") from exc


def policy_from_environment(symbol: str, feed: str = "iex") -> PilotPolicy:
    """Build the pilot policy from process environment, with the paper defaults."""
    kwargs: dict[str, Any] = {}
    support = _configured_float("ATHENA_JEV_MIN_PTAKE")
    confidence = _configured_float("ATHENA_JEV_MIN_CONFIDENCE")
    cutoff = _configured_int("ATHENA_FALLBACK_AFTER_OPEN_MINUTES")
    if support is not None:
        kwargs["support_min"] = support
    if confidence is not None:
        kwargs["confidence_min"] = confidence
    if cutoff is not None:
        kwargs["fallback_after_open_minutes"] = cutoff
    return PilotPolicy(symbol, feed=feed, **kwargs)


def take_trade_rank(receipt: dict[str, Any]) -> tuple[float, float, float] | None:
    """Score a Jev receipt when its label is TAKE_TRADE.

    The score is confidence times p(TAKE_TRADE). Other labels are not candidates.
    """
    answer = receipt.get("response", {}).get("answers", {}).get("entry_decision")
    if not isinstance(answer, dict) or answer.get("choice") != "TAKE_TRADE":
        return None
    probabilities = answer.get("probabilities")
    checks = receipt.get("probability_checks")
    if isinstance(checks, dict):
        checked = checks.get("entry_decision")
        if isinstance(checked, dict) and isinstance(checked.get("used"), dict):
            probabilities = checked["used"]
    if not isinstance(probabilities, dict):
        return None
    confidence, take = answer.get("confidence"), probabilities.get("TAKE_TRADE")
    if type(confidence) not in (int, float) or type(take) not in (int, float):
        return None
    if not math.isfinite(confidence) or not math.isfinite(take):
        return None
    return (float(confidence) * float(take), float(confidence), float(take))


def _order_from_packet(packet: dict[str, Any]) -> dict[str, Any] | None:
    """Rebuild the bounded bracket from a journaled signal packet."""
    try:
        observations = packet["observations"]
        price = number(observations["latest_completed_close"], positive=True)
        stop = number(observations["risk_stop"], positive=True)
        direction = packet["candidate_direction"]
        symbol = packet["symbol"]
    except (KeyError, TypeError, ValueError):
        return None
    if direction not in ("LONG", "SHORT"):
        return None
    sign = 1 if direction == "LONG" else -1
    risk = abs(price - stop)
    if risk <= 0:
        return None
    return {
        "symbol": symbol, "qty": "1", "side": "buy" if sign == 1 else "sell",
        "type": "limit", "limit_price": f"{price:.2f}", "time_in_force": "day",
        "order_class": "bracket", "extended_hours": False,
        "stop_loss": {"stop_price": f"{stop:.2f}"},
        "take_profit": {"limit_price": f"{price + sign * 2 * risk:.2f}"},
    }


class LivePaperAPI(AlpacaPaperBroker):
    """Extend the existing paper-only adapter with data and position lifecycle calls."""

    def __init__(self, api_key: str, api_secret: str, *, transport=request_json) -> None:
        super().__init__(api_key, api_secret)
        self.http = transport

    def _broker_http(self, method: str, url: str, payload: Any = None) -> Any:
        """Retry broker reads. Order submits and cancels are a single attempt."""
        if method != "GET":
            return self.http(method, url, self._headers(), payload, timeout=5)
        for attempt in range(BROKER_GET_ATTEMPTS):
            try:
                return self.http("GET", url, self._headers(), None, timeout=5)
            except ModelError as exc:
                if attempt + 1 >= BROKER_GET_ATTEMPTS or not transient_broker_failure(exc):
                    raise
                time.sleep(_get_backoff(attempt))
        raise RuntimeError("broker GET retry loop ended without a result")

    def call(self, method: str, path: str, payload: Any = None) -> Any:
        return self._broker_http(method, PAPER_API_BASE + path, payload)

    def bars(self, symbol: str, start: datetime, end: datetime, timeframe: str, feed: str):
        params = {
            "symbols": symbol, "start": start.isoformat(), "end": end.isoformat(),
            "timeframe": timeframe, "feed": feed, "adjustment": "raw", "limit": 10000,
            "sort": "asc",
        }
        result, tokens = [], set()
        for _ in range(20):
            raw = self._broker_http(
                "GET", "https://data.alpaca.markets/v2/stocks/bars?" + urlencode(params),
            )
            result.extend(raw["bars"].get(symbol, []))
            token = raw.get("next_page_token")
            if not token:
                return result
            if token in tokens:
                break
            tokens.add(token)
            params["page_token"] = token
        raise ValueError("incomplete market-data pagination")

    def news(self, symbols: list[str], start: datetime, end: datetime) -> list[dict[str, Any]]:
        """Headlines since ``start``. Rate limits use the same GET retry as bars."""
        cleaned: list[str] = []
        for symbol in symbols:
            if isinstance(symbol, str) and symbol and symbol not in cleaned:
                cleaned.append(symbol)
        if not cleaned:
            return []
        params = {
            "symbols": ",".join(cleaned[:50]),
            "start": start.astimezone(UTC).isoformat(),
            "end": end.astimezone(UTC).isoformat(),
            "limit": "50", "sort": "desc",
        }
        collected: list[dict[str, Any]] = []
        tokens: set[str] = set()
        for _ in range(3):
            raw = self._broker_http(
                "GET", "https://data.alpaca.markets/v1beta1/news?" + urlencode(params),
            )
            collected.extend(normalize_news_page(raw))
            token = raw.get("next_page_token") if isinstance(raw, dict) else None
            if not isinstance(token, str) or not token:
                return collected[:50]
            if token in tokens:
                break
            tokens.add(token)
            params["page_token"] = token
        if collected:
            return collected[:50]
        raise ValueError("incomplete news pagination")

    def snapshot(self) -> dict[str, Any]:
        return {
            "clock": self.call("GET", "/v2/clock"),
            "positions": self.call("GET", "/v2/positions"),
            # nested=false hides a bracket stop while Alpaca keeps that leg "held".
            "orders": working_orders(self.call(
                "GET", "/v2/orders?status=open&nested=true&limit=500",
            )),
            # Buying-power exemptions may use only exposure observed BEFORE this
            # account sample. An order appearing after an older account read is
            # not proof that its cost was deducted from that earlier balance.
            "account": self.call("GET", "/v2/account"),
        }


def signal_packet(
    raw_bars: list[dict[str, Any]], daily: list[dict[str, Any]],
    *, now: datetime, session_open: datetime, policy: PilotPolicy,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Only a fresh completed minute may trigger; no historical catch-up orders."""
    bars, seen = [], set()
    for raw in raw_bars:
        event_at = timestamp(raw["t"])
        if event_at in seen:
            raise ValueError("duplicate market bar")
        seen.add(event_at)
        if event_at < session_open or event_at + timedelta(minutes=1) > now:
            continue
        minute = int((event_at - session_open).total_seconds() // 60)
        if event_at.second or event_at.microsecond:
            raise ValueError("unaligned market bar")
        bars.append(Bar(event_at, minute, *(number(raw[k], positive=True)
                                         for k in ("o", "h", "l", "c")),
                        number(raw["v"])))
    bars.sort(key=lambda b: b.event_at)
    if not bars or bars[-1].minute < 15:
        return None
    age = (now - (bars[-1].event_at + timedelta(minutes=1))).total_seconds()
    if age > policy.max_bar_age_seconds:
        raise DataDeferral("STALE_BAR")
    constitution = Constitution()
    opening_bars = [bar for bar in bars if 0 <= bar.minute < constitution.opening_minutes]
    if len(opening_bars) != constitution.opening_minutes:
        raise DataDeferral("OPENING_RANGE_INCOMPLETE")
    opening = freeze_opening_range(bars, constitution)
    signal = detect_breakout(bars[-1:], opening, constitution)
    if signal is None:
        return None
    prior = sorted((raw for raw in daily if timestamp(raw["t"]).astimezone(NY).date()
                    < session_open.astimezone(NY).date()), key=lambda raw: raw["t"])
    if len({raw["t"] for raw in prior}) != len(prior):
        raise ValueError("duplicate daily bars")
    atr = average_true_range([(number(d["h"], positive=True), number(d["l"], positive=True),
                               number(d["c"], positive=True)) for d in prior])
    frame = build_risk_frame(signal, signal.signal_close, atr, constitution)
    price = signal.signal_close
    sign = 1 if signal.direction == "LONG" else -1
    stop = round(frame.stop_price, 2)
    risk = abs(price - stop)
    if price < constitution.price_min or atr < constitution.atr14_min or risk < 0.02:
        return None
    packet = {
        "strategy": "PREDICTIVE_INTRADAY", "signal_component": "opening_range_breakout",
        "symbol": policy.symbol, "as_of": now.isoformat(),
        "signal_at": bars[-1].event_at.isoformat(), "feed": policy.feed,
        "candidate_direction": signal.direction,
        "context": {"version": "empty-v2", "recent_experiences": [], "validated_rules": []},
        "observations": {
            "breakout": "closed above the opening range" if sign == 1 else
                        "closed below the opening range",
            "bar_direction": "up" if bars[-1].close > bars[-1].open else "down_or_flat",
            "opening_range_high": opening.high, "opening_range_low": opening.low,
            "latest_completed_close": price, "atr14": atr,
            "news": "unavailable", "sector_context": "unavailable",
            "forecast_probability": "unvalidated", "risk_stop": stop,
        },
        "input_hash": canonical_hash({"bars": bars, "daily": prior}),
    }
    order = {
        "symbol": policy.symbol, "qty": "1", "side": "buy" if sign == 1 else "sell",
        "type": "limit", "limit_price": f"{price:.2f}", "time_in_force": "day",
        "order_class": "bracket", "extended_hours": False,
        "stop_loss": {"stop_price": f"{stop:.2f}"},
        "take_profit": {"limit_price": f"{price + sign * 2 * risk:.2f}"},
    }
    return packet, order


def setup_identity(packet: dict[str, Any]) -> tuple[Any, ...]:
    """Opening-range setup, without the completed bar's timestamp.

    A later minute of the same direction, range, price, and stop is the same
    setup. The timestamp stays on the packet for freshness checks.
    """
    observations = packet.get("observations") if isinstance(packet.get("observations"), dict) else {}
    return (
        packet.get("candidate_direction"),
        observations.get("opening_range_high"),
        observations.get("opening_range_low"),
        observations.get("latest_completed_close"),
        observations.get("risk_stop"),
    )


class ActivePaperPilot:
    def __init__(
        self, broker: LivePaperAPI, jev: JevDecisionEngine | None,
        journal: PaperJournal, policy: PilotPolicy, *, session_date: date | None = None, learning=None,
        authority: ExecutionAuthority = ExecutionAuthority.PAPER,
    ) -> None:
        self.broker, self.jev = broker, jev
        self.learning = learning
        self.journal, self.policy = journal, policy
        self.authority = authority
        self.session_date = session_date
        self.daily = None
        self._flat_observations = 0

    def _without_earnings(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """Copy a snapshot with earnings positions and orders removed.

        The raw snapshot stays in the journal. Decisions and flatten use this view.
        """
        positions, orders = intraday_book(
            snapshot.get("positions"), snapshot.get("orders"),
            own_symbol=self.policy.symbol,
            ledger_symbols=load_ownership_symbols(earnings_state_dir()),
        )
        view = dict(snapshot)
        view["positions"] = positions
        view["orders"] = orders
        return view

    def halt(self, reason: str) -> None:
        if not self.journal.last("halt"):
            self.journal.append("halt", reason=reason, at=datetime.now(UTC))

    def _bind(self, snapshot: dict[str, Any]) -> None:
        binding = {"account_id": snapshot["account"]["id"], "policy": asdict(self.policy)}
        previous = self.journal.last("binding")
        if previous:
            stored = previous["binding"]
            same_account = stored.get("account_id") == binding["account_id"]
            stored_policy = stored.get("policy")
            current_policy = binding["policy"]
            # A journal written before a new policy field existed stays resumable.
            same_policy = isinstance(stored_policy, dict) and all(
                current_policy.get(key) == value for key, value in stored_policy.items()
            )
            if not same_account or not same_policy:
                raise ValueError("journal belongs to a different account or policy")
        else:
            book = self._without_earnings(snapshot)
            if book["positions"] or book["orders"]:
                raise ValueError("pilot requires a dedicated, initially flat paper account")
            self.journal.append("binding", binding=binding)

    def _entry(self):
        return self.journal.last("entry_intent")

    def _track_entry(self):
        entry = self._entry()
        if not entry:
            return None
        try:
            parent = self.broker.call(
                "GET", "/v2/orders:by_client_order_id?" +
                urlencode({"client_order_id": entry["order"]["client_order_id"]}),
            )
        except ModelError as exc:
            not_found = getattr(exc, "status", None) == 404 or str(exc) == "HTTP 404"
            if not not_found:
                raise
            if self.journal.last("entry_ack"):
                raise ValueError(
                    "acknowledged entry disappeared; refusing to drop or resend it"
                ) from exc
            return None
        for key in ("client_order_id", "symbol", "side"):
            if parent.get(key) != entry["order"][key]:
                raise ValueError("recovered order does not match the reserved entry")
        if number(parent["qty"]) != 1 or not 0 <= number(parent["filled_qty"]) <= 1:
            raise ValueError("recovered entry quantity mismatch")
        return parent

    def _missing_reserved_order(self, snapshot: dict[str, Any]) -> str:
        """The reserved id was never created. Look twice, then stop. Never resubmit."""
        book = self._without_earnings(snapshot)
        if book["positions"] or book["orders"]:
            raise ValueError("reserved order is missing while exposure remains")
        client_order_id = self._entry()["order"]["client_order_id"]
        if self.journal.last("entry_not_created"):
            return "ENTRY_NOT_CREATED"
        if not self.journal.last("order_lookup_miss"):
            self.journal.append(
                "order_lookup_miss", reason="BROKER_ORDER_NOT_FOUND",
                client_order_id=client_order_id, at=datetime.now(UTC),
            )
            return "ORDER_NOT_FOUND_RECHECK"
        self.journal.append(
            "entry_not_created", reason="BROKER_ORDER_NOT_FOUND",
            client_order_id=client_order_id, at=datetime.now(UTC),
        )
        return "ENTRY_NOT_CREATED"

    def _lookup_parent(self) -> tuple[dict[str, Any] | None, Exception | None]:
        """Fetch the reserved bracket. A lookup error must not block a protective flatten."""
        if not self._entry() or self.journal.last("entry_not_created"):
            return None, None
        try:
            return self._track_entry(), None
        except (ModelError, ValueError) as exc:
            return None, exc

    def _visible_orders(
        self, orders: Any, parent: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Snapshot orders plus still-working legs from the tracked bracket."""
        extras: list[Any] = []
        if parent:
            extras.append(parent)
            legs = parent.get("legs") or []
            if isinstance(legs, list):
                extras.extend(legs)
        combined = [*orders, *extras] if isinstance(orders, list) else orders
        return working_orders(combined)

    def _delete_order(self, order_id: str) -> None:
        """Cancel one order. A finished or already-canceled leg is not a flatten failure."""
        try:
            self.broker.call("DELETE", "/v2/orders/" + order_id)
        except ModelError as exc:
            if getattr(exc, "status", None) not in {404, 422}:
                raise
            self.journal.append("cancel_already_finished", order_id=order_id, status=exc.status)
            return
        self.journal.append("cancel_requested", order_id=order_id)

    def flatten_step(self, snapshot: dict[str, Any]) -> bool:
        """Halt first; cancel entry/exit reservations, then close confirmed exposure."""
        self._bind(snapshot)
        self.halt("FLATTEN_REQUESTED")
        tracked, lookup_error = self._lookup_parent()
        visible = self._visible_orders(snapshot["orders"], tracked)
        positions, visible = intraday_book(
            snapshot["positions"], visible, own_symbol=self.policy.symbol,
            ledger_symbols=load_ownership_symbols(earnings_state_dir()),
        )
        if not self._entry():
            return not positions and not visible
        symbol = self.policy.symbol
        if any(item["symbol"] != symbol for item in positions + visible):
            raise ValueError("unowned exposure is present; refusing account-wide cleanup")
        if self.journal.last("entry_not_created"):
            if positions or visible:
                raise ValueError("exposure remains after a missing-order closeout")
            return True
        close_events = [e for e in self.journal.events if e["kind"] == "close_ack"]
        close_ids = {e["order"]["id"] for e in close_events}
        working = visible
        # After a lost close response, reconcile its broker-created order instead of duplicating it.
        pending_close = self.journal.last("close_intent")
        if pending_close and not any(e["attempt"] == pending_close["attempt"] for e in close_events):
            candidates = [o for o in working if o["symbol"] == symbol
                          and o.get("type") == "market" and o.get("order_class", "simple") == "simple"]
            if len(candidates) == 1:
                self.journal.append("close_ack", order=candidates[0], attempt=pending_close["attempt"])
                close_ids.add(candidates[0]["id"])
        cancelable = cancel_targets(working, close_ids)
        for order in cancelable:
            self._delete_order(order["id"])
        if cancelable or any(o["id"] in close_ids for o in working):
            self._flat_observations = 0
            return False  # cancellation/close acknowledgement is not a fill
        if positions:
            self._flat_observations = 0
            attempts = sum(e["kind"] == "close_intent" for e in self.journal.events)
            if attempts >= 3:
                raise ValueError("close attempts exhausted; exposure remains unresolved")
            self.journal.append("close_intent", attempt=attempts + 1,
                                positions=positions)
            order = self.broker.call("DELETE", "/v2/positions/" + symbol)
            self.journal.append("close_ack", attempt=attempts + 1, order=order)
            return False
        # A possibly accepted entry must be resolved before declaring the account flat.
        if lookup_error is not None:
            raise lookup_error
        parent = tracked
        if parent is None:
            return self._missing_reserved_order(snapshot) == "ENTRY_NOT_CREATED"
        if parent["status"] not in TERMINAL:
            self._delete_order(parent["id"])
            return False
        self._record_terminal_unfilled(parent, timestamp(snapshot["clock"]["timestamp"]))
        self._flat_observations += 1
        if self._flat_observations < 2:
            return False
        history = self.broker.call("GET", "/v2/orders?" + urlencode({
            "status": "all", "after": (timestamp(self._entry()["at"]) - timedelta(seconds=5)).isoformat(),
            "limit": 500, "direction": "asc", "nested": "true",
        }))
        if not isinstance(history, list) or len(history) >= 500:
            raise ValueError("terminal broker order history is incomplete")
        owned_ids = {
            event["order"]["id"] for event in self.journal.events
            if event["kind"] == "close_ack" and isinstance(event.get("order"), dict)
            and isinstance(event["order"].get("id"), str)
        }
        if isinstance(parent.get("id"), str):
            owned_ids.add(parent["id"])
        learning_history = terminal_learning_history(
            history, owned_ids=owned_ids,
            earnings_orders=load_ownership_orders(earnings_state_dir(), snapshot["account"]["id"]),
        )
        self.journal.append(
            "flat_confirmed", parent=parent, snapshot=snapshot,
            order_history=learning_history, account_order_history=history,
        )
        return True

    def _record_terminal_unfilled(self, parent: dict[str, Any], now: datetime) -> None:
        """A timeout or cleanup that ends with no fill is still one funnel outcome."""
        if parent.get("status") not in {"canceled", "expired", "rejected", "replaced"}:
            return
        try:
            filled = number(parent.get("filled_qty"))
        except (TypeError, ValueError):
            return
        if filled != 0:
            return
        entry = self._entry()
        client_order_id = None
        if entry and isinstance(entry.get("order"), dict):
            client_order_id = entry["order"].get("client_order_id")
        if not isinstance(client_order_id, str):
            return
        halt = self.journal.last("halt")
        reason = "ENTRY_TIMEOUT" if halt and halt.get("reason") == "ENTRY_TIMEOUT" else "ENTRY_TERMINATED"
        record_opportunity(
            self.journal, stage="unfilled", reason=reason, at=now, client_order_id=client_order_id,
        )

    def _fallback_due(self, now: datetime, session_open: datetime) -> bool:
        return now >= session_open + timedelta(minutes=self.policy.fallback_after_open_minutes)

    def _remember_take(
        self, day: str, packet: dict[str, Any], order: dict[str, Any],
        confidence: float, take_probability: float, verdict_hash: str,
    ) -> None:
        signal_at = packet["signal_at"]
        if any(event["kind"] == "fallback_candidate" and event["session"] == day
               and event["signal_at"] == signal_at for event in self.journal.events):
            return
        self.journal.append(
            "fallback_candidate", session=day, signal_at=signal_at,
            score=confidence * take_probability, confidence=confidence,
            take_probability=take_probability, verdict_hash=verdict_hash,
            packet=packet, order=order,
        )

    def _recorded_takes(self, day: str) -> list[dict[str, Any]]:
        """TAKE_TRADE labels already journaled, including sessions from before this field."""
        takes: list[dict[str, Any]] = []
        seen: set[str] = set()
        for event in self.journal.events:
            if event["kind"] == "fallback_candidate" and event["session"] == day:
                if event["signal_at"] not in seen:
                    takes.append(event)
                    seen.add(event["signal_at"])
        pending = None
        for event in self.journal.events:
            if event["kind"] == "decision_started" and event.get("session") == day:
                pending = event
            elif event["kind"] == "jev_veto":
                # A bad answer closes that setup. It must not pair with a later receipt.
                pending = None
            elif event["kind"] == "adjudication" and pending is not None:
                rank = take_trade_rank(event["receipt"])
                signal_at = pending.get("packet", {}).get("signal_at")
                if rank is not None and isinstance(signal_at, str) and signal_at not in seen:
                    order = _order_from_packet(pending["packet"])
                    if order is not None:
                        score, confidence, take_probability = rank
                        takes.append({
                            "session": day, "signal_at": signal_at, "score": score,
                            "confidence": confidence, "take_probability": take_probability,
                            "verdict_hash": canonical_hash(event["receipt"]),
                            "packet": pending["packet"], "order": order,
                        })
                        seen.add(signal_at)
                pending = None
        return takes

    def _best_take(self, day: str) -> dict[str, Any] | None:
        takes = self._recorded_takes(day)
        if not takes:
            return None
        return min(takes, key=lambda event: (-event["score"], event["signal_at"]))

    def _peek_fresh(
        self, now: datetime, day: str, session_open: datetime,
    ) -> tuple[tuple[dict[str, Any], dict[str, Any]] | None, DataDeferral | None]:
        calendar = self.broker.call("GET", "/v2/calendar?" + urlencode({
            "start": (now.astimezone(NY).date() - timedelta(days=10)).isoformat(), "end": day,
        }))
        prior_sessions = [item["date"] for item in calendar if item["date"] < day]
        if not prior_sessions:
            raise ValueError("broker calendar unavailable")
        if self.daily is None:
            self.daily = self.broker.bars(
                self.policy.symbol, session_open - timedelta(days=60),
                session_open, "1Day", self.policy.feed,
            )
        prior_dates = [
            timestamp(item["t"]).astimezone(NY).date().isoformat() for item in self.daily
            if timestamp(item["t"]).astimezone(NY).date().isoformat() < day
        ]
        if not prior_dates or max(prior_dates) != max(prior_sessions):
            raise ValueError("prior daily data is stale")
        raw = self.broker.bars(self.policy.symbol, session_open, now, "1Min", self.policy.feed)
        try:
            return signal_packet(
                raw, self.daily, now=now, session_open=session_open, policy=self.policy,
            ), None
        except DataDeferral as deferred:
            return None, deferred

    def _finish_veto(
        self, day: str, now: datetime, session_open: datetime, account: dict[str, Any],
    ) -> str:
        """This setup is declined. A stale remembered take is not sent from here."""
        if self._fallback_due(now, session_open):
            fallback_status = self._submit_fallback(day, now, session_open, account)
            if fallback_status is not None:
                return fallback_status
        return "JEV_VETO"

    def _submit_fallback(
        self, day: str, now: datetime, session_open: datetime, account: dict[str, Any],
    ) -> str | None:
        """Submit only when the fresh bar is still the accepted setup."""
        if self._entry() or self.journal.last("fallback_entry") or self.journal.last("fallback_no_trade"):
            return None
        candidate = self._best_take(day)
        if candidate is None:
            return None
        require_paper(self.authority)
        fresh, error = self._peek_fresh(now, day, session_open)
        remembered = candidate["packet"].get("candidate_direction")
        if error is not None or fresh is None:
            reason = error.reason if error is not None else "NO_CURRENT_SETUP"
            self.journal.append(
                "fallback_no_trade", session=day, at=now, reason=reason,
                remembered_direction=remembered, remembered_signal_at=candidate["signal_at"],
            )
            record_opportunity(
                self.journal, stage="fallback", reason=reason, at=now, signal_at=candidate["signal_at"],
            )
            return "FALLBACK_NO_TRADE"
        packet, order = fresh
        remembered_packet = candidate.get("packet") if isinstance(candidate.get("packet"), dict) else {}
        if packet["candidate_direction"] != remembered or setup_identity(packet) != setup_identity(remembered_packet):
            reason = "DIRECTION_CHANGED" if packet["candidate_direction"] != remembered else "SETUP_CHANGED"
            self.journal.append(
                "fallback_no_trade", session=day, at=now, reason=reason,
                remembered_direction=remembered, current_direction=packet["candidate_direction"],
                remembered_signal_at=candidate["signal_at"], current_signal_at=packet["signal_at"],
            )
            record_opportunity(
                self.journal, stage="fallback", reason=reason, at=now,
                signal_at=candidate["signal_at"],
            )
            return None
        require_paper(self.authority)
        if (order.get("qty") != "1" or order.get("order_class") != "bracket"
                or order.get("extended_hours") is not False or order.get("time_in_force") != "day"):
            raise ValueError("fallback order violates the paper bracket limits")
        price = number(order["limit_price"], positive=True)
        stop = number(order["stop_loss"]["stop_price"], positive=True)
        equity = number(account["equity"], positive=True)
        if price > min(self.policy.max_notional, equity * 0.01, number(account["buying_power"])):
            return "NOTIONAL_BLOCKED"
        if abs(price - stop) > min(self.policy.max_stop_risk, equity * 0.001):
            return "STOP_RISK_BLOCKED"
        if self.learning is not None:
            context = self.learning.context(
                account["id"], self.policy.symbol, packet["candidate_direction"], now,
                asdict(self.policy),
            )
            if context["validated_rules"]:
                if not any(event["kind"] == "learning_veto" and event.get("fallback")
                           for event in self.journal.events):
                    self.journal.append("learning_veto", session=day, packet=packet, fallback=True)
                return "LEARNED_VETO"
        asset = self.broker.call("GET", "/v2/assets/" + self.policy.symbol)
        if (asset.get("status") != "active" or asset.get("tradable") is not True
                or asset.get("class") != "us_equity"):
            return "ASSET_BLOCKED"
        if order["side"] == "sell" and (not asset.get("shortable") or not asset.get("easy_to_borrow")):
            return "SHORT_BLOCKED"
        return self._commit_order(
            order, packet, session_day=day, account_id=account["id"], observed_at=now,
            verdict_hash=candidate["verdict_hash"], allow_stale=False,
            fallback={
                "session": day, "reason": "NO_ORDER_BY_CUTOFF",
                "signal_at": candidate["signal_at"], "score": candidate["score"],
                "confidence": candidate["confidence"],
                "take_probability": candidate["take_probability"],
                "fallback_after_open_minutes": self.policy.fallback_after_open_minutes,
            },
        )

    def _commit_order(
        self, order: dict[str, Any], packet: dict[str, Any], *, session_day: str,
        account_id: str, observed_at: datetime, verdict_hash: str, allow_stale: bool,
        fallback: dict[str, Any] | None,
    ) -> str:
        """Recheck risk, reserve one bracket, then send it. PAPER only."""
        require_paper(self.authority)
        try:
            with entry_coordination(self.journal, account_id):
                return self._commit_order_coordinated(
                    order, packet, session_day=session_day, account_id=account_id,
                    observed_at=observed_at, verdict_hash=verdict_hash,
                    allow_stale=allow_stale, fallback=fallback,
                )
        except (SharedBookBusy, SharedExposureUnreadable) as exc:
            record_opportunity(
                self.journal, stage="rejected", at=observed_at,
                reason="SHARED_BOOK_BUSY" if isinstance(exc, SharedBookBusy) else "SHARED_EXPOSURE_UNREADABLE",
                signal_at=packet.get("signal_at"),
            )
            return "SHARED_RISK_BLOCKED"

    def _commit_order_coordinated(
        self, order: dict[str, Any], packet: dict[str, Any], *, session_day: str,
        account_id: str, observed_at: datetime, verdict_hash: str, allow_stale: bool,
        fallback: dict[str, Any] | None,
    ) -> str:
        raw = self.broker.snapshot()
        current = self._without_earnings(raw)
        current_now = timestamp(current["clock"]["timestamp"])
        if current_now < observed_at:
            raise ValueError("broker clock moved backwards during adjudication")
        if current["account"]["id"] != account_id or current["positions"] or current["orders"]:
            raise ValueError("account changed during adjudication")
        close_at = timestamp(current["clock"]["next_close"])
        if (not current["clock"]["is_open"] or current_now
                >= close_at - timedelta(minutes=self.policy.close_buffer_minutes)):
            return "SESSION_BLOCKED"
        signal_age = (current_now - timestamp(packet["signal_at"]) - timedelta(minutes=1)).total_seconds()
        if not allow_stale and signal_age > self.policy.max_bar_age_seconds:
            return "STALE_AFTER_ADJUDICATION"
        blocked = current["account"].get("status") != "ACTIVE" or any(
            current["account"].get(key) for key in
            ("trading_blocked", "account_blocked", "trade_suspended_by_user")
        )
        if blocked:
            return "ACCOUNT_BLOCKED"
        current_equity = number(current["account"]["equity"], positive=True)
        price = number(order["limit_price"], positive=True)
        stop = number(order["stop_loss"]["stop_price"], positive=True)
        last_equity = number(current["account"]["last_equity"], positive=True)
        if current_equity <= last_equity * (1 - self.policy.max_daily_loss_fraction):
            self.halt("DAILY_LOSS_LIMIT")
            return "COMPLETE"
        too_large = price > min(
            self.policy.max_notional, current_equity * 0.01, number(current["account"]["buying_power"]),
        )
        stop_too_wide = abs(price - stop) > min(self.policy.max_stop_risk, current_equity * 0.001)
        if too_large or stop_too_wide:
            return "RISK_CHANGED"
        try:
            other = other_arm_exposure(
                "intraday", today=current_now.astimezone(NY).date(), account_id=account_id,
            )
        except SharedBookBusy:
            record_opportunity(
                self.journal, stage="rejected", reason="SHARED_BOOK_BUSY", at=current_now,
                signal_at=packet.get("signal_at"),
            )
            return "SHARED_RISK_BLOCKED"
        except SharedExposureUnreadable:
            record_opportunity(
                self.journal, stage="rejected", reason="SHARED_EXPOSURE_UNREADABLE", at=current_now,
                signal_at=packet.get("signal_at"),
            )
            return "SHARED_RISK_BLOCKED"
        reflected_ids, reflected_symbols = reflected_exposure(raw)
        shared = authorize_entry(
            arm="intraday", symbol=str(order["symbol"]), notional=price, stop_risk=abs(price - stop),
            overnight=False, buying_power=number(current["account"]["buying_power"]),
            open_exposure=other, reflected_client_order_ids=reflected_ids,
            reflected_symbols=reflected_symbols,
        )
        if not shared.allowed:
            record_opportunity(
                self.journal, stage="rejected", reason=shared.reason, at=current_now,
                signal_at=packet.get("signal_at"),
            )
            return "SHARED_RISK_BLOCKED"
        if fallback is not None and self.journal.last("fallback_entry") is None:
            self.journal.append("fallback_entry", **fallback, at=current_now)
        reserved = {
            key: (dict(value) if isinstance(value, dict) else value) for key, value in order.items()
        }
        reserved["client_order_id"] = "athp-" + canonical_hash({
            "account": account_id, "session": session_day,
        })[:40]
        self.journal.append(
            "entry_intent", session=session_day, at=current_now, order=reserved,
            packet_hash=canonical_hash(packet), verdict_hash=verdict_hash,
            fallback=fallback is not None,
        )
        # A lost response leaves a durable reservation. Recovery only queries this ID, never resends.
        ack = self.broker.call("POST", "/v2/orders", reserved)
        self.journal.append("entry_ack", order=ack)
        record_opportunity(
            self.journal, stage="eligible", reason="ENTRY_SUBMITTED", at=current_now,
            signal_at=packet.get("signal_at"), client_order_id=reserved["client_order_id"],
        )
        return "ENTRY_SUBMITTED"

    def tick(self) -> str:
        snapshot = self.broker.snapshot()
        self._bind(snapshot)
        now = timestamp(snapshot["clock"]["timestamp"])
        day = now.astimezone(NY).date().isoformat()
        self.journal.append("broker_observation", at=now, snapshot=snapshot)
        snapshot = self._without_earnings(snapshot)
        snapshot["orders"] = working_orders(snapshot["orders"])
        if self.journal.last("flat_confirmed"):
            tracked, lookup_error = self._lookup_parent()
            visible = self._visible_orders(snapshot["orders"], tracked)
            if lookup_error is not None or snapshot["positions"] or visible:
                self.halt("EXPOSURE_AFTER_FLAT")
            else:
                return "COMPLETE"
        if self.journal.last("halt"):
            return "COMPLETE" if self.flatten_step(snapshot) else "FLATTENING"
        clock, account = snapshot["clock"], snapshot["account"]
        if self.session_date is not None and not self._entry() and (
            day != self.session_date.isoformat() or not clock["is_open"]
        ):
            return "COMPLETE"  # the supervisor owns the next session and its journal
        close_at = timestamp(clock["next_close"])
        if not clock["is_open"] or now >= close_at - timedelta(minutes=self.policy.close_buffer_minutes):
            if self._entry():
                self.halt("SESSION_CLOSE")
                return "COMPLETE" if self.flatten_step(snapshot) else "FLATTENING"
            return "MARKET_CLOSED" if not clock["is_open"] else "COMPLETE"
        equity = number(account["equity"], positive=True)
        last_equity = number(account["last_equity"], positive=True)
        if equity <= last_equity * (1 - self.policy.max_daily_loss_fraction):
            self.halt("DAILY_LOSS_LIMIT")
            return "COMPLETE" if self.flatten_step(snapshot) else "FLATTENING"
        entry = self._entry()
        if entry:
            if entry["session"] != day:
                self.halt("PRIOR_SESSION_RECOVERY")
                return "COMPLETE" if self.flatten_step(snapshot) else "FLATTENING"
            if self.journal.last("entry_not_created"):
                if snapshot["positions"] or snapshot["orders"]:
                    raise ValueError("exposure remains after a missing-order closeout")
                return "ENTRY_NOT_CREATED"
            parent = self._track_entry()
            if parent is None:
                return self._missing_reserved_order(snapshot)
            self.journal.append("entry_observation", order=parent)
            qty = number(parent["filled_qty"])
            if parent["status"] == "partially_filled" or (qty > 0 and parent["status"] != "filled"):
                self.halt("PARTIAL_ENTRY")
            elif parent["status"] in {"canceled", "expired", "rejected", "replaced"}:
                record_opportunity(
                    self.journal, stage="unfilled", reason="ENTRY_TERMINATED", at=now,
                    client_order_id=entry["order"].get("client_order_id"),
                )
                self.halt("ENTRY_TERMINATED")
            elif parent["status"] != "filled" and (now - timestamp(entry["at"])).total_seconds() > 60:
                self.halt("ENTRY_TIMEOUT")
            elif parent["status"] == "filled":
                record_opportunity(
                    self.journal, stage="executed", reason="FILLED", at=now,
                    client_order_id=entry["order"].get("client_order_id"),
                )
                positions = snapshot["positions"]
                if any(p["symbol"] != self.policy.symbol for p in positions):
                    raise ValueError("unowned position encountered")
                if not positions:
                    exit_reason = bracket_exit_reason(parent, entry["order"]["side"])
                    if exit_reason is not None and not self.journal.last("bracket_exit"):
                        self.journal.append("bracket_exit", reason=exit_reason, at=datetime.now(UTC))
                    self.halt("POSITION_EXITED")
                else:
                    position = positions[0]
                    expected_sign = 1 if entry["order"]["side"] == "buy" else -1
                    position_qty = number(position["qty"])
                    if position_qty * expected_sign <= 0 or abs(position_qty) > 1:
                        self.halt("POSITION_MISMATCH")
                    else:
                        # status=open omits a bracket stop while that leg is held.
                        legs = parent.get("legs") or []
                        if not isinstance(legs, list):
                            legs = []
                        protected = any(
                            protective_stop(
                                order, symbol=self.policy.symbol,
                                entry_side=entry["order"]["side"], position_qty=position_qty,
                            )
                            for order in (*snapshot["orders"], *legs)
                        )
                        if not protected:
                            self.halt("PROTECTION_MISSING")
            if self.journal.last("halt"):
                return "COMPLETE" if self.flatten_step(snapshot) else "FLATTENING"
            return "POSITION_OPEN" if qty > 0 else "ENTRY_WORKING"
        if snapshot["positions"] or snapshot["orders"]:
            raise ValueError("account is not flat before entry")
        if account.get("status") != "ACTIVE" or any(account.get(k) for k in
            ("trading_blocked", "account_blocked", "trade_suspended_by_user")):
            return "ACCOUNT_BLOCKED"
        calendar = self.broker.call("GET", "/v2/calendar?" + urlencode({
            "start": (now.astimezone(NY).date() - timedelta(days=10)).isoformat(), "end": day,
        }))
        current_session = [item for item in calendar if item["date"] == day]
        prior_sessions = [item["date"] for item in calendar if item["date"] < day]
        if len(current_session) != 1 or not prior_sessions:
            raise ValueError("broker calendar unavailable")
        session_open = datetime.fromisoformat(day + "T" + current_session[0]["open"]).replace(tzinfo=NY)
        if self._fallback_due(now, session_open):
            fallback_status = self._submit_fallback(day, now, session_open, account)
            if fallback_status is not None:
                return fallback_status
        if self.daily is None:
            self.daily = self.broker.bars(self.policy.symbol, session_open - timedelta(days=60),
                                          session_open, "1Day", self.policy.feed)
        prior_dates = [timestamp(item["t"]).astimezone(NY).date().isoformat()
                       for item in self.daily if timestamp(item["t"]).astimezone(NY).date().isoformat() < day]
        if not prior_dates or max(prior_dates) != max(prior_sessions):
            raise ValueError("prior daily data is stale")
        raw = self.broker.bars(self.policy.symbol, session_open, now, "1Min", self.policy.feed)
        try:
            candidate = signal_packet(
                raw, self.daily, now=now, session_open=session_open, policy=self.policy,
            )
        except DataDeferral as deferred:
            return deferred.reason
        if candidate is None:
            return "WAITING_FOR_SIGNAL"
        packet, order = candidate
        attempts = [e for e in self.journal.events if e["kind"] == "decision_started" and e["session"] == day]
        if any(e["signal_at"] == packet["signal_at"] for e in attempts):
            return "ALREADY_REVIEWED"
        setup_key = canonical_hash({
            "direction": packet["candidate_direction"],
            "opening_range_high": packet["observations"]["opening_range_high"],
            "opening_range_low": packet["observations"]["opening_range_low"],
        })
        same_setup = [event for event in attempts if event.get("setup_key") == setup_key]
        if len(same_setup) >= 2:
            record_opportunity(
                self.journal, stage="temporarily_ineligible", reason="EQUIVALENT_SETUP", at=now,
                signal_at=packet["signal_at"],
            )
            return "ALREADY_REVIEWED"
        distinct = {event.get("setup_key") for event in attempts if event.get("setup_key")}
        legacy = sum(1 for event in attempts if not event.get("setup_key"))
        if not same_setup and len(distinct) + legacy >= self.policy.max_adjudications:
            record_opportunity(
                self.journal, stage="budget_limited", reason="ADJUDICATION_BUDGET", at=now,
                signal_at=packet["signal_at"],
            )
            return "ADJUDICATION_BUDGET"
        asset = self.broker.call("GET", "/v2/assets/" + self.policy.symbol)
        if asset.get("status") != "active" or asset.get("tradable") is not True or asset.get("class") != "us_equity":
            return "ASSET_BLOCKED"
        if order["side"] == "sell" and (not asset.get("shortable") or not asset.get("easy_to_borrow")):
            return "SHORT_BLOCKED"
        price, stop = number(order["limit_price"], positive=True), number(order["stop_loss"]["stop_price"], positive=True)
        if price > min(self.policy.max_notional, equity * 0.01, number(account["buying_power"])):
            return "NOTIONAL_BLOCKED"
        if abs(price - stop) > min(self.policy.max_stop_risk, equity * 0.001):
            return "STOP_RISK_BLOCKED"
        # Reserve this observation before model calls: restart cannot repeat spend/decisions.
        if self.jev is None:
            raise ModelError("Jev is required for a new entry")
        if self.learning is not None:
            packet["context"] = self.learning.context(account["id"], self.policy.symbol,
                                                       packet["candidate_direction"], now, asdict(self.policy))
            if packet["context"]["validated_rules"]:
                self.journal.append("learning_veto", session=day, packet=packet)
                return "LEARNED_VETO"
        self.journal.append(
            "decision_started", session=day, signal_at=packet["signal_at"], setup_key=setup_key,
            packet=packet, market_inputs={"bars": raw, "daily": self.daily},
        )
        answered = False

        def before_validation(response: Any) -> None:
            nonlocal answered
            answered = True
            self.journal.append(
                "jev_response", session=day, signal_at=packet["signal_at"],
                response=journalable_response(response),
            )

        try:
            verdict = self.jev.decide(packet, before_validation=before_validation)
        except ModelError as exc:
            if not answered:
                raise
            self.journal.append(
                "jev_veto", session=day, signal_at=packet["signal_at"],
                reason=str(exc)[:250], accepted=False,
            )
            record_opportunity(
                self.journal, stage="model_vetoed", reason="JEV_VETO", at=now,
                signal_at=packet["signal_at"],
            )
            return self._finish_veto(day, now, session_open, account)
        self.journal.append("adjudication", receipt=verdict.receipt)
        rank = take_trade_rank(verdict.receipt)
        verdict_hash = canonical_hash(verdict.receipt)
        if verdict.accepted:
            status = self._commit_order(
                order, packet, session_day=day, account_id=account["id"], observed_at=now,
                verdict_hash=verdict_hash, allow_stale=False, fallback=None,
            )
            if status != "ENTRY_SUBMITTED" and rank is not None:
                self._remember_take(day, packet, order, rank[1], rank[2], verdict_hash)
            return status
        if rank is not None:
            self._remember_take(day, packet, order, rank[1], rank[2], verdict_hash)
        record_opportunity(
            self.journal, stage="model_vetoed", reason="JEV_VETO", at=now,
            signal_at=packet["signal_at"],
        )
        return self._finish_veto(day, now, session_open, account)
