"""Trading execution package: authority, order intent, broker protocol.

This package does not grant live-money authority. PAPER is the only sendable
value and stays off unless an operator configures it.
"""
from .authority import AuthorityError, ExecutionAuthority, parse_authority, require_paper
from .broker import BrokerAdapter, BrokerError, BrokerOrder, OrderStatus
from .intent import (
    OrderIntent, PaperDecision, client_order_id, order_intent_from_decision, size_shares,
)
