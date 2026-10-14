"""Bounded DeepSeek Flash pilot. Not TRAINING authorization.

Nick authorized a bounded pilot with a new provider-scoped identity. This
module runs a small N-opportunity / N-call harness against that identity under
hard call and spend ceilings. It does not freeze a claim contract, rewrite the
Terra protocol, consume a holdout, or raise ``execution_authority``.

Default transport is fixture / dry. Live spend requires ``allow_live=True``,
``DEEPSEEK_API_KEY``, and explicit ceilings at or below Nick's authorized
bigger-pilot limits (about 500 calls, ``$50.00``). That is not TRAINING.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ..athena_adapter.contracts import canonical_hash
from ..exogenous import feature_keys
from .arms import ACTOR_ARMS, D_ATHENA, E_DELIBERATION
from .deepseek_preflight import (
    DEFAULT_PREFLIGHT_ARMS,
    SINGLE_CALL_OUTPUT_TOKENS,
    DeepSeekPreflightError,
    _assert_no_secret,
    _assistant_content,
    _cost_usd,
    _live_transport,
    _load_preflight_fixture,
    _preflight_worst_case_usd,
    _read_decision,
    _read_usage,
    _require_key,
    _resolve_transport,
    api_key_from_env,
    build_deepseek_payload,
    load_deepseek_pricing,
    load_registered_v2_protocol,
)
from .deliberation import (
    DELIBERATION_OUTPUT_TOKENS,
    DELIBERATION_TURN_ROLES,
    DELIBERATION_TURNS,
    DeliberationError,
    load_e_arm_amendment,
    raw_content_snippet,
    worst_case_compact_payloads,
)
from .identity import (
    COMMITTED_IDENTITY_PATH,
    IDENTITY_STATUS,
    PILOT_PROMPT,
    IdentityError,
    identity_digest,
    load_deepseek_flash_identity,
)
from .packet import build_packet

PILOT_SCHEMA = "athena-aat-v2-deepseek-flash-pilot-v1"
PILOT_STATUS = "PILOT_NOT_TRAINING"

#: Hard fail-closed caps. Nick-authorized bigger live pilot (not TRAINING).
#: B/C/D + four E turns = 7 calls/opportunity; 71 × 7 = 497 calls, under 500.
#: Opportunity hard cap 80 keeps 71 legal and still refuses TRAINING-sized N.
PILOT_OPPORTUNITY_CEILING = 80
PILOT_CALL_CEILING = 500
PILOT_SPEND_CEILING_USD = 50.00

#: Dry / fixture defaults. Live still requires explicit flags and a key.
DEFAULT_PILOT_OPPORTUNITIES = 1
DEFAULT_PILOT_CALL_CEILING = 7
DEFAULT_PILOT_SPEND_CEILING_USD = 1.00

#: Nick-authorized bigger live knobs. Still not TRAINING. Dry CLI stays below.
#: 71 opportunities × (3 Actor + 4 E) = 497 calls, under the 500-call limit.
RECOMMENDED_LIVE_OPPORTUNITIES = 71
RECOMMENDED_LIVE_CALL_CEILING = 500
RECOMMENDED_LIVE_SPEND_CEILING_USD = 50.00

CALLS_PER_OPPORTUNITY_ACTOR = len(DEFAULT_PREFLIGHT_ARMS)
CALLS_PER_OPPORTUNITY_WITH_E = CALLS_PER_OPPORTUNITY_ACTOR + DELIBERATION_TURNS


class DeepSeekPilotError(DeepSeekPreflightError):
    """The DeepSeek Flash pilot cannot proceed safely.

    ``live_calls`` / ``completed_calls`` / ``attempted_calls`` record whether a
    live transport was selected and how far a failed run got, so a paid miss
    is not reported as ``live_calls: false``.
    """

    def __init__(
        self,
        message: str,
        *,
        live_calls: bool = False,
        allow_live: bool = False,
        completed_calls: int = 0,
        attempted_calls: int = 0,
    ) -> None:
        super().__init__(message)
        self.live_calls = live_calls
        self.allow_live = allow_live
        self.completed_calls = completed_calls
        self.attempted_calls = attempted_calls


def run_deepseek_flash_pilot(
    *,
    fixture_path: str | Path,
    pricing_path: str | Path,
    protocol_path: str | Path,
    identity_path: str | Path | None = None,
    amendment_path: str | Path | None = None,
    opportunity_count: int,
    call_ceiling: int,
    spend_ceiling_usd: float,
    api_key: str | None = None,
    transport=None,
    allow_live: bool = False,
    include_deliberation: bool = True,
) -> dict[str, Any]:
    """Run a bounded N-opportunity DeepSeek Flash pilot.

    Fixture-safe by default. Live transport requires ``allow_live=True`` plus a
    credential and still cannot authorize TRAINING or consume a holdout.
    """
    if opportunity_count < 1 or opportunity_count > PILOT_OPPORTUNITY_CEILING:
        raise DeepSeekPilotError(
            f"pilot opportunity count must be in 1..{PILOT_OPPORTUNITY_CEILING}"
        )
    if call_ceiling < 1 or call_ceiling > PILOT_CALL_CEILING:
        raise DeepSeekPilotError(
            f"pilot call ceiling must be in 1..{PILOT_CALL_CEILING}"
        )
    if (
        not isinstance(spend_ceiling_usd, (int, float))
        or not math.isfinite(spend_ceiling_usd)
        or spend_ceiling_usd < 0
        or spend_ceiling_usd > PILOT_SPEND_CEILING_USD
    ):
        raise DeepSeekPilotError(
            f"pilot spend ceiling must be a finite number in 0..{PILOT_SPEND_CEILING_USD}"
        )
    key = api_key if api_key is not None else api_key_from_env()
    _require_key(key)
    pricing = load_deepseek_pricing(pricing_path)
    protocol = load_registered_v2_protocol(protocol_path)
    identity_file = COMMITTED_IDENTITY_PATH if identity_path is None else identity_path
    try:
        identity = load_deepseek_flash_identity(identity_file, protocol_path=protocol_path)
    except IdentityError as exc:
        raise DeepSeekPilotError(str(exc)) from exc
    actor_id = identity_digest(identity)
    if include_deliberation:
        if amendment_path is None:
            raise DeepSeekPilotError(
                "E-arm pilot requires the non-authorizing compact-schema amendment"
            )
        try:
            load_e_arm_amendment(amendment_path, protocol_path=protocol_path)
        except DeliberationError as exc:
            raise DeepSeekPilotError(str(exc)) from exc
        if identity.get("deliberation_hash") is None:
            raise DeepSeekPilotError("DeepSeek identity is missing the compact E-arm axis")

    arms = _pilot_arm_sequence(include_deliberation=include_deliberation)
    planned_calls = opportunity_count * len(arms)
    if planned_calls > call_ceiling:
        raise DeepSeekPilotError("pilot arm sequence exceeds call ceiling")

    try:
        sender = _resolve_transport(transport=transport, allow_live=allow_live)
    except DeepSeekPreflightError as exc:
        raise DeepSeekPilotError(str(exc), allow_live=allow_live) from exc
    live_calls = sender is _live_transport
    envelope = _pilot_fixture_envelope(fixture_path)
    estimate = _build_pilot_requests(
        envelope,
        opportunity_count=opportunity_count,
        arms=arms,
        actor_identity=actor_id,
        prior_source="worst_case",
    )
    worst_cost = _preflight_worst_case_usd(estimate, pricing["peak"])
    if worst_cost > spend_ceiling_usd:
        raise DeepSeekPilotError(
            "worst-case pilot cost exceeds spend ceiling",
            allow_live=allow_live,
        )

    records: list[dict[str, Any]] = []
    total_input = total_output = 0
    attempted_calls = 0
    try:
        for index in range(opportunity_count):
            opportunity_id, packet, packet_hash = _opportunity_packet(
                envelope, opportunity_count=opportunity_count, index=index,
                actor_identity=actor_id,
            )
            prior_turns: list[dict[str, Any]] = []
            for item in arms:
                turn = item["turn"]
                priors = tuple(prior_turns) if item["arm"] == E_DELIBERATION else ()
                request = _arm_request(
                    packet=packet,
                    packet_hash=packet_hash,
                    arm=item["arm"],
                    turn=turn,
                    opportunity_id=opportunity_id,
                    opportunity_index=index,
                    prior_turns=priors,
                )
                attempted_calls += 1
                try:
                    response = sender(request["payload"], key)
                except DeepSeekPreflightError as exc:
                    raise DeepSeekPilotError(
                        str(exc),
                        live_calls=live_calls,
                        allow_live=allow_live,
                        completed_calls=len(records),
                        attempted_calls=attempted_calls,
                    ) from exc
                prompt_tokens, completion_tokens = _read_usage(response)
                total_input += prompt_tokens
                total_output += completion_tokens
                actual_cost = _cost_usd(total_input, total_output, pricing["peak"])
                decision, rejection = _read_decision(response, turn=turn)
                if actual_cost > spend_ceiling_usd and rejection is None:
                    rejection = "SPEND_CEILING_EXCEEDED"
                records.append({
                    "sequence": attempted_calls,
                    "arm": item["arm"],
                    "turn": turn,
                    "opportunity_id": opportunity_id,
                    "opportunity_index": index,
                    "request_hash": canonical_hash(request["payload"]),
                    "packet_hash": packet_hash,
                    "accepted": rejection is None,
                    "rejection_reason": rejection,
                    "decision": decision,
                    "raw_content_snippet": (
                        None if rejection is None
                        else raw_content_snippet(_assistant_content(response))
                    ),
                    "input_tokens": prompt_tokens,
                    "output_tokens": completion_tokens,
                    "cumulative_cost_usd": actual_cost,
                    "status": PILOT_STATUS,
                    "execution_authority": "ABSENT",
                    "actor_identity_hash": actor_id,
                    "prior_turn_count": len(priors),
                })
                if actual_cost > spend_ceiling_usd:
                    raise DeepSeekPilotError(
                        "reported usage exceeds spend ceiling",
                        live_calls=live_calls,
                        allow_live=allow_live,
                        completed_calls=len(records),
                        attempted_calls=attempted_calls,
                    )
                if item["arm"] == E_DELIBERATION and rejection is None and decision:
                    prior_turns.append(decision)
    except DeepSeekPilotError as exc:
        if attempted_calls and not exc.attempted_calls:
            exc.live_calls = live_calls
            exc.allow_live = allow_live
            exc.completed_calls = len(records)
            exc.attempted_calls = attempted_calls
        raise
    except DeepSeekPreflightError as exc:
        raise DeepSeekPilotError(
            str(exc),
            live_calls=live_calls,
            allow_live=allow_live,
            completed_calls=len(records),
            attempted_calls=attempted_calls,
        ) from exc

    result = {
        "schema_version": PILOT_SCHEMA,
        "status": PILOT_STATUS,
        "dry_run": not live_calls,
        "execution_authorized": False,
        "claim_authorized": False,
        "sealed_holdout_consumed": False,
        "execution_authority": "ABSENT",
        "registration_status": "REGISTERED_NOT_AUTHORIZED",
        "terra_protocol_not_reused": True,
        "pilot_is_not_training": True,
        "candidate_provider": identity["provider"],
        "candidate_model_id": identity["model_id"],
        "actor_identity_status": IDENTITY_STATUS,
        "actor_identity_hash": actor_id,
        "protocol_hash": protocol["protocol_hash"],
        "source_document": "docs/AAT_V2_MODEL_EXECUTION_OPTIONS.md",
        "opportunity_count": opportunity_count,
        "request_count": len(records),
        "accepted_count": sum(record["accepted"] for record in records),
        "rejected_count": sum(not record["accepted"] for record in records),
        "input_tokens": total_input,
        "output_tokens": total_output,
        "worst_case_cost_usd": worst_cost,
        "recorded_actual_cost_usd": records[-1]["cumulative_cost_usd"] if records else 0.0,
        "call_ceiling": call_ceiling,
        "spend_ceiling_usd": spend_ceiling_usd,
        "live_calls": live_calls,
        "actor_called": True,
        "allow_live": allow_live,
        "include_deliberation": include_deliberation,
        "recommended_live_opportunities": RECOMMENDED_LIVE_OPPORTUNITIES,
        "recommended_live_call_ceiling": RECOMMENDED_LIVE_CALL_CEILING,
        "recommended_live_spend_ceiling_usd": RECOMMENDED_LIVE_SPEND_CEILING_USD,
        "records": records,
    }
    result["result_hash"] = canonical_hash(
        {key: value for key, value in result.items() if key != "records"}
    )
    _assert_no_secret(result, key)
    return result


def _pilot_arm_sequence(*, include_deliberation: bool) -> tuple[dict[str, Any], ...]:
    items: list[dict[str, Any]] = [
        {"arm": arm, "turn": None} for arm in DEFAULT_PREFLIGHT_ARMS
    ]
    if include_deliberation:
        items.extend(
            {"arm": E_DELIBERATION, "turn": role} for role in DELIBERATION_TURN_ROLES
        )
    for item in items:
        if item["arm"] not in ACTOR_ARMS:
            raise DeepSeekPilotError(f"pilot cannot call arm {item['arm']}")
    return tuple(items)


def _pilot_fixture_envelope(path: str | Path) -> Mapping[str, Any]:
    payload = json_load_fixture(path)
    opportunity_id = payload.get("opportunity_id")
    if not isinstance(opportunity_id, str) or not opportunity_id.strip():
        raise DeepSeekPilotError("pilot fixture opportunity_id is unusable")
    if any(token in opportunity_id.lower() for token in ("holdout", "sealed")):
        raise DeepSeekPilotError("holdout paths are forbidden")
    return payload


def json_load_fixture(path: str | Path) -> dict[str, Any]:
    """Reuse the preflight fixture loader's holdout and schema guards."""
    try:
        return _load_preflight_fixture(path)
    except DeepSeekPreflightError as exc:
        raise DeepSeekPilotError(str(exc)) from exc


