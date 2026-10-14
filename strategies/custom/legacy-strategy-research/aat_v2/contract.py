"""Freeze the AAT-V2 claim contract.

The contract is what makes a later result mean something: it fixes the minimum
evidence, the scoring, the arm definitions and the coverage floor *before* any
Actor runs, so a disappointing result cannot be rescued by moving a threshold.

Freezing deliberately requires a **measured** coverage rate, not an intended
one.  Coverage is the number that decides whether the comparison has power at
all: if most opportunities carry no exogenous evidence, arms B through E are the
control arm with extra steps and a null result says nothing about adaptation.
That number cannot be known before the data exists, so this module refuses to
freeze without it.  The refusal is the feature.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..athena_adapter.contracts import canonical_hash
from .arms import assert_treatment_asymmetry

CONTRACT_SCHEMA = "athena-aat-v2-claim-contract-v1"

#: Inherited from V1 and not negotiable downward.  Falling short means
#: insufficient evidence, not a lowered bar.
MINIMUM_PAIRS_FLOOR = 300


class ContractError(ValueError):
    """The contract cannot be frozen as specified."""


def freeze_claim_contract(
    *,
    assignment_hash: str,
    minimum_opportunity_count: int,
    coverage_floor: float,
    measured_coverage: Mapping[str, float],
    required_sources: tuple[str, ...],
    compressor_identity_hash: str,
    actor_identity: Mapping[str, Any],
    arms: Mapping[str, Any],
    scoring_hash: str,
) -> dict[str, Any]:
    """Return a frozen, hashed contract or refuse with a reason.

    ``required_sources`` names the exogenous sources the experiment depends on.
    Only those are held to the floor: a Tier-3 source expected to carry no
    signal should not be able to block a run by being sparse, and pretending
    otherwise would just invite quietly dropping the floor later.
    """
    if not isinstance(minimum_opportunity_count, int) or (
        minimum_opportunity_count < MINIMUM_PAIRS_FLOOR
    ):
        raise ContractError(
            f"minimum_opportunity_count must be at least {MINIMUM_PAIRS_FLOOR}"
        )
    if not isinstance(coverage_floor, (int, float)) or not 0.0 < coverage_floor <= 1.0:
        raise ContractError("coverage_floor must lie in (0, 1]")
    if not isinstance(measured_coverage, Mapping) or not measured_coverage:
        raise ContractError(
            "measured coverage is required; a contract cannot be frozen against "
            "an intended coverage rate"
        )
    if not required_sources:
        raise ContractError("at least one exogenous source must be required")
    for field, value in (
        ("assignment_hash", assignment_hash),
        ("compressor_identity_hash", compressor_identity_hash),
        ("scoring_hash", scoring_hash),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ContractError(f"{field} is required")

    missing = [source for source in required_sources if source not in measured_coverage]
    if missing:
        raise ContractError(f"no measured coverage for required sources {sorted(missing)}")
    thin = sorted(
        source for source in required_sources if measured_coverage[source] < coverage_floor
    )
    if thin:
        raise ContractError(
            f"measured coverage below the {coverage_floor} floor for {thin}; "
            "the comparison would lack power"
        )

    assert_treatment_asymmetry(arms)
    for key in ("model_hash", "prompt_hash", "action_schema_hash", "provider"):
        if not actor_identity.get(key):
            raise ContractError(f"actor identity is missing {key}")

    contract = {
        "schema_version": CONTRACT_SCHEMA,
        "assignment_hash": assignment_hash,
        "minimum_opportunity_count": minimum_opportunity_count,
        "coverage_floor": float(coverage_floor),
        "required_sources": list(required_sources),
        "measured_coverage": {
            source: float(rate) for source, rate in sorted(measured_coverage.items())
        },
        "compressor_identity_hash": compressor_identity_hash,
        "actor_identity": dict(actor_identity),
        "arms": dict(arms),
        "scoring_hash": scoring_hash,
        "partition": "TRAINING_THEN_ONE_TIME_SEALED_HOLDOUT",
        "claim_authorized": False,
        "execution_authority": "ABSENT",
    }
    contract["contract_hash"] = canonical_hash(contract)
    return contract


def write_contract(contract: Mapping[str, Any], path: str | Path) -> dict[str, Any]:
    """Write a frozen contract once.  A frozen artifact is never overwritten."""
    target = Path(path)
    if target.exists():
        raise ContractError("refusing to overwrite a frozen claim contract")
    payload = dict(contract)
    claimed = payload.pop("contract_hash", None)
    if claimed != canonical_hash(payload):
        raise ContractError("contract hash does not match its contents")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(contract, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return dict(contract)


def load_contract(path: str | Path) -> dict[str, Any]:
    """Load a frozen contract, verifying it has not been edited in place."""
    try:
        contract = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError("claim contract is unreadable") from exc
    payload = dict(contract)
    claimed = payload.pop("contract_hash", None)
    if contract.get("schema_version") != CONTRACT_SCHEMA or claimed != canonical_hash(payload):
        raise ContractError("claim contract drift")
    assert_treatment_asymmetry(contract.get("arms", {}))
    return contract
