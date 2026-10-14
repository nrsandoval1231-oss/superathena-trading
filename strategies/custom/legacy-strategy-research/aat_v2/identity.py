"""Provider-scoped AAT-V2 Actor identities.

The registered V2 protocol is bound to OpenAI / ``gpt-5.6-terra``. Changing off
Terra is a new Actor, not a runtime substitution: Phase 2 made ``provider`` a
hashed axis so the same model string under a different vendor cannot inherit
Terra evidence.

DeepSeek Flash is declared here as a **candidate / pilot** identity. The
declaration does not rewrite the registered protocol, freeze a claim contract,
authorize TRAINING, or consume a holdout. V1 ``registered_providers()`` stays
``("openai",)``; DeepSeek is not inserted into that registry.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from ..paths import config_file
from typing import Any

from ..aat_v1.actor_canary import ACTION_SCHEMA
from ..aat_v1.providers import DEEPSEEK, OPENAI, provider_identity
from ..athena_adapter.contracts import canonical_hash
from .deliberation import deliberation_plan

IDENTITY_SCHEMA = "athena-aat-v2-deepseek-flash-actor-identity-v1"
PROTOCOL_SCHEMA = "athena-aat-v2-registered-protocol-v1"
IDENTITY_STATUS = "CANDIDATE_PILOT"

PROVIDER = DEEPSEEK.provider
MODEL_ID = "deepseek-flash"

#: Consulted, never rewritten. Must match ``configs/aat_v2_registered_protocol_v1.json``.
TERRA_PROTOCOL_HASH = "85d97d923f7b502dea20a936abe6334b57df64a677afdb6510376c5ea5b08027"
TERRA_PROVIDER = OPENAI.provider
TERRA_MODEL_ID = "gpt-5.6-terra"
TERRA_MODEL_HASH = "9c4aaaa136ed098624bee45f5f75d0654f4d56ea526fc4cc51a1f3f3bf1ae5db"
TERRA_PROMPT_HASH = "b7fa5ec9928d3ec22225bd757aa25b408ffdc9a5d3897bf8717a9d7d44bca88a"
TERRA_INFERENCE_HASH = "2c1cc91e081dd2f02283a520b0d01a226e9fc8320844e2126f95099de2b68633"

#: Actor-path (B/C/D) inference for the DeepSeek Flash *pilot*. Thinking off and
#: 512 output tokens are the hardened preflight rules. The registered TRAINING
#: protocol remains 256; this identity is not a TRAINING amendment.
PILOT_INFERENCE = {
    "endpoint": "chat.completions",
    "thinking": {"type": "disabled"},
    "response_format": {"type": "json_object"},
    "stream": False,
    "max_output_tokens": 512,
}

PILOT_PROMPT = (
    "You are a fail-closed AAT-V2 DeepSeek Flash Actor. Use only the supplied "
    "opaque features. Return exactly one JSON object and nothing else: no "
    "markdown, no code fences, no commentary, no extra keys. Required keys: "
    "action, confidence, horizon, invalidation, rationale. action must be one "
    "of PASS, ENTER_REDUCED, ENTER_STANDARD, ENTER_HIGH_CONVICTION. confidence "
    "must be a number in [0, 1]. horizon, invalidation, and rationale must be "
    "non-empty strings. Never claim execution_authority. This is "
    "PILOT_NOT_TRAINING, not TRAINING."
)

_FORBIDDEN_PATH_TOKENS = ("holdout", "sealed")

COMMITTED_IDENTITY_PATH = config_file("aat_v2_deepseek_flash_actor_identity_v1.json")


class IdentityError(ValueError):
    """A V2 Actor identity cannot be declared or loaded safely."""


def declared_deepseek_flash_identity() -> dict[str, Any]:
    """Hashed DeepSeek Flash candidate identity. Does not write the protocol."""
    axes = provider_identity(
        DEEPSEEK,
        model_id=MODEL_ID,
        prompt=PILOT_PROMPT,
        inference=PILOT_INFERENCE,
        action_schema=ACTION_SCHEMA,
    )
    _assert_not_terra(axes)
    deliberation = deliberation_plan()
    identity = {
        "schema_version": IDENTITY_SCHEMA,
        "identity_status": IDENTITY_STATUS,
        "bound_to_registered_protocol": False,
        "rewrites_registered_protocol": False,
        "execution_authorized": False,
        "claim_authorized": False,
        "execution_authority": "ABSENT",
        "sealed_holdout_consumed": False,
        "pilot_is_not_training": True,
        "terra_protocol_not_reused": True,
        "consulted_terra_protocol_hash": TERRA_PROTOCOL_HASH,
        "provider": axes["provider"],
        "model_id": axes["model_id"],
        "model_hash": axes["model_hash"],
        "prompt": PILOT_PROMPT,
        "prompt_hash": axes["prompt_hash"],
        "inference": dict(PILOT_INFERENCE),
        "inference_hash": axes["inference_hash"],
        "action_schema_hash": axes["action_schema_hash"],
        "deliberation_hash": deliberation["deliberation_hash"],
        "source_document": "docs/AAT_V2_MODEL_EXECUTION_OPTIONS.md",
    }
    identity["identity_hash"] = canonical_hash(identity)
    return identity


def load_deepseek_flash_identity(
    path: str | Path,
    *,
    protocol_path: str | Path,
) -> dict[str, Any]:
    """Load the committed candidate identity. Refuses a silent Terra swap."""
    payload = _load_json(path)
    protocol = _load_json(protocol_path)
    expected = declared_deepseek_flash_identity()
    body = dict(payload)
    claimed = body.pop("identity_hash", None)
    if payload.get("schema_version") != IDENTITY_SCHEMA:
        raise IdentityError("DeepSeek Flash identity schema is unusable")
    if not isinstance(claimed, str) or claimed != canonical_hash(body):
        raise IdentityError("DeepSeek Flash identity_hash does not match its contents")
    if payload.get("identity_hash") != expected["identity_hash"]:
        raise IdentityError("DeepSeek Flash identity drifted from the declared axes")
    if (
        payload.get("identity_status") != IDENTITY_STATUS
        or payload.get("bound_to_registered_protocol") is not False
        or payload.get("rewrites_registered_protocol") is not False
        or payload.get("execution_authorized") is not False
        or payload.get("claim_authorized") is not False
        or payload.get("execution_authority") != "ABSENT"
        or payload.get("sealed_holdout_consumed") is not False
        or payload.get("pilot_is_not_training") is not True
        or payload.get("terra_protocol_not_reused") is not True
    ):
        raise IdentityError("DeepSeek Flash identity must remain a non-authorizing candidate")
    _assert_not_terra(payload)
    actor = protocol.get("protocol", {}).get("actor_identity")
    if (
        protocol.get("schema_version") != PROTOCOL_SCHEMA
        or protocol.get("protocol_hash") != TERRA_PROTOCOL_HASH
        or not isinstance(actor, Mapping)
        or actor.get("provider") != TERRA_PROVIDER
        or actor.get("model_id") != TERRA_MODEL_ID
        or actor.get("model_hash") != TERRA_MODEL_HASH
    ):
        raise IdentityError(
            "registered Actor is not the Terra identity; refusing a silent swap"
        )
    if payload.get("consulted_terra_protocol_hash") != protocol.get("protocol_hash"):
        raise IdentityError("DeepSeek identity does not consult the registered Terra protocol")
    if payload.get("provider") == actor.get("provider") and payload.get("model_hash") == actor.get(
        "model_hash"
    ):
        raise IdentityError("DeepSeek must not reuse the Terra protocol identity")
    return payload


def identity_digest(identity: Mapping[str, Any]) -> str:
    """Stable digest stamped onto packets and receipts."""
    digest = identity.get("identity_hash")
    if not isinstance(digest, str) or not digest:
        raise IdentityError("Actor identity hash is missing")
    return digest


def _assert_not_terra(axes: Mapping[str, Any]) -> None:
    if axes.get("provider") == TERRA_PROVIDER or axes.get("model_id") == TERRA_MODEL_ID:
        raise IdentityError("DeepSeek identity cannot reuse the Terra provider or model id")
    if axes.get("model_hash") == TERRA_MODEL_HASH:
        raise IdentityError("DeepSeek model_hash collided with the Terra Actor")
    if axes.get("prompt_hash") == TERRA_PROMPT_HASH:
        raise IdentityError("DeepSeek prompt_hash collided with the Terra Actor")
    if axes.get("inference_hash") == TERRA_INFERENCE_HASH:
        raise IdentityError("DeepSeek inference_hash collided with the Terra Actor")
    if axes.get("provider") != PROVIDER or axes.get("model_id") != MODEL_ID:
        raise IdentityError("DeepSeek Flash identity is not provider-scoped to deepseek-flash")


def _load_json(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    text = str(target).lower()
    if any(token in text for token in _FORBIDDEN_PATH_TOKENS):
        raise IdentityError("holdout paths are forbidden")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IdentityError("Actor identity input is unreadable") from exc
    if not isinstance(value, dict):
        raise IdentityError("Actor identity input is not an object")
    return value