def _build_pilot_requests(
    fixture: Mapping[str, Any],
    *,
    opportunity_count: int,
    arms: tuple[dict[str, Any], ...],
    actor_identity: str,
    prior_source: str = "none",
) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    for index in range(opportunity_count):
        opportunity_id, packet, packet_hash = _opportunity_packet(
            fixture, opportunity_count=opportunity_count, index=index,
            actor_identity=actor_identity,
        )
        for item in arms:
            prior_turns: Sequence[Mapping[str, Any]] = ()
            if item["arm"] == E_DELIBERATION and prior_source == "worst_case":
                prior_turns = _worst_case_priors(item["turn"])
            requests.append(_arm_request(
                packet=packet,
                packet_hash=packet_hash,
                arm=item["arm"],
                turn=item["turn"],
                opportunity_id=opportunity_id,
                opportunity_index=index,
                prior_turns=prior_turns,
            ))
    return requests


def _opportunity_packet(
    fixture: Mapping[str, Any],
    *,
    opportunity_count: int,
    index: int,
    actor_identity: str,
) -> tuple[str, dict[str, Any], str]:
    exogenous = {key: 0 for key in feature_keys()}
    base_id = str(fixture["opportunity_id"])
    opportunity_id = base_id if opportunity_count == 1 else f"{base_id}-{index + 1}"
    packet = build_packet(
        arm=D_ATHENA,
        opportunity_id=opportunity_id,
        features=dict(fixture["features"]),
        actor_identity=actor_identity,
        exogenous_features=exogenous,
    )
    return opportunity_id, packet, canonical_hash(packet)


