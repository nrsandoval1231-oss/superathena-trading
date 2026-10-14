"""Provider-scoped Ollama / Qwen AAT-V2 Actor identities.

The registered V2 protocol stays bound to OpenAI / ``gpt-5.6-terra``. Ollama
Qwen is a **separate Actor family**, hashed on the ``ollama`` provider axis
so it cannot inherit Terra or DeepSeek Flash evidence.

Three committed TRAINING candidates exist:

* Desktop loopback ``qwen3.5:9b`` (``LOCAL_TRAINING_CANDIDATE``). Full
  in-sample TRAINING requires Nick's local authorization artifact **and**
  ``--authorize-local-training``.
* RunPod / remote gold ``qwen2.5:14b`` (``RUNPOD_TRAINING_CANDIDATE``). The
  recommended gold slice is 100 opportunities overlapping the 7b volume
  sample, full arms including E. That path still uses
  ``--authorize-runpod-training``. The flag does not authorize Terra, the
  desktop 9b Actor, or the 7b volume Actor. The frozen 16,705-opportunity
  plan remains plumbing, not the recommended next step.
* RunPod / remote volume ``qwen2.5:7b`` (``VOLUME_TRAINING_CANDIDATE``). The
  documented volume plan is a stratified 1,000-opportunity TRAINING
  subsample, native ``/api/chat``. Full volume-subsample runs require the
  volume authorization artifact **and** ``--authorize-volume-training``.
  That flag does not authorize Terra, desktop 9b, or gold 14b.

None of these identities rewrite the registered protocol, freeze a claim
contract, grant ``execution_authority``, or consume a holdout. Smoke / dry
defaults never flip those bits.

A different Ollama tag is a different Actor: pass a separately hashed
identity file rather than swapping the string at runtime.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from ..paths import config_file
from typing import Any

from ..aat_v1.actor_canary import ACTION_SCHEMA
from ..aat_v1.providers import DEEPSEEK, OLLAMA, provider_identity
from ..athena_adapter.contracts import canonical_hash
from .deliberation import deliberation_plan
from .identity import (
    TERRA_INFERENCE_HASH,
    TERRA_MODEL_HASH,
    TERRA_MODEL_ID,
    TERRA_PROMPT_HASH,
    TERRA_PROTOCOL_HASH,
    TERRA_PROVIDER,
    IdentityError,
    identity_digest,
)

IDENTITY_SCHEMA = "athena-aat-v2-ollama-qwen-actor-identity-v1"
AUTHORIZATION_SCHEMA = "athena-aat-v2-ollama-local-training-authorization-v1"
RUNPOD_IDENTITY_SCHEMA = "athena-aat-v2-ollama-qwen-14b-runpod-actor-identity-v1"
RUNPOD_AUTHORIZATION_SCHEMA = "athena-aat-v2-ollama-runpod-training-authorization-v1"
VOLUME_IDENTITY_SCHEMA = "athena-aat-v2-ollama-qwen-7b-volume-actor-identity-v1"
VOLUME_AUTHORIZATION_SCHEMA = "athena-aat-v2-ollama-volume-training-authorization-v1"
PROTOCOL_SCHEMA = "athena-aat-v2-registered-protocol-v1"
IDENTITY_STATUS = "LOCAL_TRAINING_CANDIDATE"
RUNPOD_IDENTITY_STATUS = "RUNPOD_TRAINING_CANDIDATE"
VOLUME_IDENTITY_STATUS = "VOLUME_TRAINING_CANDIDATE"
AUTHORIZATION_STATUS = "AUTHORIZATION_REQUIRED_FOR_FULL_RUN"

PROVIDER = OLLAMA.provider
DEFAULT_MODEL_ID = "qwen3.5:9b"
MODEL_ID = DEFAULT_MODEL_ID
RUNPOD_MODEL_ID = "qwen2.5:14b"
VOLUME_MODEL_ID = "qwen2.5:7b"
DEFAULT_BASE_URL = "http://127.0.0.1:11434"
CHAT_PATH = "/api/chat"
RUNTIME_BASE_URL = "runtime"
RUNPOD_BASE_URL_POLICY = "explicit_cli"
RUNPOD_HOST_SCOPE = "runpod_or_tunnel"
VOLUME_SUBSAMPLE_OPPORTUNITIES = 1000
GOLD_SUBSAMPLE_OPPORTUNITIES = 100

#: Registered TRAINING single-call budget (not the DeepSeek 512-token pilot).
TRAINING_INFERENCE = {
    "endpoint": "ollama.chat",
    "base_url": DEFAULT_BASE_URL,
    "path": CHAT_PATH,
    "think": False,
    "format": "json",
    "stream": False,
    "max_output_tokens": 256,
}

#: Host is a runtime transport parameter (pod IP or SSH tunnel), not an Actor axis.
RUNPOD_TRAINING_INFERENCE = {
    "endpoint": "ollama.chat",
    "base_url": RUNTIME_BASE_URL,
    "base_url_policy": RUNPOD_BASE_URL_POLICY,
    "path": CHAT_PATH,
    "think": False,
    "format": "json",
    "stream": False,
    "max_output_tokens": 256,
    "host_scope": RUNPOD_HOST_SCOPE,
}

TRAINING_PROMPT = (
    "You are a fail-closed AAT-V2 local Ollama Qwen Actor. Use only the supplied "
    "opaque features. Return exactly one JSON object and nothing else: no "
    "markdown, no code fences, no commentary, no extra keys. Required keys: "
    "action, confidence, horizon, invalidation, rationale. action must be one "
    "of PASS, ENTER_REDUCED, ENTER_STANDARD, ENTER_HIGH_CONVICTION. confidence "
    "must be a number in [0, 1]. horizon, invalidation, and rationale must be "
    "non-empty strings. Never claim execution_authority. This is "
    "LOCAL_TRAINING_IN_SAMPLE, not a claim, not a holdout, and not broker "
    "execution."
)

RUNPOD_TRAINING_PROMPT = (
    "You are a fail-closed AAT-V2 RunPod Ollama Qwen 14b Actor. Use only the "
    "supplied opaque features. Return exactly one JSON object and nothing else: "
    "no markdown, no code fences, no commentary, no extra keys. Required keys: "
    "action, confidence, horizon, invalidation, rationale. action must be one "
    "of PASS, ENTER_REDUCED, ENTER_STANDARD, ENTER_HIGH_CONVICTION. confidence "
    "must be a number in [0, 1]. horizon, invalidation, and rationale must be "
    "non-empty strings. Never claim execution_authority. This is "
    "RUNPOD_TRAINING_IN_SAMPLE, not a claim, not a holdout, and not broker "
    "execution."
)

VOLUME_TRAINING_PROMPT = (
    "You are a fail-closed AAT-V2 volume Ollama Qwen 7b Actor. Use only the "
    "supplied opaque features. Return exactly one JSON object and nothing else: "
    "no markdown, no code fences, no commentary, no extra keys. Required keys: "
    "action, confidence, horizon, invalidation, rationale. action must be one "
    "of PASS, ENTER_REDUCED, ENTER_STANDARD, ENTER_HIGH_CONVICTION. confidence "
    "must be a number in [0, 1]. horizon, invalidation, and rationale must be "
    "non-empty strings. Never claim execution_authority. This is "
    "VOLUME_TRAINING_IN_SAMPLE, not a claim, not a holdout, and not broker "
    "execution."
)

_FORBIDDEN_PATH_TOKENS = ("holdout", "sealed")

COMMITTED_IDENTITY_PATH = config_file("aat_v2_ollama_qwen_actor_identity_v1.json")
COMMITTED_AUTHORIZATION_PATH = config_file("aat_v2_ollama_local_training_authorization_v1.json")
COMMITTED_RUNPOD_IDENTITY_PATH = config_file(
    "aat_v2_ollama_qwen_14b_runpod_actor_identity_v1.json"
)
COMMITTED_RUNPOD_AUTHORIZATION_PATH = config_file(
    "aat_v2_ollama_runpod_training_authorization_v1.json"
)
COMMITTED_VOLUME_IDENTITY_PATH = config_file("aat_v2_ollama_qwen_7b_volume_actor_identity_v1.json")
COMMITTED_VOLUME_AUTHORIZATION_PATH = config_file(
    "aat_v2_ollama_volume_training_authorization_v1.json"
)

CLI_AUTHORIZATION_FLAG = "--authorize-local-training"
RUNPOD_CLI_AUTHORIZATION_FLAG = "--authorize-runpod-training"
VOLUME_CLI_AUTHORIZATION_FLAG = "--authorize-volume-training"


class AuthorizationError(IdentityError):
    """Local TRAINING authorization is missing, drifted, or silently overreaching."""


def declared_ollama_qwen_identity(*, model_id: str = DEFAULT_MODEL_ID) -> dict[str, Any]:
    """Hashed Ollama Qwen candidate identity. Does not write the protocol."""
    if not isinstance(model_id, str) or not model_id.strip():
        raise IdentityError("Ollama model id is unusable")
    axes = provider_identity(
        OLLAMA,
        model_id=model_id,
        prompt=TRAINING_PROMPT,
        inference=TRAINING_INFERENCE,
        action_schema=ACTION_SCHEMA,
    )
    _assert_not_terra_or_deepseek(axes)
    if axes.get("provider") != PROVIDER:
        raise IdentityError("Ollama identity is not provider-scoped to ollama")
    if axes.get("model_id") != model_id:
        raise IdentityError("Ollama identity model id drifted")
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
        "local_training_candidate": True,
        "local_training_requires_explicit_authorization": True,
        "authorization_cli_flag": CLI_AUTHORIZATION_FLAG,
        "terra_protocol_not_reused": True,
        "deepseek_identity_not_reused": True,
        "consulted_terra_protocol_hash": TERRA_PROTOCOL_HASH,
        "default_model_id": DEFAULT_MODEL_ID,
        "model_id_configurable": True,
        "runtime_model_swap_forbidden": True,
        "provider": axes["provider"],
        "model_id": axes["model_id"],
        "model_hash": axes["model_hash"],
        "prompt": TRAINING_PROMPT,
        "prompt_hash": axes["prompt_hash"],
        "inference": dict(TRAINING_INFERENCE),
        "inference_hash": axes["inference_hash"],
        "action_schema_hash": axes["action_schema_hash"],
        "deliberation_hash": deliberation["deliberation_hash"],
        "source_document": "docs/AAT_V2_MODEL_EXECUTION_OPTIONS.md",
    }
    identity["identity_hash"] = canonical_hash(identity)
    return identity


def load_ollama_qwen_identity(
    path: str | Path,
    *,
    protocol_path: str | Path,
    expected_model_id: str | None = None,
) -> dict[str, Any]:
    """Load the committed candidate identity. Refuses a silent Terra/DeepSeek swap."""
    payload = _load_json(path)
    protocol = _load_json(protocol_path)
    model_id = payload.get("model_id")
    if not isinstance(model_id, str):
        raise IdentityError("Ollama identity model id is unusable")
    expected = declared_ollama_qwen_identity(model_id=model_id)
    body = dict(payload)
    claimed = body.pop("identity_hash", None)
    if payload.get("schema_version") != IDENTITY_SCHEMA:
        raise IdentityError("Ollama Qwen identity schema is unusable")
    if not isinstance(claimed, str) or claimed != canonical_hash(body):
        raise IdentityError("Ollama Qwen identity_hash does not match its contents")
    if payload.get("identity_hash") != expected["identity_hash"]:
        raise IdentityError("Ollama Qwen identity drifted from the declared axes")
    if expected_model_id is not None and payload.get("model_id") != expected_model_id:
        raise IdentityError("Ollama model id does not match the requested identity")
    if (
        payload.get("identity_status") != IDENTITY_STATUS
        or payload.get("bound_to_registered_protocol") is not False
        or payload.get("rewrites_registered_protocol") is not False
        or payload.get("execution_authorized") is not False
        or payload.get("claim_authorized") is not False
        or payload.get("execution_authority") != "ABSENT"
        or payload.get("sealed_holdout_consumed") is not False
        or payload.get("local_training_candidate") is not True
        or payload.get("local_training_requires_explicit_authorization") is not True
        or payload.get("terra_protocol_not_reused") is not True
        or payload.get("runtime_model_swap_forbidden") is not True
    ):
        raise IdentityError("Ollama identity must remain a non-authorizing TRAINING candidate")
    _assert_not_terra_or_deepseek(payload)
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
    if protocol.get("protocol", {}).get("registration_status") != "REGISTERED_NOT_AUTHORIZED":
        raise IdentityError("refusing to treat a non-Terra-registered protocol as authorized")
    if payload.get("consulted_terra_protocol_hash") != protocol.get("protocol_hash"):
        raise IdentityError("Ollama identity does not consult the registered Terra protocol")
    if payload.get("provider") == actor.get("provider") and payload.get("model_hash") == actor.get(
        "model_hash"
    ):
        raise IdentityError("Ollama must not reuse the Terra protocol identity")
    return payload


def declared_ollama_runpod_identity(*, model_id: str = RUNPOD_MODEL_ID) -> dict[str, Any]:
    """Hashed RunPod / remote Ollama 14b candidate. Does not write the protocol."""
    if not isinstance(model_id, str) or not model_id.strip():
        raise IdentityError("Ollama model id is unusable")
    axes = provider_identity(
        OLLAMA,
        model_id=model_id,
        prompt=RUNPOD_TRAINING_PROMPT,
        inference=RUNPOD_TRAINING_INFERENCE,
        action_schema=ACTION_SCHEMA,
    )
    _assert_not_terra_or_deepseek(axes)
    if axes.get("provider") != PROVIDER:
        raise IdentityError("Ollama identity is not provider-scoped to ollama")
    if axes.get("model_id") != model_id:
        raise IdentityError("Ollama identity model id drifted")
    local = declared_ollama_qwen_identity()
    if axes["model_hash"] == local["model_hash"] and model_id == DEFAULT_MODEL_ID:
        raise IdentityError("RunPod identity cannot reuse the local qwen3.5:9b model hash")
    deliberation = deliberation_plan()
    identity = {
        "schema_version": RUNPOD_IDENTITY_SCHEMA,
        "identity_status": RUNPOD_IDENTITY_STATUS,
        "bound_to_registered_protocol": False,
        "rewrites_registered_protocol": False,
        "execution_authorized": False,
        "claim_authorized": False,
        "execution_authority": "ABSENT",
        "sealed_holdout_consumed": False,
        "local_training_candidate": False,
        "runpod_training_candidate": True,
        "local_9b_identity_not_reused": True,
        "local_training_requires_explicit_authorization": True,
        "authorization_cli_flag": RUNPOD_CLI_AUTHORIZATION_FLAG,
        "terra_protocol_not_reused": True,
        "deepseek_identity_not_reused": True,
        "consulted_terra_protocol_hash": TERRA_PROTOCOL_HASH,
        "default_model_id": RUNPOD_MODEL_ID,
        "model_id_configurable": True,
        "runtime_model_swap_forbidden": True,
        "runtime_base_url_not_identity": True,
        "provider": axes["provider"],
        "model_id": axes["model_id"],
        "model_hash": axes["model_hash"],
        "prompt": RUNPOD_TRAINING_PROMPT,
        "prompt_hash": axes["prompt_hash"],
        "inference": dict(RUNPOD_TRAINING_INFERENCE),
        "inference_hash": axes["inference_hash"],
        "action_schema_hash": axes["action_schema_hash"],
        "deliberation_hash": deliberation["deliberation_hash"],
        "source_document": "docs/AAT_V2_MODEL_EXECUTION_OPTIONS.md",
        "model_tag_choice": (
            "qwen2.5:14b is the committed RunPod tag because it is the widely "
            "available 14b-class Ollama model that fits a Community RTX 4090 "
            "and cannot be confused with desktop qwen3.5:9b. qwen3:14b would "
            "look like a typo next to the desktop 9b tag and is a different "
            "generation from Qwen 3.5 anyway."
        ),
    }
    identity["identity_hash"] = canonical_hash(identity)
    if identity["identity_hash"] == local["identity_hash"]:
        raise IdentityError("RunPod identity collided with the local qwen3.5:9b Actor")
    return identity


def load_ollama_runpod_identity(
    path: str | Path,
    *,
    protocol_path: str | Path,
    expected_model_id: str | None = None,
) -> dict[str, Any]:
    """Load the committed RunPod 14b identity. Refuses a silent 9b/Terra/DeepSeek swap."""
    payload = _load_json(path)
    protocol = _load_json(protocol_path)
    model_id = payload.get("model_id")
    if not isinstance(model_id, str):
        raise IdentityError("Ollama identity model id is unusable")
    expected = declared_ollama_runpod_identity(model_id=model_id)
    body = dict(payload)
    claimed = body.pop("identity_hash", None)
    if payload.get("schema_version") != RUNPOD_IDENTITY_SCHEMA:
        raise IdentityError("RunPod Ollama identity schema is unusable")
    if not isinstance(claimed, str) or claimed != canonical_hash(body):
        raise IdentityError("RunPod Ollama identity_hash does not match its contents")
    if payload.get("identity_hash") != expected["identity_hash"]:
        raise IdentityError("RunPod Ollama identity drifted from the declared axes")
    if expected_model_id is not None and payload.get("model_id") != expected_model_id:
        raise IdentityError("Ollama model id does not match the requested identity")
    if (
        payload.get("identity_status") != RUNPOD_IDENTITY_STATUS
        or payload.get("bound_to_registered_protocol") is not False
        or payload.get("rewrites_registered_protocol") is not False
        or payload.get("execution_authorized") is not False
        or payload.get("claim_authorized") is not False
        or payload.get("execution_authority") != "ABSENT"
        or payload.get("sealed_holdout_consumed") is not False
        or payload.get("runpod_training_candidate") is not True
        or payload.get("local_training_candidate") is not False
        or payload.get("local_9b_identity_not_reused") is not True
        or payload.get("local_training_requires_explicit_authorization") is not True
        or payload.get("terra_protocol_not_reused") is not True
        or payload.get("runtime_model_swap_forbidden") is not True
        or payload.get("runtime_base_url_not_identity") is not True
        or payload.get("authorization_cli_flag") != RUNPOD_CLI_AUTHORIZATION_FLAG
    ):
        raise IdentityError("RunPod identity must remain a non-authorizing TRAINING candidate")
    _assert_not_terra_or_deepseek(payload)
    local = declared_ollama_qwen_identity()
    if payload.get("identity_hash") == local["identity_hash"]:
        raise IdentityError("RunPod identity cannot reuse the local qwen3.5:9b Actor")
    if payload.get("model_id") == DEFAULT_MODEL_ID:
        raise IdentityError("RunPod committed identity cannot silently reuse qwen3.5:9b")
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
    if protocol.get("protocol", {}).get("registration_status") != "REGISTERED_NOT_AUTHORIZED":
        raise IdentityError("refusing to treat a non-Terra-registered protocol as authorized")
    if payload.get("consulted_terra_protocol_hash") != protocol.get("protocol_hash"):
        raise IdentityError("Ollama identity does not consult the registered Terra protocol")
    if payload.get("provider") == actor.get("provider") and payload.get("model_hash") == actor.get(
        "model_hash"
    ):
        raise IdentityError("Ollama must not reuse the Terra protocol identity")
    return payload


def declared_ollama_volume_identity(*, model_id: str = VOLUME_MODEL_ID) -> dict[str, Any]:
    """Hashed volume / remote Ollama 7b candidate. Does not write the protocol."""
    if not isinstance(model_id, str) or not model_id.strip():
        raise IdentityError("Ollama model id is unusable")
    axes = provider_identity(
        OLLAMA,
        model_id=model_id,
        prompt=VOLUME_TRAINING_PROMPT,
        inference=RUNPOD_TRAINING_INFERENCE,
        action_schema=ACTION_SCHEMA,
    )
    _assert_not_terra_or_deepseek(axes)
    if axes.get("provider") != PROVIDER:
        raise IdentityError("Ollama identity is not provider-scoped to ollama")
    if axes.get("model_id") != model_id:
        raise IdentityError("Ollama identity model id drifted")
    local = declared_ollama_qwen_identity()
    gold = declared_ollama_runpod_identity()
    if axes["model_hash"] == local["model_hash"] and model_id == DEFAULT_MODEL_ID:
        raise IdentityError("volume identity cannot reuse the local qwen3.5:9b model hash")
    if axes["model_hash"] == gold["model_hash"] and model_id == RUNPOD_MODEL_ID:
        raise IdentityError("volume identity cannot reuse the RunPod qwen2.5:14b model hash")
    deliberation = deliberation_plan()
    identity = {
        "schema_version": VOLUME_IDENTITY_SCHEMA,
        "identity_status": VOLUME_IDENTITY_STATUS,
        "bound_to_registered_protocol": False,
        "rewrites_registered_protocol": False,
        "execution_authorized": False,
        "claim_authorized": False,
        "execution_authority": "ABSENT",
        "sealed_holdout_consumed": False,
        "local_training_candidate": False,
        "runpod_training_candidate": False,
        "volume_training_candidate": True,
        "local_9b_identity_not_reused": True,
        "runpod_14b_identity_not_reused": True,
        "local_training_requires_explicit_authorization": True,
        "authorization_cli_flag": VOLUME_CLI_AUTHORIZATION_FLAG,
        "terra_protocol_not_reused": True,
        "deepseek_identity_not_reused": True,
        "consulted_terra_protocol_hash": TERRA_PROTOCOL_HASH,
        "default_model_id": VOLUME_MODEL_ID,
        "model_id_configurable": True,
        "runtime_model_swap_forbidden": True,
        "runtime_base_url_not_identity": True,
        "volume_subsample_opportunities": VOLUME_SUBSAMPLE_OPPORTUNITIES,
        "gold_subsample_opportunities": GOLD_SUBSAMPLE_OPPORTUNITIES,
        "authorizes_full_16705_plan": False,
        "provider": axes["provider"],
        "model_id": axes["model_id"],
        "model_hash": axes["model_hash"],
        "prompt": VOLUME_TRAINING_PROMPT,
        "prompt_hash": axes["prompt_hash"],
        "inference": dict(RUNPOD_TRAINING_INFERENCE),
        "inference_hash": axes["inference_hash"],
        "action_schema_hash": axes["action_schema_hash"],
        "deliberation_hash": deliberation["deliberation_hash"],
        "source_document": "docs/AAT_V2_MODEL_EXECUTION_OPTIONS.md",
        "model_tag_choice": (
            "qwen2.5:7b is the committed volume tag because it is the widely "
            "available 7b-class Ollama model that fits a Community RTX 4090 "
            "and cannot be confused with desktop qwen3.5:9b or gold "
            "qwen2.5:14b. A different tag is a different hashed Actor."
        ),
    }
    identity["identity_hash"] = canonical_hash(identity)
    if identity["identity_hash"] == local["identity_hash"]:
        raise IdentityError("volume identity collided with the local qwen3.5:9b Actor")
    if identity["identity_hash"] == gold["identity_hash"]:
        raise IdentityError("volume identity collided with the RunPod qwen2.5:14b Actor")
    return identity


def load_ollama_volume_identity(
    path: str | Path,
    *,
    protocol_path: str | Path,
    expected_model_id: str | None = None,
) -> dict[str, Any]:
    """Load the committed volume 7b identity. Refuses a silent 9b/14b/Terra swap."""
    payload = _load_json(path)
    protocol = _load_json(protocol_path)
    model_id = payload.get("model_id")
    if not isinstance(model_id, str):
        raise IdentityError("Ollama identity model id is unusable")
    expected = declared_ollama_volume_identity(model_id=model_id)
    body = dict(payload)
    claimed = body.pop("identity_hash", None)
    if payload.get("schema_version") != VOLUME_IDENTITY_SCHEMA:
        raise IdentityError("volume Ollama identity schema is unusable")
    if not isinstance(claimed, str) or claimed != canonical_hash(body):
        raise IdentityError("volume Ollama identity_hash does not match its contents")
    if payload.get("identity_hash") != expected["identity_hash"]:
        raise IdentityError("volume Ollama identity drifted from the declared axes")
    if expected_model_id is not None and payload.get("model_id") != expected_model_id:
        raise IdentityError("Ollama model id does not match the requested identity")
    if (
        payload.get("identity_status") != VOLUME_IDENTITY_STATUS
        or payload.get("bound_to_registered_protocol") is not False
        or payload.get("rewrites_registered_protocol") is not False
        or payload.get("execution_authorized") is not False
        or payload.get("claim_authorized") is not False
        or payload.get("execution_authority") != "ABSENT"
        or payload.get("sealed_holdout_consumed") is not False
        or payload.get("volume_training_candidate") is not True
        or payload.get("runpod_training_candidate") is not False
        or payload.get("local_training_candidate") is not False
        or payload.get("local_9b_identity_not_reused") is not True
        or payload.get("runpod_14b_identity_not_reused") is not True
        or payload.get("local_training_requires_explicit_authorization") is not True
        or payload.get("terra_protocol_not_reused") is not True
        or payload.get("runtime_model_swap_forbidden") is not True
        or payload.get("runtime_base_url_not_identity") is not True
        or payload.get("authorizes_full_16705_plan") is not False
        or payload.get("volume_subsample_opportunities") != VOLUME_SUBSAMPLE_OPPORTUNITIES
        or payload.get("gold_subsample_opportunities") != GOLD_SUBSAMPLE_OPPORTUNITIES
        or payload.get("authorization_cli_flag") != VOLUME_CLI_AUTHORIZATION_FLAG
    ):
        raise IdentityError("volume identity must remain a non-authorizing TRAINING candidate")
    _assert_not_terra_or_deepseek(payload)
    local = declared_ollama_qwen_identity()
    gold = declared_ollama_runpod_identity()
    if payload.get("identity_hash") == local["identity_hash"]:
        raise IdentityError("volume identity cannot reuse the local qwen3.5:9b Actor")
    if payload.get("identity_hash") == gold["identity_hash"]:
        raise IdentityError("volume identity cannot reuse the RunPod qwen2.5:14b Actor")
    if payload.get("model_id") in {DEFAULT_MODEL_ID, RUNPOD_MODEL_ID}:
        raise IdentityError("volume committed identity cannot silently reuse 9b or 14b")
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
    if protocol.get("protocol", {}).get("registration_status") != "REGISTERED_NOT_AUTHORIZED":
        raise IdentityError("refusing to treat a non-Terra-registered protocol as authorized")
    if payload.get("consulted_terra_protocol_hash") != protocol.get("protocol_hash"):
        raise IdentityError("Ollama identity does not consult the registered Terra protocol")
    if payload.get("provider") == actor.get("provider") and payload.get("model_hash") == actor.get(
        "model_hash"
    ):
        raise IdentityError("Ollama must not reuse the Terra protocol identity")
    return payload


def load_committed_ollama_training_identity(
    path: str | Path,
    *,
    protocol_path: str | Path,
    expected_model_id: str | None = None,
) -> dict[str, Any]:
    """Load the desktop 9b, RunPod 14b, or volume 7b identity. Fail closed otherwise."""
    payload = _load_json(path)
    schema = payload.get("schema_version")
    if schema == IDENTITY_SCHEMA:
        return load_ollama_qwen_identity(
            path, protocol_path=protocol_path, expected_model_id=expected_model_id,
        )
    if schema == RUNPOD_IDENTITY_SCHEMA:
        return load_ollama_runpod_identity(
            path, protocol_path=protocol_path, expected_model_id=expected_model_id,
        )
    if schema == VOLUME_IDENTITY_SCHEMA:
        return load_ollama_volume_identity(
            path, protocol_path=protocol_path, expected_model_id=expected_model_id,
        )
    raise IdentityError("unrecognized Ollama TRAINING identity schema")


def is_runpod_identity(identity: Mapping[str, Any]) -> bool:
    return identity.get("schema_version") == RUNPOD_IDENTITY_SCHEMA


def is_volume_identity(identity: Mapping[str, Any]) -> bool:
    return identity.get("schema_version") == VOLUME_IDENTITY_SCHEMA


def allows_remote_ollama(identity: Mapping[str, Any]) -> bool:
    """RunPod gold 14b and volume 7b may use a pod IP, HTTPS proxy, or tunnel."""
    return is_runpod_identity(identity) or is_volume_identity(identity)


def declared_local_training_authorization(identity: Mapping[str, Any]) -> dict[str, Any]:
    """Nick-authorized local Ollama TRAINING plumbing. Not a Terra protocol flip."""
    digest = identity_digest(identity)
    authorization = {
        "schema_version": AUTHORIZATION_SCHEMA,
        "authorization_status": AUTHORIZATION_STATUS,
        "authorization_kind": "NICK_EXPLICIT_LOCAL_OLLAMA_TRAINING",
        "nick_authorized_plumbing": True,
        "nick_authorized_local_training_execution": True,
        "execution_requires_cli_flag": True,
        "authorization_cli_flag": CLI_AUTHORIZATION_FLAG,
        "execution_authorized": False,
        "claim_authorized": False,
        "execution_authority": "ABSENT",
        "sealed_holdout_consumed": False,
        "holdout_untouched": True,
        "rewrites_registered_protocol": False,
        "authorizes_terra_protocol": False,
        "bound_to_registered_protocol": False,
        "scope": "LOCAL_IN_SAMPLE_TRAINING_ONLY",
        "provider": PROVIDER,
        "model_id": identity.get("model_id"),
        "actor_identity_hash": digest,
        "consulted_terra_protocol_hash": TERRA_PROTOCOL_HASH,
        "source_document": "docs/AAT_V2_MODEL_EXECUTION_OPTIONS.md",
        "notes": (
            "Authorizes local Ollama TRAINING execution plumbing under Nick's "
            "direction. Full 16,705-opportunity runs still require the CLI "
            "flag. The registered Terra protocol stays REGISTERED_NOT_AUTHORIZED. "
            "Broker execution_authority stays ABSENT. V1/V2 holdout stays unused."
        ),
    }
    authorization["authorization_hash"] = canonical_hash(authorization)
    return authorization


def load_local_training_authorization(
    path: str | Path,
    *,
    identity: Mapping[str, Any],
    protocol_path: str | Path,
) -> dict[str, Any]:
    """Load Nick's local-TRAINING authorization. Does not flip Terra to authorized."""
    payload = _load_json(path)
    protocol = _load_json(protocol_path)
    expected = declared_local_training_authorization(identity)
    body = dict(payload)
    claimed = body.pop("authorization_hash", None)
    if payload.get("schema_version") != AUTHORIZATION_SCHEMA:
        raise AuthorizationError("local TRAINING authorization schema is unusable")
    if not isinstance(claimed, str) or claimed != canonical_hash(body):
        raise AuthorizationError("local TRAINING authorization_hash does not match its contents")
    if payload.get("authorization_hash") != expected["authorization_hash"]:
        raise AuthorizationError("local TRAINING authorization drifted from the declared artifact")
    if (
        payload.get("authorization_status") != AUTHORIZATION_STATUS
        or payload.get("nick_authorized_plumbing") is not True
        or payload.get("nick_authorized_local_training_execution") is not True
        or payload.get("execution_requires_cli_flag") is not True
        or payload.get("execution_authorized") is not False
        or payload.get("claim_authorized") is not False
        or payload.get("execution_authority") != "ABSENT"
        or payload.get("sealed_holdout_consumed") is not False
        or payload.get("holdout_untouched") is not True
        or payload.get("rewrites_registered_protocol") is not False
        or payload.get("authorizes_terra_protocol") is not False
        or payload.get("actor_identity_hash") != identity_digest(identity)
        or payload.get("consulted_terra_protocol_hash") != TERRA_PROTOCOL_HASH
    ):
        raise AuthorizationError("local TRAINING authorization must stay fail-closed")
    if protocol.get("protocol_hash") != TERRA_PROTOCOL_HASH:
        raise AuthorizationError("authorization does not consult the registered Terra protocol")
    if protocol.get("protocol", {}).get("registration_status") != "REGISTERED_NOT_AUTHORIZED":
        raise AuthorizationError("refusing to silently authorize the Terra protocol")
    return payload


