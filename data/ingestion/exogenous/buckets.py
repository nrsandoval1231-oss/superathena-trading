"""Frozen quantization for exogenous features.

Precision the strategy cannot act on is precision an Actor can overfit to.  A
headline count of 11 versus 12 is noise; "more than ten overnight stories" is
the part a decision could plausibly turn on.  Every continuous exogenous value
is therefore reduced to a small integer before it reaches a packet.

Bucket edges are frozen constants and part of each compressor's version hash.
Changing an edge changes the compressor version and invalidates prior
snapshots, rather than silently re-scoring them.

``ABSENT`` is distinct from bucket 0.  "No news at all" and "the fewest news
items we bucket" are different facts and must not collide.
"""
from __future__ import annotations

from collections.abc import Sequence

#: Returned when the underlying evidence does not exist for this opportunity.
ABSENT = -1


def bucket(value: float | None, edges: Sequence[float]) -> int:
    """Return the index of the half-open interval ``value`` falls in.

    ``edges`` are ascending lower bounds.  With edges ``(0, 1, 3, 6, 12)`` a
    value of 0 buckets to 0, 2 to 1, 12 to 4, and 400 to 4.

    A value below the first edge clamps to bucket 0 rather than falling out of
    range.  Only ``None`` is ``ABSENT``: on a signed scale such as macro
    surprise, "further below the lowest edge" is still an observation, and
    letting it collide with "no observation at all" would be a lie.
    """
    if value is None:
        return ABSENT
    if not edges:
        raise ValueError("bucket edges must not be empty")
    if list(edges) != sorted(edges):
        raise ValueError("bucket edges must ascend")
    index = 0
    for position, edge in enumerate(edges):
        if value >= edge:
            index = position
        else:
            break
    return index


def ratio_bucket(numerator: float | None, denominator: float | None,
                 edges: Sequence[float]) -> int:
    """Bucket ``numerator / denominator``, treating a zero baseline as absent.

    Coverage baselines are frequently zero -- a name with no trailing news has
    no baseline to be a multiple of -- and dividing by it would either raise or
    invent an infinity.  Absent is the honest answer.
    """
    if numerator is None or not denominator:
        return ABSENT
    return bucket(numerator / denominator, edges)


# --- Frozen edge sets --------------------------------------------------------
# Named so a test can pin them by value.  Do not tune these against outcomes.

COUNT_EDGES = (0.0, 1.0, 3.0, 6.0, 12.0)
"""Item counts: none, one, a few, several, many."""

MINUTES_EDGES = (0.0, 15.0, 60.0, 240.0, 960.0)
"""Minutes since an event: this quarter-hour, this hour, this morning, overnight, stale."""

HOURS_EDGES = (0.0, 2.0, 8.0, 24.0, 72.0)
"""Hours since a filing: just now, this session, overnight, yesterday, older."""

DAYS_EDGES = (0.0, 3.0, 10.0, 30.0, 90.0)
"""Days to a scheduled event: imminent, this week, this month, this quarter, distant."""

DENSITY_EDGES = (0.0, 0.5, 1.0, 2.0, 5.0)
"""Activity as a multiple of the symbol's own trailing baseline."""

RATIO_EDGES = (0.0, 0.2, 0.4, 0.6, 0.8)
"""A bounded 0-1 ratio, such as a bull share of tagged messages."""

SURPRISE_EDGES = (-3.0, -1.0, -0.25, 0.25, 1.0, 3.0)
"""Standardized macro surprise: large miss through large beat."""
