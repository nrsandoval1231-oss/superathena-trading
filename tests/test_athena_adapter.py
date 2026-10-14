"""The adapter's canonical hash must stay byte-compatible with Athena Core.

These digests are pinned, not recomputed. Identity hashes produced here travel
into Athena evidence records, so a drift in this function silently breaks
provenance across the domain boundary rather than failing loudly.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from athena_trading.athena_adapter.contracts import canonical_hash, canonical_json


def test_mapping_key_order_does_not_affect_the_digest():
    assert canonical_hash({"a": 1, "b": 2}) == canonical_hash({"b": 2, "a": 1})


def test_sets_are_ordered_deterministically():
    assert canonical_hash(frozenset({"b", "a"})) == canonical_hash(frozenset({"a", "b"}))


def test_naive_timestamps_are_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        canonical_hash(datetime(2026, 1, 1))


def test_non_finite_floats_are_rejected():
    with pytest.raises(ValueError, match="non-finite"):
        canonical_hash(float("inf"))


def test_unsupported_types_are_rejected():
    with pytest.raises(TypeError, match="unsupported canonical value"):
        canonical_hash(object())


def test_canonical_json_is_compact_and_ascii():
    assert canonical_json({"b": 1, "a": "cafe"}) == '{"a":"cafe","b":1}'


@pytest.mark.parametrize("value,expected", [
    ({"a": 1, "b": 2},
     "43258cff783fe7036d8a43033f830adfc60ec037382473548ac742b888292777"),
    ([1, 2.5, "x", True, None],
     "2cb910968617706b862d9a4fe3d5a3d3874c5cd7a6f94c1fceb14d83670e8080"),
])
def test_pinned_digests_match_athena_core(value, expected):
    # Recorded from athena_arena.contracts.canonical_hash. A failure here means
    # the two implementations have diverged, not that this test is stale.
    assert canonical_hash(value) == expected