def declared_runpod_training_authorization(identity: Mapping[str, Any]) -> dict[str, Any]:
    """Nick-authorized RunPod Ollama TRAINING plumbing. Not a Terra or 9b flip."""
    if not is_runpod_identity(identity):
        raise AuthorizationError("RunPod authorization requires the RunPod 14b identity")
    digest = identity_digest(identity)
    authorization = {
        "schema_version": RUNPOD_AUTHORIZATION_SCHEMA,
        "authorization_status": AUTHORIZATION_STATUS,
        "authorization_kind": "NICK_EXPLICIT_RUNPOD_OLLAMA_TRAINING",
        "nick_authorized_plumbing": True,
        "nick_authorized_runpod_training_execution": True,
        "nick_authorized_local_training_execution": False,
        "execution_requires_cli_flag": True,
        "authorization_cli_flag": RUNPOD_CLI_AUTHORIZATION_FLAG,
        "execution_authorized": False,
        "claim_authorized": False,
        "execution_authority": "ABSENT",
        "sealed_holdout_consumed": False,
        "holdout_untouched": True,
        "rewrites_registered_protocol": False,
        "authorizes_terra_protocol": False,
        "authorizes_local_9b_identity": False,
        "bound_to_registered_protocol": False,
        "scope": "RUNPOD_IN_SAMPLE_TRAINING_ONLY",
        "provider": PROVIDER,
        "model_id": identity.get("model_id"),
        "actor_identity_hash": digest,
        "consulted_terra_protocol_hash": TERRA_PROTOCOL_HASH,
        "source_document": "docs/AAT_V2_MODEL_EXECUTION_OPTIONS.md",
        "notes": (
            "Authorizes RunPod / remote Ollama TRAINING execution plumbing under "
            "Nick's direction. Full 16,705-opportunity runs still require "
            f"{RUNPOD_CLI_AUTHORIZATION_FLAG}. That flag does not authorize the "
            "desktop qwen3.5:9b Actor or the Terra protocol. Broker "
            "execution_authority stays ABSENT. V1/V2 holdout stays unused."
        ),
    }
    authorization["authorization_hash"] = canonical_hash(authorization)
    return authorization


