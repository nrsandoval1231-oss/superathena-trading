"""Universe selection must be decidable before the campaign window opens."""
from __future__ import annotations

from datetime import date

import pytest

from athena_trading.orb_m.universe import (
    PoolProvenance, SelectionRule, SymbolStatistics, UniverseManifest, select_universe,
)

LOOKBACK = (date(2023, 10, 1), date(2023, 12, 29))
CAMPAIGN = (date(2024, 1, 2), date(2025, 12, 31))


def stats(symbol, dollar_volume=5e8, price=50.0, sessions=60):
    return SymbolStatistics(symbol, sessions, price, dollar_volume, 100_000.0)


def freeze(items, rule=None, provenance=PoolProvenance.POINT_IN_TIME):
    return select_universe(items, rule or SelectionRule(), provenance=provenance,
                           lookback_start=LOOKBACK[0], lookback_end=LOOKBACK[1],
                           campaign_start=CAMPAIGN[0], campaign_end=CAMPAIGN[1])


def test_selects_the_top_names_by_dollar_volume():
    items = [stats(f"S{i:03d}", dollar_volume=1e9 - i * 1e6) for i in range(80)]
    manifest = freeze(items, SelectionRule(universe_size=50))
    assert len(manifest.members) == 50
    assert manifest.members[0] == "S000"


def test_ties_break_on_symbol_so_selection_is_reproducible():
    items = [stats("ZZZ"), stats("AAA"), stats("MMM")]
    assert freeze(items, SelectionRule(universe_size=3)).members == ("AAA", "MMM", "ZZZ")


def test_illiquid_and_cheap_names_are_rejected_and_counted():
    items = [stats("GOOD"), stats("CHEAP", price=2.0),
             stats("THIN", dollar_volume=1e6), stats("SPARSE", sessions=10)]
    manifest = freeze(items, SelectionRule(universe_size=10))
    assert manifest.members == ("GOOD",)
    assert manifest.rejected_counts == {"price": 1, "dollar_volume": 1, "coverage": 1}


def test_lookback_may_not_extend_into_the_campaign_window():
    with pytest.raises(ValueError, match="leaks the outcome into the universe"):
        UniverseManifest(("AAA",), SelectionRule(), PoolProvenance.POINT_IN_TIME,
                         date(2024, 1, 1), date(2024, 6, 1),   # ends mid-campaign
                         date(2024, 1, 2), date(2025, 12, 31), 1, {})


def test_a_current_snapshot_pool_is_recorded_as_biased():
    manifest = freeze([stats("AAA")], provenance=PoolProvenance.CURRENT_SNAPSHOT)
    assert manifest.carries_survivorship_bias
    assert manifest.to_payload()["carries_survivorship_bias"] is True


def test_a_point_in_time_pool_is_not_flagged():
    assert not freeze([stats("AAA")]).carries_survivorship_bias


def test_manifest_hash_changes_with_membership():
    first = freeze([stats("AAA"), stats("BBB")], SelectionRule(universe_size=1))
    second = freeze([stats("BBB"), stats("AAA")], SelectionRule(universe_size=2))
    assert first.identity_hash != second.identity_hash


def test_manifest_hash_is_stable_across_input_ordering():
    items = [stats("AAA", 9e8), stats("BBB", 8e8)]
    assert freeze(items).identity_hash == freeze(list(reversed(items))).identity_hash


def test_duplicate_members_are_rejected():
    with pytest.raises(ValueError, match="duplicates"):
        UniverseManifest(("AAA", "AAA"), SelectionRule(), PoolProvenance.POINT_IN_TIME,
                         *LOOKBACK, *CAMPAIGN, 2, {})


def test_rule_rejects_unregistered_ranking():
    with pytest.raises(ValueError, match="only median_dollar_volume"):
        SelectionRule(rank_by="sharpe")


def test_payload_carries_the_rule_hash_for_audit():
    payload = freeze([stats("AAA")]).to_payload()
    assert payload["rule"]["rule_hash"] == SelectionRule().identity_hash
    assert payload["schema_version"] == "athena-orb-m-universe-v1"