def _arm_request(
    *,
    packet: Mapping[str, Any],
    packet_hash: str,
    arm: str,
    turn: str | None,
    opportunity_id: str,
    opportunity_index: int,
    prior_turns: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    max_output_tokens = (
        DELIBERATION_OUTPUT_TOKENS if arm == E_DELIBERATION
        else SINGLE_CALL_OUTPUT_TOKENS
    )
    return {
        "arm": arm,
        "turn": turn,
        "opportunity_id": opportunity_id,
        "opportunity_index": opportunity_index,
        "max_output_tokens": max_output_tokens,
        "packet_hash": packet_hash,
        "payload": build_deepseek_payload(
            packet,
            max_output_tokens=max_output_tokens,
            arm=arm,
            turn=turn,
            system_prompt=PILOT_PROMPT,
            prior_turns=prior_turns,
        ),
    }


def _worst_case_priors(turn: str | None) -> tuple[dict[str, Any], ...]:
    if turn not in DELIBERATION_TURN_ROLES or turn == DELIBERATION_TURN_ROLES[0]:
        return ()
    worst = worst_case_compact_payloads()
    prior_roles = DELIBERATION_TURN_ROLES[:DELIBERATION_TURN_ROLES.index(turn)]
    return tuple(worst[role] for role in prior_roles)