def load_runpod_training_authorization(
    path: str | Path,
    *,
    identity: Mapping[str, Any],
    protocol_path: str | Path,
) -> dict[str, Any]:
    """Load Nick's RunPod-TRAINING authorization. Does not flip Terra or local 9b."""
    payload = _load_json(path)
    protocol = _load_json(protocol_path)
    expected = declared_runpod_training_authorization(identity)
    body = dict(payload)
    claimed = body.pop("authorization_hash", None)
    if payload.get("schema_version") != RUNPOD_AUTHORIZATION_SCHEMA:
        raise AuthorizationError("RunPod TRAINING authorization schema is unusable")
    if not isinstance(claimed, str) or claimed != canonical_hash(body):
        raise AuthorizationError("RunPod TRAINING authorization_hash does not match its contents")
    if payload.get("authorization_hash") != expected["authorization_hash"]:
        raise AuthorizationError("RunPod TRAINING authorization drifted from the declared artifact")
    if (
        payload.get("authorization_status") != AUTHORIZATION_STATUS
        or payload.get("nick_authorized_plumbing") is not True
        or payload.get("nick_authorized_runpod_training_execution") is not True
        or payload.get("nick_authorized_local_training_execution") is not False
        or payload.get("execution_requires_cli_flag") is not True
        or payload.get("execution_authorized") is not False
        or payload.get("claim_authorized") is not False
        or payload.get("execution_authority") != "ABSENT"
        or payload.get("sealed_holdout_consumed") is not False
        or payload.get("holdout_untouched") is not True
        or payload.get("rewrites_registered_protocol") is not False
        or payload.get("authorizes_terra_protocol") is not False
        or payload.get("authorizes_local_9b_identity") is not False
        or payload.get("authorization_cli_flag") != RUNPOD_CLI_AUTHORIZATION_FLAG
        or payload.get("actor_identity_hash") != identity_digest(identity)
        or payload.get("consulted_terra_protocol_hash") != TERRA_PROTOCOL_HASH
        or payload.get("scope") != "RUNPOD_IN_SAMPLE_TRAINING_ONLY"
    ):
        raise AuthorizationError("RunPod TRAINING authorization must stay fail-closed")
    if protocol.get("protocol_hash") != TERRA_PROTOCOL_HASH:
        raise AuthorizationError("authorization does not consult the registered Terra protocol")
    if protocol.get("protocol", {}).get("registration_status") != "REGISTERED_NOT_AUTHORIZED":
        raise AuthorizationError("refusing to silently authorize the Terra protocol")
    return payload


