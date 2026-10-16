"""Refuse a replay whose ORB constitution is not the frozen one."""

from __future__ import annotations

from athena_trading.orb_m.constitution import Constitution

from .constants import (
    COMMISSION_PER_SHARE,
    PINNED_CONSTITUTION_HASH,
    SLIPPAGE_BPS,
)
from .types import ConstitutionDrift


def require_constitution(expected: str | None = None) -> Constitution:
    """Return the frozen constitution, or refuse the run.

    ``expected`` is an additional caller pin. The harness pin is always checked.
    The returned object is ``Constitution()`` with no field overrides.
    """
    live = Constitution()
    digest = live.identity_hash
    if digest != PINNED_CONSTITUTION_HASH:
        raise ConstitutionDrift(
            "ORB constitution hash differs from the frozen pin "
            f"{PINNED_CONSTITUTION_HASH}; this harness will not replay a different strategy"
        )
    if expected is not None and expected != digest:
        raise ConstitutionDrift(
            f"refusing replay: constitution hash {expected} != {digest}"
        )
    if live.intrabar_resolution != "ADVERSE_FIRST":
        raise ConstitutionDrift("ORB intrabar resolution is ADVERSE_FIRST")
    if (live.max_initial_attempts_per_direction != 1
            or live.max_reentries_per_direction != 1):
        raise ConstitutionDrift("ORB attempt budget is one initial and one re-entry per direction")
    if live.slippage_bps != SLIPPAGE_BPS or live.commission_per_share != COMMISSION_PER_SHARE:
        raise ConstitutionDrift("ORB research haircut no longer matches paper-cost-scenario-v1")
    return live
