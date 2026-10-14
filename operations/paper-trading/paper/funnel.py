"""One journal row for each opportunity outcome the books can actually observe."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .journal import PaperJournal

STAGES = frozenset({
    "eligible", "temporarily_ineligible", "rejected", "model_vetoed",
    "budget_limited", "unfilled", "fallback", "executed",
})


def record_opportunity(
    journal: PaperJournal, *, stage: str, reason: str, at: datetime, **fields: Any,
) -> None:
    """Append one funnel fact. The same stage and reason are not repeated for one key."""
    if stage not in STAGES:
        raise ValueError("unknown opportunity stage")
    identity = fields.get("signal_key") or fields.get("signal_at") or fields.get("client_order_id")
    if any(
        event["kind"] == "opportunity" and event.get("stage") == stage
        and event.get("reason") == reason and (
            event.get("signal_key") == identity or event.get("signal_at") == identity
            or event.get("client_order_id") == identity
        )
        for event in journal.events
    ):
        return
    journal.append("opportunity", stage=stage, reason=reason, at=at, **fields)
