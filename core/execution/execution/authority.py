"""Execution authority. Paper may be granted; live money may not.

AAT / TRAINING evidence keeps its own ``execution_authority: ABSENT`` field and
is not this module. This flag only answers whether the paper loop may send an
order to a paper broker. It defaults to off. ``LIVE`` is not a value.
"""
from __future__ import annotations

from enum import StrEnum


class AuthorityError(ValueError):
    """Raised when an order would require authority that does not exist."""


class ExecutionAuthority(StrEnum):
    ABSENT = "ABSENT"
    PAPER = "PAPER"


def parse_authority(value: str) -> ExecutionAuthority:
    """Parse an operator-supplied authority. ``LIVE`` fails closed."""
    text = str(value).strip().upper()
    if text == "LIVE":
        raise AuthorityError("LIVE execution authority is not available")
    try:
        return ExecutionAuthority(text)
    except ValueError as exc:
        raise AuthorityError(f"unknown execution authority: {value!r}") from exc


def require_paper(authority: ExecutionAuthority) -> None:
    """Orders may be sent only under explicitly granted PAPER authority."""
    if authority is ExecutionAuthority.PAPER:
        return
    raise AuthorityError(
        "execution authority is ABSENT; paper orders are not authorized"
    )
