"""The constitution must be immutable and the adaptive surface must be bounded."""
from __future__ import annotations

import pytest

from athena_trading.orb_m import ADAPTIVE_SURFACE, Constitution, ManagementParameters


def test_constitution_freezes_the_fifteen_minute_opening_range():
    assert Constitution().opening_minutes == 15


def test_constitution_defaults_to_the_pessimistic_intrabar_assumption():
    # A result that depends on favorable-first ordering is not a result.
    assert Constitution().intrabar_resolution == "ADVERSE_FIRST"


def test_constitution_rejects_an_optimistic_unknown_resolution():
    with pytest.raises(ValueError, match="intrabar resolution"):
        Constitution(intrabar_resolution="BEST_CASE")


def test_constitution_forbids_holding_past_the_hard_flat():
    with pytest.raises(ValueError, match="hard flat"):
        Constitution(session_deadline_minute=380, hard_flat_minute=370)


def test_opening_range_must_close_before_the_deadline():
    with pytest.raises(ValueError, match="opening range"):
        Constitution(opening_minutes=400)


@pytest.mark.parametrize("field", sorted(ADAPTIVE_SURFACE))
def test_every_advertised_adaptive_field_exists_on_the_parameters(field):
    assert hasattr(ManagementParameters(), field)


def test_evolve_rejects_constitutional_fields():
    with pytest.raises(ValueError, match="not on the adaptive surface"):
        ManagementParameters().evolve(opening_minutes=5)


def test_evolve_rejects_unknown_fields():
    with pytest.raises(ValueError, match="not on the adaptive surface"):
        ManagementParameters().evolve(secret_edge=1.0)


def test_evolve_changes_identity():
    base = ManagementParameters()
    assert base.evolve(peak_retention=0.7).identity_hash != base.identity_hash


def test_trail_stages_must_increase():
    with pytest.raises(ValueError, match="strictly increasing"):
        ManagementParameters(protect_r=1.0, free_trade_r=0.5)


def test_harvests_must_leave_a_runner():
    with pytest.raises(ValueError, match="leave a runner"):
        ManagementParameters(first_harvest_fraction=0.6, momentum_harvest_fraction=0.5)


def test_confidence_thresholds_must_be_ordered():
    with pytest.raises(ValueError, match="thresholds must be increasing"):
        ManagementParameters(pass_below=0.9, standard_above=0.7)


def test_retracement_bands_must_be_ordered():
    with pytest.raises(ValueError, match="retracement bands"):
        ManagementParameters(strong_setup_retracement_max=0.5,
                             moderate_setup_retracement_min=0.3)


def test_deterioration_weights_default_and_are_copied():
    parameters = ManagementParameters()
    assert parameters.deterioration_weights["vwap_loss"] == 1.5
    supplied = {"vwap_loss": 2.0}
    built = ManagementParameters(deterioration_weights=supplied)
    supplied["vwap_loss"] = 99.0
    assert built.deterioration_weights["vwap_loss"] == 2.0


def test_identity_is_stable_across_weight_ordering():
    first = ManagementParameters(deterioration_weights={"a": 1.0, "b": 2.0})
    second = ManagementParameters(deterioration_weights={"b": 2.0, "a": 1.0})
    assert first.identity_hash == second.identity_hash
