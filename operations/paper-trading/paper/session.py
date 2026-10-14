"""Paper session: ORB-M decisions → halt gate → paper broker.

``run_symbol_session`` remains the strategy. This runner consumes its
sendable episodes, sizes an entry, and will not call ``broker.submit`` if the
constitutional halt ledger vetoes the send. Filled-position management stays
in the engine; this increment submits / cancels / tracks entry orders only.

Authority defaults to ABSENT. PAPER must be granted by the caller. LIVE is
not a value.
"""
from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ..execution.authority import ExecutionAuthority, parse_authority
from ..execution.broker import BrokerAdapter, BrokerError, BrokerOrder, OrderStatus
from ..execution.intent import (
    OrderIntent, PaperDecision, order_intent_from_decision,
)
from ..orb_m.constitution import Constitution, ManagementParameters
from ..orb_m.market import Bar, PriorSession
from ..orb_m.session import SessionRiskState, SymbolSessionResult, run_symbol_session
from ..risk.halt import HaltDecision, RiskHaltGate, send_gated
from .demo import (
    DEMO_CONSTITUTION, DEMO_EQUITY, DEMO_PARAMETERS, DEMO_PRIOR, DEMO_SYMBOL, demo_bars,
)


PAPER_CONFIG_SCHEMA = "athena-orb-m-paper-session-v1"


@dataclass(frozen=True)
class PaperAction:
    decision: PaperDecision
    intent: OrderIntent | None
    halt: HaltDecision
    order: BrokerOrder | None
    bar_minute: int | None = None


@dataclass(frozen=True)
class PaperSessionResult:
    actions: tuple[PaperAction, ...]
    halt_reason: str | None
    authority: ExecutionAuthority
    bars_processed: int = 0
    mode: str = "decisions"

    @property
    def submitted(self) -> tuple[BrokerOrder, ...]:
        return tuple(action.order for action in self.actions if action.order is not None)

    @property
    def blocked(self) -> tuple[PaperAction, ...]:
        return tuple(action for action in self.actions if action.order is None)


def decisions_from_symbol_session(
    symbol: str,
    session: SymbolSessionResult,
    *,
    atr14: float,
) -> tuple[PaperDecision, ...]:
    """Sendable ORB-M episodes, including those the engine skipped on halt.

    PASS / failed quality never become paper decisions. Halt-skipped episodes
    stay in the list so the paper gate can refuse them independently.
    """
    ticker = symbol.strip().upper()
    decisions: list[PaperDecision] = []
    for episode in session.episodes:
        entry = (
            episode.result.entry_price if episode.result is not None
            else episode.signal.signal_close
        )
        decision = PaperDecision(
            ticker, episode.signal, episode.quality, atr14, entry,
        )
        if decision.sendable:
            decisions.append(decision)
    return tuple(decisions)


def run_paper_session(
    decisions: Sequence[PaperDecision],
    *,
    constitution: Constitution,
    parameters: ManagementParameters,
    broker: BrokerAdapter,
    authority: ExecutionAuthority,
    equity: float,
    risk: SessionRiskState | None = None,
) -> PaperSessionResult:
    """Wire ORB-M decisions to a paper broker through the halt gate.

    Under ABSENT authority no intent is built and the broker is not called.
    A halt cancels working (unfilled) entries already submitted in this
    session; filled positions are not auto-flattened here.
    """
    if equity <= 0:
        raise ValueError("equity must be positive")
    if authority is not ExecutionAuthority.PAPER:
        return PaperSessionResult((), "AUTHORITY_ABSENT", authority)

    ledger = risk if risk is not None else SessionRiskState()
    gate = RiskHaltGate(constitution, ledger)
    actions: list[PaperAction] = []

    for decision in decisions:
        if not decision.sendable:
            continue
        halt = gate.inspect()
        if not halt.allowed:
            actions.append(PaperAction(decision, None, halt, None))
            _cancel_working(broker, actions)
            return PaperSessionResult(tuple(actions), halt.reason, authority)
        try:
            intent = order_intent_from_decision(
                decision, constitution, parameters,
                equity=equity, authority=authority,
            )
        except ValueError:
            unsized = HaltDecision(False, "UNSIZED")
            actions.append(PaperAction(decision, None, unsized, None))
            _cancel_working(broker, actions)
            return PaperSessionResult(tuple(actions), "UNSIZED", authority)
        halt, order = send_gated(intent, gate, broker)
        if order is None:
            actions.append(PaperAction(decision, intent, halt, None))
            _cancel_working(broker, actions)
            return PaperSessionResult(tuple(actions), halt.reason, authority)
        ledger.register_open()
        actions.append(PaperAction(decision, intent, halt, order))

    return PaperSessionResult(tuple(actions), None, authority)