def declared_volume_training_authorization(identity: Mapping[str, Any]) -> dict[str, Any]:
    """Nick-authorized 7b volume Ollama TRAINING plumbing. Not Terra, 9b, or 14b."""
    if not is_volume_identity(identity):
        raise AuthorizationError("volume authorization requires the volume 7b identity")
    digest = identity_digest(identity)
    authorization = {
        "schema_version": VOLUME_AUTHORIZATION_SCHEMA,
        "authorization_status": AUTHORIZATION_STATUS,
        "authorization_kind": "NICK_EXPLICIT_VOLUME_OLLAMA_TRAINING",
        "nick_authorized_plumbing": True,
        "nick_authorized_volume_training_execution": True,
        "nick_authorized_runpod_training_execution": False,
        "nick_authorized_local_training_execution": False,
        "execution_requires_cli_flag": True,
        "authorization_cli_flag": VOLUME_CLI_AUTHORIZATION_FLAG,
        "execution_authorized": False,
        "claim_authorized": False,
        "execution_authority": "ABSENT",
        "sealed_holdout_consumed": False,
        "holdout_untouched": True,
        "rewrites_registered_protocol": False,
        "authorizes_terra_protocol": False,
        "authorizes_local_9b_identity": False,
        "authorizes_runpod_14b_identity": False,
        "authorizes_full_16705_plan": False,
        "bound_to_registered_protocol": False,
        "scope": "VOLUME_IN_SAMPLE_TRAINING_ONLY",
        "provider": PROVIDER,
        "model_id": identity.get("model_id"),
        "volume_subsample_opportunities": VOLUME_SUBSAMPLE_OPPORTUNITIES,
        "gold_subsample_opportunities": GOLD_SUBSAMPLE_OPPORTUNITIES,
        "actor_identity_hash": digest,
        "consulted_terra_protocol_hash": TERRA_PROTOCOL_HASH,
        "source_document": "docs/AAT_V2_MODEL_EXECUTION_OPTIONS.md",
        "notes": (
            "Authorizes RunPod / remote Ollama 7b volume TRAINING plumbing under "
            "Nick's direction. The documented volume plan is the stratified "
            f"{VOLUME_SUBSAMPLE_OPPORTUNITIES}-opportunity subsample, not the "
            f"full 16,705. That run still requires {VOLUME_CLI_AUTHORIZATION_FLAG}. "
            "That flag does not authorize desktop qwen3.5:9b, gold qwen2.5:14b, "
            "or the Terra protocol. Broker execution_authority stays ABSENT. "
            "V1/V2 holdout stays unused."
        ),
    }
    authorization["authorization_hash"] = canonical_hash(authorization)
    return authorization


