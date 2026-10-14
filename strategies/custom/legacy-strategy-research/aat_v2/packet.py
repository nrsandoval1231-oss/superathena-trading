"""The AAT-V2 Actor packet.

One change from V1, and it is the whole experiment: arms B through E carry a
bucketed exogenous feature vector that the deterministic control arm cannot
consume.

The guards here are deliberately symmetric and fail closed in both directions.
A treated arm built without exogenous features silently degrades to a V1 packet
and the run produces a null for the wrong reason; a control arm built *with*
them destroys the comparison outright.  Neither is recoverable after the fact
from a ledger, so both are refused at construction.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..athena_adapter.contracts import canonical_hash
from ..exogenous import feature_keys
from .arms import ArmError, receives_exogenous, receives_memory

PACKET_SCHEMA = "athena-aat-v2-actor-packet-v1"


def build_packet(
    *,
    arm: str,
    opportunity_id: str,
    features: Mapping[str, Any],
    actor_identity: str,
    exogenous_features: Mapping[str, Any] | None = None,
    memory: Sequence[Mapping[str, str]] = (),
) -> dict[str, Any]:
    """Build one packet, refusing any shape that would confound the comparison.

    ``features`` is the V1 price-derived vector, opaque as before.
    ``exogenous_features`` must be exactly the frozen key set from the
    compressors -- a partial vector would let coverage differences masquerade as
    an arm effect.
    """
    if not receives_exogenous(arm) and exogenous_features is not None:
        raise ArmError(f"arm {arm} must not receive exogenous evidence")
    if receives_exogenous(arm):
        if exogenous_features is None:
            raise ArmError(f"arm {arm} requires exogenous evidence and none was supplied")
        expected = set(feature_keys())
        if set(exogenous_features) != expected:
            missing = sorted(expected - set(exogenous_features))
            extra = sorted(set(exogenous_features) - expected)
            raise ArmError(
                f"exogenous feature key drift for arm {arm}: missing={missing} extra={extra}"
            )
    if memory and not receives_memory(arm):
        raise ArmError(f"arm {arm} must not receive memory")
    if not isinstance(opportunity_id, str) or not opportunity_id.strip():
        raise ArmError("opportunity_id is required")

    packet: dict[str, Any] = {
        "schema_version": PACKET_SCHEMA,
        "candidate_hash": opportunity_id,
        "features": dict(features),
        "memory": [dict(item) for item in memory],
        "actor_identity": actor_identity,
    }
    if exogenous_features is not None:
        packet["exogenous"] = dict(exogenous_features)
    return packet


def packet_hash(packet: Mapping[str, Any]) -> str:
    return canonical_hash(packet)


def assert_control_arm_never_saw_treatment(ledger_rows: Sequence[Mapping[str, Any]]) -> None:
    """Audit a completed run: no control-arm row may carry exogenous evidence.

    Construction guards can be bypassed by a caller assembling a packet by hand,
    so the finished ledger gets checked too. This is cheap and it is the last
    place the mistake is still visible.
    """
    for row in ledger_rows:
        arm = row.get("arm")
        if arm is None:
            raise ArmError("ledger row has no arm")
        if not receives_exogenous(arm) and row.get("exogenous_present"):
            raise ArmError(f"control arm {arm} recorded exogenous evidence")
        if receives_exogenous(arm) and row.get("exogenous_present") is False:
            raise ArmError(f"treated arm {arm} recorded no exogenous evidence")


def ledger_projection(packet: Mapping[str, Any], *, arm: str) -> dict[str, Any]:
    """The auditable summary of a packet, without reproducing its contents."""
    return {
        "arm": arm,
        "opportunity_id": packet["candidate_hash"],
        "packet_hash": packet_hash(packet),
        "exogenous_present": "exogenous" in packet,
        "memory_count": len(packet.get("memory", ())),
        "execution_authority": "ABSENT",
    }
