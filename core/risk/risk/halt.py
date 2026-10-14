"""Constitutional halt gate. Refuse before any order is sent.

``SessionRiskState.veto_reason`` already encodes ``max_open_positions``,
``max_daily_loss_r``, and ``max_drawdown_r``. This module is the paper-loop
gate that consults that ledger on every send. It does not invent a second set
of ceilings and it does not wait for a broker reject.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..execution.authority import ExecutionAuthority
from ..execution.broker import BrokerAdapter, BrokerOrder
from ..execution.intent import OrderIntent
from ..orb_m.constitution import Constitution
from ..orb_m.session import SessionRiskState


@dataclass(frozen=True)
class HaltDecision:
    allowed: bool
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.allowed and self.reason is not None:
            raise ValueError("an allowed send cannot carry a halt reason")
        if not self.allowed and not self.reason:
            raise ValueError("a refused send must name the halt reason")


class RiskHaltGate:
    """Fail-closed inspect/authorize against the constitutional ledger."""

    def __init__(self, constitution: Constitution, state: SessionRiskState) -> None:
        self.constitution = constitution
        self.state = state

    def inspect(self, intent: OrderIntent | None = None) -> HaltDecision:
        """Return whether a send is permitted right now.

        ``intent`` is optional so the session can halt before constructing an
        order. When supplied, PAPER authority is required on the intent itself.
        """
        if intent is not None and intent.authority is not ExecutionAuthority.PAPER:
            return HaltDecision(False, "AUTHORITY_ABSENT")
        reason = self.state.veto_reason(self.constitution)
        if reason is not None:
            return HaltDecision(False, reason)
        return HaltDecision(True)

    def authorize_send(self, intent: OrderIntent) -> HaltDecision:
        """Last check before ``broker.submit``. Halt means the order is not sent."""
        return self.inspect(intent)


def send_gated(
    intent: OrderIntent,
    gate: RiskHaltGate,
    broker: BrokerAdapter,
) -> tuple[HaltDecision, BrokerOrder | None]:
    """Submit only after the halt gate allows. The broker is not called on halt."""
    decision = gate.authorize_send(intent)
    if not decision.allowed:
        return decision, None
    return decision, broker.submit(intent)