def load_volume_training_authorization(
    path: str | Path,
    *,
    identity: Mapping[str, Any],
    protocol_path: str | Path,
) -> dict[str, Any]:
    """Load Nick's volume-TRAINING authorization. Does not flip Terra, 9b, or 14b."""
    payload = _load_json(path)
    protocol = _load_json(protocol_path)
    expected = declared_volume_training_authorization(identity)
    body = dict(payload)
    claimed = body.pop("authorization_hash", None)
    if payload.get("schema_version") != VOLUME_AUTHORIZATION_SCHEMA:
        raise AuthorizationError("volume TRAINING authorization schema is unusable")
    if not isinstance(claimed, str) or claimed != canonical_hash(body):
        raise AuthorizationError("volume TRAINING authorization_hash does not match its contents")
    if payload.get("authorization_hash") != expected["authorization_hash"]:
        raise AuthorizationError("volume TRAINING authorization drifted from the declared artifact")
    if (
        payload.get("authorization_status") != AUTHORIZATION_STATUS
        or payload.get("nick_authorized_plumbing") is not True
        or payload.get("nick_authorized_volume_training_execution") is not True
        or payload.get("nick_authorized_runpod_training_execution") is not False
        or payload.get("nick_authorized_local_training_execution") is not False
        or payload.get("execution_requires_cli_flag") is not True
        or payload.get("execution_authorized") is not False
        or payload.get("claim_authorized") is not False
        or payload.get("execution_authority") != "ABSENT"
        or payload.get("sealed_holdout_consumed") is not False
        or payload.get("holdout_untouched") is not True
        or payload.get("rewrites_registered_protocol") is not False
        or payload.get("authorizes_terra_protocol") is not False
        or payload.get("authorizes_local_9b_identity") is not False
        or payload.get("authorizes_runpod_14b_identity") is not False
        or payload.get("authorizes_full_16705_plan") is not False
        or payload.get("authorization_cli_flag") != VOLUME_CLI_AUTHORIZATION_FLAG
        or payload.get("volume_subsample_opportunities") != VOLUME_SUBSAMPLE_OPPORTUNITIES
        or payload.get("gold_subsample_opportunities") != GOLD_SUBSAMPLE_OPPORTUNITIES
        or payload.get("actor_identity_hash") != identity_digest(identity)
        or payload.get("consulted_terra_protocol_hash") != TERRA_PROTOCOL_HASH
        or payload.get("scope") != "VOLUME_IN_SAMPLE_TRAINING_ONLY"
    ):
        raise AuthorizationError("volume TRAINING authorization must stay fail-closed")
    if protocol.get("protocol_hash") != TERRA_PROTOCOL_HASH:
        raise AuthorizationError("authorization does not consult the registered Terra protocol")
    if protocol.get("protocol", {}).get("registration_status") != "REGISTERED_NOT_AUTHORIZED":
        raise AuthorizationError("refusing to silently authorize the Terra protocol")
    return payload