def run_orb_m_paper_session(
    bars: Sequence[Bar],
    prior: PriorSession,
    *,
    symbol: str,
    constitution: Constitution,
    parameters: ManagementParameters,
    broker: BrokerAdapter,
    authority: ExecutionAuthority,
    equity: float,
    risk: SessionRiskState | None = None,
) -> PaperSessionResult:
    """Run the ORB-M campaign session, then paper-execute sendable decisions."""
    engine = run_symbol_session(bars, prior, constitution, parameters)
    decisions = decisions_from_symbol_session(symbol, engine, atr14=prior.atr14)
    return run_paper_session(
        decisions,
        constitution=constitution,
        parameters=parameters,
        broker=broker,
        authority=authority,
        equity=equity,
        risk=risk,
    )


def run_dry_run(
    *,
    authority: ExecutionAuthority = ExecutionAuthority.PAPER,
    halt_demo: bool = False,
    broker: BrokerAdapter | None = None,
) -> PaperSessionResult:
    """Deterministic fixture-broker session. No network, no API keys."""
    from .fixture import FixtureBroker

    paper_broker = broker if broker is not None else FixtureBroker()
    risk = SessionRiskState()
    if halt_demo:
        risk = SessionRiskState(
            realized_r=-DEMO_CONSTITUTION.max_daily_loss_r,
            peak_realized_r=0.0,
        )
    return run_orb_m_paper_session(
        demo_bars(), DEMO_PRIOR,
        symbol=DEMO_SYMBOL,
        constitution=DEMO_CONSTITUTION,
        parameters=DEMO_PARAMETERS,
        broker=paper_broker,
        authority=authority,
        equity=DEMO_EQUITY,
        risk=risk,
    )


def load_paper_config(path: str | Path) -> dict:
    """Load the paper-session config. LIVE and non-PAPER environments fail closed."""
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("paper session config must be an object")
    if value.get("schema_version") != PAPER_CONFIG_SCHEMA:
        raise ValueError("unexpected paper session config schema")
    if value.get("environment") != "PAPER":
        raise ValueError("paper session config must declare environment PAPER")
    parse_authority(str(value.get("execution_authority", "ABSENT")))
    if float(value.get("equity", DEMO_EQUITY)) <= 0:
        raise ValueError("equity must be positive")
    return value


def _cancel_working(broker: BrokerAdapter, actions: Sequence[PaperAction]) -> None:
    for action in actions:
        order = action.order
        if order is None or not order.is_working:
            continue
        current = broker.track(order.broker_order_id)
        if current.is_working:
            broker.cancel(order.broker_order_id)


def result_as_dict(result: PaperSessionResult) -> dict:
    """JSON-ready receipt. Not a performance claim."""
    return {
        "schema_version": "athena-orb-m-paper-session-result-v1",
        "execution_authority": result.authority.value,
        "halt_reason": result.halt_reason,
        "submitted": len(result.submitted),
        "blocked": len(result.blocked),
        "bars_processed": result.bars_processed,
        "mode": result.mode,
        "live_trading": False,
        "orders": [
            {
                "broker_order_id": order.broker_order_id,
                "client_order_id": order.client_order_id,
                "status": order.status.value,
                "symbol": order.symbol,
                "side": order.side,
                "quantity": order.quantity,
            }
            for order in result.submitted
        ],
        "blocked_reasons": [
            action.halt.reason for action in result.blocked
        ],
    }


def cancel_order(broker: BrokerAdapter, order_id: str) -> BrokerOrder:
    """Explicit cancel used by tests and the operator. Fails closed on unknown ids."""
    current = broker.track(order_id)
    if current.status is OrderStatus.FILLED:
        raise BrokerError(f"cannot cancel a filled order: {order_id}")
    return broker.cancel(order_id)


def track_order(broker: BrokerAdapter, order_id: str) -> BrokerOrder:
    return broker.track(order_id)
