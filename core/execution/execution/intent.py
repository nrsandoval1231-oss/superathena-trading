"""Order intent derived from an ORB-M decision.

This is not a second strategy. The direction, stop, and R denominator come from
``build_risk_frame``. Sizing applies constitutional ceilings and the action
already chosen by Breakout Quality Score. The intent is sendable only under
PAPER authority.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..athena_adapter.contracts import canonical_hash
from ..orb_m.constitution import BreakoutAction, Constitution, ManagementParameters
from ..orb_m.entry import BreakoutSignal, RiskFrame, build_risk_frame
from ..orb_m.quality import BreakoutQualityResult
from .authority import ExecutionAuthority, require_paper


_ACTION_MULTIPLIER: dict[BreakoutAction, float] = {
    BreakoutAction.PASS: 0.0,
    BreakoutAction.REDUCED: 0.5,
    BreakoutAction.STANDARD: 1.0,
    BreakoutAction.HIGH_CONVICTION: 2.0,
}


@dataclass(frozen=True)
class OrderIntent:
    """A paper entry the broker adapter may submit. Not a live-money order."""

    symbol: str
    side: str
    quantity: int
    order_type: str
    time_in_force: str
    client_order_id: str
    authority: ExecutionAuthority
    signal: BreakoutSignal
    risk_frame: RiskFrame
    action: BreakoutAction

    def __post_init__(self) -> None:
        require_paper(self.authority)
        if not self.symbol or self.symbol != self.symbol.strip().upper():
            raise ValueError("symbol must be a non-empty uppercase ticker")
        if self.side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        if (self.signal.direction == "LONG") != (self.side == "BUY"):
            raise ValueError("side must match the ORB-M signal direction")
        if self.quantity < 1:
            raise ValueError("quantity must be positive")
        if self.order_type != "MARKET":
            raise ValueError("paper V1 sends MARKET entries only")
        if self.time_in_force != "DAY":
            raise ValueError("paper V1 is DAY-only; nothing overnight")
        if not self.client_order_id:
            raise ValueError("client_order_id is required")
        if self.action is BreakoutAction.PASS:
            raise ValueError("PASS is not a sendable intent")

    @property
    def identity_hash(self) -> str:
        return canonical_hash(self)


@dataclass(frozen=True)
class PaperDecision:
    """An ORB-M signal the paper loop may turn into an intent."""

    symbol: str
    signal: BreakoutSignal
    quality: BreakoutQualityResult
    atr14: float
    entry_price: float

    def __post_init__(self) -> None:
        if not self.symbol or self.symbol != self.symbol.strip().upper():
            raise ValueError("symbol must be a non-empty uppercase ticker")
        if self.atr14 <= 0 or self.entry_price <= 0:
            raise ValueError("ATR and entry price must be positive")

    @property
    def sendable(self) -> bool:
        return self.quality.ok and self.quality.action is not BreakoutAction.PASS


def client_order_id(symbol: str, signal: BreakoutSignal) -> str:
    kind = "re" if signal.is_reentry else "in"
    return f"orbm-{symbol}-{signal.direction[0]}-{kind}-{signal.signal_minute}"


def size_shares(
    *,
    equity: float,
    action: BreakoutAction,
    risk_per_share: float,
    entry_price: float,
    constitution: Constitution,
    parameters: ManagementParameters,
) -> int:
    """Shares from base risk, action multiplier, and constitutional caps."""
    if equity <= 0 or risk_per_share <= 0 or entry_price <= 0:
        return 0
    multiplier = min(
        _ACTION_MULTIPLIER[action], parameters.confidence_multiplier_max,
    )
    risk_dollars = equity * parameters.base_risk_fraction * multiplier
    risk_dollars = min(
        risk_dollars, equity * constitution.max_risk_per_trade_fraction,
    )
    shares = int(risk_dollars / risk_per_share)
    max_shares = int(equity * constitution.max_notional_fraction / entry_price)
    return max(0, min(shares, max_shares))


def order_intent_from_decision(
    decision: PaperDecision,
    constitution: Constitution,
    parameters: ManagementParameters,
    *,
    equity: float,
    authority: ExecutionAuthority,
) -> OrderIntent:
    """Translate one ORB-M decision into a sendable paper entry.

    Raises if the decision is not sendable, authority is not PAPER, or sizing
    collapses to zero — those are not orders.
    """
    require_paper(authority)
    if not decision.sendable:
        raise ValueError("ORB-M decision is not sendable")
    frame = build_risk_frame(
        decision.signal, decision.entry_price, decision.atr14, constitution,
    )
    quantity = size_shares(
        equity=equity,
        action=decision.quality.action,
        risk_per_share=frame.risk_per_share,
        entry_price=decision.entry_price,
        constitution=constitution,
        parameters=parameters,
    )
    if quantity < 1:
        raise ValueError("sized quantity is not positive")
    side = "BUY" if decision.signal.direction == "LONG" else "SELL"
    return OrderIntent(
        symbol=decision.symbol,
        side=side,
        quantity=quantity,
        order_type="MARKET",
        time_in_force="DAY",
        client_order_id=client_order_id(decision.symbol, decision.signal),
        authority=authority,
        signal=decision.signal,
        risk_frame=frame,
        action=decision.quality.action,
    )