def load_committed_ollama_training_authorization(
    path: str | Path,
    *,
    identity: Mapping[str, Any],
    protocol_path: str | Path,
) -> dict[str, Any]:
    """Load the matching local, RunPod, or volume authorization artifact."""
    payload = _load_json(path)
    schema = payload.get("schema_version")
    if schema == AUTHORIZATION_SCHEMA:
        if is_runpod_identity(identity):
            raise AuthorizationError(
                "local TRAINING authorization does not cover the RunPod 14b Actor"
            )
        if is_volume_identity(identity):
            raise AuthorizationError(
                "local TRAINING authorization does not cover the volume 7b Actor"
            )
        return load_local_training_authorization(
            path, identity=identity, protocol_path=protocol_path,
        )
    if schema == RUNPOD_AUTHORIZATION_SCHEMA:
        if is_volume_identity(identity):
            raise AuthorizationError(
                "RunPod TRAINING authorization does not cover the volume 7b Actor"
            )
        if not is_runpod_identity(identity):
            raise AuthorizationError(
                "RunPod TRAINING authorization does not cover the local qwen3.5:9b Actor"
            )
        return load_runpod_training_authorization(
            path, identity=identity, protocol_path=protocol_path,
        )
    if schema == VOLUME_AUTHORIZATION_SCHEMA:
        if is_runpod_identity(identity):
            raise AuthorizationError(
                "volume TRAINING authorization does not cover the RunPod 14b Actor"
            )
        if not is_volume_identity(identity):
            raise AuthorizationError(
                "volume TRAINING authorization does not cover the local qwen3.5:9b Actor"
            )
        return load_volume_training_authorization(
            path, identity=identity, protocol_path=protocol_path,
        )
    raise AuthorizationError("unrecognized Ollama TRAINING authorization schema")


def assert_full_run_authorized(
    *,
    authorization: Mapping[str, Any],
    authorize_local_training: bool = False,
    authorize_runpod_training: bool = False,
    authorize_volume_training: bool = False,
) -> None:
    """Full TRAINING requires the matching artifact *and* Nick's matching CLI flag."""
    if authorization.get("execution_requires_cli_flag") is not True:
        raise AuthorizationError("authorization artifact must still require the CLI flag")
    flags = (
        authorize_local_training,
        authorize_runpod_training,
        authorize_volume_training,
    )
    if sum(bool(flag) for flag in flags) > 1:
        raise AuthorizationError(
            "local, RunPod, and volume TRAINING flags cannot be combined; they "
            "authorize different Actors and none of them authorizes Terra"
        )
    required = authorization.get("authorization_cli_flag")
    if required == CLI_AUTHORIZATION_FLAG:
        if authorize_runpod_training:
            raise AuthorizationError(
                "RunPod TRAINING flag does not authorize the local qwen3.5:9b Actor"
            )
        if authorize_volume_training:
            raise AuthorizationError(
                "volume TRAINING flag does not authorize the local qwen3.5:9b Actor"
            )
        if not authorize_local_training:
            raise AuthorizationError(
                "full local TRAINING requires Nick's explicit "
                f"{CLI_AUTHORIZATION_FLAG} flag; the Terra protocol stays "
                "REGISTERED_NOT_AUTHORIZED"
            )
        return
    if required == RUNPOD_CLI_AUTHORIZATION_FLAG:
        if authorize_local_training:
            raise AuthorizationError(
                "local TRAINING flag does not authorize the RunPod 14b Actor"
            )
        if authorize_volume_training:
            raise AuthorizationError(
                "volume TRAINING flag does not authorize the RunPod 14b Actor"
            )
        if not authorize_runpod_training:
            raise AuthorizationError(
                "full RunPod TRAINING requires Nick's explicit "
                f"{RUNPOD_CLI_AUTHORIZATION_FLAG} flag; the Terra protocol stays "
                "REGISTERED_NOT_AUTHORIZED"
            )
        return
    if required == VOLUME_CLI_AUTHORIZATION_FLAG:
        if authorize_local_training:
            raise AuthorizationError(
                "local TRAINING flag does not authorize the volume 7b Actor"
            )
        if authorize_runpod_training:
            raise AuthorizationError(
                "RunPod TRAINING flag does not authorize the volume 7b Actor"
            )
        if not authorize_volume_training:
            raise AuthorizationError(
                "volume subsample TRAINING requires Nick's explicit "
                f"{VOLUME_CLI_AUTHORIZATION_FLAG} flag; the Terra protocol stays "
                "REGISTERED_NOT_AUTHORIZED"
            )
        return
    raise AuthorizationError("authorization artifact CLI flag is unusable")


def _assert_not_terra_or_deepseek(axes: Mapping[str, Any]) -> None:
    if axes.get("provider") == TERRA_PROVIDER or axes.get("model_id") == TERRA_MODEL_ID:
        raise IdentityError("Ollama identity cannot reuse the Terra provider or model id")
    if axes.get("model_hash") == TERRA_MODEL_HASH:
        raise IdentityError("Ollama model_hash collided with the Terra Actor")
    if axes.get("prompt_hash") == TERRA_PROMPT_HASH:
        raise IdentityError("Ollama prompt_hash collided with the Terra Actor")
    if axes.get("inference_hash") == TERRA_INFERENCE_HASH:
        raise IdentityError("Ollama inference_hash collided with the Terra Actor")
    if axes.get("provider") == DEEPSEEK.provider or axes.get("model_id") == "deepseek-flash":
        raise IdentityError("Ollama identity cannot reuse the DeepSeek Flash Actor")


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
