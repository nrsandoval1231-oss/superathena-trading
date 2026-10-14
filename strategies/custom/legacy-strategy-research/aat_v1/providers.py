"""Provider-scoped Actor identity.

AAT-V1 hardcodes one vendor: a fixed endpoint, a payload shaped for one
request API, a response reader that knows one output format, and a pricing
guard that only accepts one documentation domain.  That coupling is why the
registered protocol carries ``PROVIDER_MODEL_MUTABILITY`` as a *permanent*
limitation -- a provider swap could not be described, so it could only be
disclaimed.

A descriptor makes the vendor an explicit, hashed axis instead.  Identity is
scoped by provider, so ``{"provider": "openai", "model": X}`` and
``{"provider": "other", "model": X}`` are different Actors even when the model
string matches, which is the property the limitation was standing in for.

**This module changes no AAT-V1 behaviour.**  ``OPENAI`` reproduces the
registered transport, payload shape, response reading and identity digests
byte-for-byte; ``tests/test_aat_v1_identity_pinning.py`` holds those digests as
literals.  V1's protocol stays frozen and keeps its limitation -- the
limitation was true when V1 ran and a consumed holdout cannot be re-described.
What this buys is a V2 protocol that can bind a provider-scoped identity and so
does not inherit it.

Adding a vendor is a descriptor plus a pricing config whose ``source_url``
prefix is documented in that vendor's provenance record.  ``OPENAI`` stays the
only *V1-registered* provider: a consumed holdout cannot grow a second vendor.
``DEEPSEEK`` is a named descriptor for a V2 candidate / pilot identity.  It is
not inserted into ``_REGISTRY``, so ``registered_providers()`` remains
``("openai",)`` and V1 receipts keep their meaning.  ``OLLAMA`` is the local
Qwen TRAINING candidate descriptor.  It is also declared, not V1-registered,
and does not inherit Terra or DeepSeek evidence.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ..athena_adapter.contracts import canonical_hash
from .training import AATValidationError


@dataclass(frozen=True)
class ProviderDescriptor:
    """Everything vendor-specific about calling an Actor, in one hashable place."""

    provider: str
    endpoint: str
    pricing_schema: str
    pricing_source_prefix: str
    build_payload: Callable[[str, Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]],
                            Mapping[str, Any]]
    read_output_text: Callable[[Mapping[str, Any]], str]
    read_usage: Callable[[Mapping[str, Any]], tuple[int, int]]
    build_headers: Callable[[str], dict[str, str]]

    def model_hash(self, model_id: str) -> str:
        """Identity digest for a model *under this provider*.

        Scoping by provider is the whole point: the same model string served by
        a different vendor is a different Actor, and evidence must not transfer
        between them silently.
        """
        return canonical_hash({"provider": self.provider, "model": model_id})


def _openai_payload(
    model_id: str, packet: Mapping[str, Any], prompt: Any, spec: Mapping[str, Any],
) -> Mapping[str, Any]:
    """The registered V1 request body.  Field order and values are frozen."""
    return {
        "model": model_id,
        "store": False,
        "reasoning": {"effort": "low"},
        "max_output_tokens": spec["inference"]["max_output_tokens"],
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": prompt}]},
            {"role": "user", "content": [{
                "type": "input_text",
                "text": json.dumps(packet, sort_keys=True, separators=(",", ":")),
            }]},
        ],
        "text": {"format": {
            "type": "json_schema", "name": "aat_actor_decision",
            "strict": True, "schema": spec["action_schema"],
        }},
    }


def _openai_output_text(response: Mapping[str, Any]) -> str:
    if isinstance(response.get("output_text"), str):
        return response["output_text"]
    for output in response.get("output", []):
        if isinstance(output, Mapping):
            for content in output.get("content", []):
                if (
                    isinstance(content, Mapping)
                    and content.get("type") == "output_text"
                    and isinstance(content.get("text"), str)
                ):
                    return content["text"]
    raise AATValidationError("Actor response lacks output text")


def _openai_usage(response: Mapping[str, Any]) -> tuple[int, int]:
    usage = response.get("usage")
    if not isinstance(usage, Mapping):
        raise AATValidationError("Actor response lacks usage evidence")
    input_tokens, output_tokens = usage.get("input_tokens"), usage.get("output_tokens")
    if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
        raise AATValidationError("Actor usage evidence is malformed")
    return input_tokens, output_tokens


OPENAI = ProviderDescriptor(
    provider="openai",
    endpoint="https://api.openai.com/v1/responses",
    pricing_schema="openai-text-pricing-v1",
    pricing_source_prefix="https://developers.openai.com/",
    build_payload=_openai_payload,
    read_output_text=_openai_output_text,
    read_usage=_openai_usage,
    build_headers=lambda key: {
        "Authorization": f"Bearer {key}", "Content-Type": "application/json",
    },
)


def _deepseek_payload(
    model_id: str, packet: Mapping[str, Any], prompt: Any, spec: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Chat-completions body for the V2 DeepSeek Flash candidate Actor.

    Thinking is disabled and ``response_format`` asks for a JSON object. This is
    the B/C/D Actor path. Arm E compact turns are assembled by V2 deliberation
    code, not by silently reusing the Terra Responses payload.
    """
    inference = spec["inference"]
    return {
        "model": model_id,
        "messages": [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": json.dumps(packet, sort_keys=True, separators=(",", ":")),
            },
        ],
        "max_tokens": inference["max_output_tokens"],
        "response_format": inference.get("response_format", {"type": "json_object"}),
        "thinking": inference.get("thinking", {"type": "disabled"}),
        "stream": False,
    }


def _deepseek_output_text(response: Mapping[str, Any]) -> str:
    if isinstance(response.get("output_text"), str):
        return response["output_text"]
    choices = response.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], Mapping):
        message = choices[0].get("message")
        if isinstance(message, Mapping) and isinstance(message.get("content"), str):
            return message["content"]
    raise AATValidationError("Actor response lacks output text")


def _deepseek_usage(response: Mapping[str, Any]) -> tuple[int, int]:
    usage = response.get("usage")
    if not isinstance(usage, Mapping):
        raise AATValidationError("Actor response lacks usage evidence")
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    if not isinstance(prompt_tokens, int) or not isinstance(completion_tokens, int):
        raise AATValidationError("Actor usage evidence is malformed")
    return prompt_tokens, completion_tokens


DEEPSEEK = ProviderDescriptor(
    provider="deepseek",
    endpoint="https://api.deepseek.com/chat/completions",
    pricing_schema="deepseek-text-pricing-v1",
    pricing_source_prefix="https://api-docs.deepseek.com/",
    build_payload=_deepseek_payload,
    read_output_text=_deepseek_output_text,
    read_usage=_deepseek_usage,
    build_headers=lambda key: {
        "Authorization": f"Bearer {key}", "Content-Type": "application/json",
    },
)


def _ollama_payload(
    model_id: str, packet: Mapping[str, Any], prompt: Any, spec: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Chat body for the local Ollama Qwen TRAINING candidate.

    Thinking is disabled when the runtime honors ``think: false``. ``format``
    asks for a JSON object. This is the B/C/D Actor path; arm E compact turns
    are assembled by V2 deliberation code.
    """
    inference = spec["inference"]
    return {
        "model": model_id,
        "messages": [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": json.dumps(packet, sort_keys=True, separators=(",", ":")),
            },
        ],
        "stream": False,
        "think": False,
        "format": "json",
        "options": {"num_predict": inference["max_output_tokens"]},
    }


def _ollama_output_text(response: Mapping[str, Any]) -> str:
    if isinstance(response.get("output_text"), str):
        return response["output_text"]
    message = response.get("message")
    if isinstance(message, Mapping) and isinstance(message.get("content"), str):
        return message["content"]
    if isinstance(response.get("response"), str):
        return response["response"]
    raise AATValidationError("Actor response lacks output text")


def _ollama_usage(response: Mapping[str, Any]) -> tuple[int, int]:
    """Return Ollama ``prompt_eval_count`` / ``eval_count`` when present.

    Missing counts are not invented here. The TRAINING transport may fall back
    to a labeled byte/4 estimate; that estimate is not vendor usage.
    """
    prompt_tokens = response.get("prompt_eval_count")
    completion_tokens = response.get("eval_count")
    if not isinstance(prompt_tokens, int) or not isinstance(completion_tokens, int):
        raise AATValidationError("Actor usage evidence is malformed")
    if prompt_tokens < 0 or completion_tokens < 0:
        raise AATValidationError("Actor usage evidence is malformed")
    return prompt_tokens, completion_tokens


# RunPod HTTPS proxies 403 urllib's default ``Python-urllib/3.x``. A
# deliberate non-urllib UA is required for remote TRAINING; loopback gets
# the same header so live requests never fall back to urllib's default.
OLLAMA_USER_AGENT = "athena-trading/0.1 ollama-training"

OLLAMA = ProviderDescriptor(
    provider="ollama",
    endpoint="http://127.0.0.1:11434/api/chat",
    pricing_schema="ollama-local-unpriced-v1",
    pricing_source_prefix="https://github.com/ollama/",
    build_payload=_ollama_payload,
    read_output_text=_ollama_output_text,
    read_usage=_ollama_usage,
    build_headers=lambda _key: {
        "Content-Type": "application/json",
        "User-Agent": OLLAMA_USER_AGENT,
    },
)

#: V1 registry stays a singleton. DeepSeek and Ollama are declared, not registered.
_REGISTRY: dict[str, ProviderDescriptor] = {OPENAI.provider: OPENAI}


def register_provider(descriptor: ProviderDescriptor) -> None:
    """Add a vendor.  Re-registering an existing provider id is refused."""
    if not isinstance(descriptor, ProviderDescriptor):
        raise AATValidationError("provider descriptor is malformed")
    if descriptor.provider in _REGISTRY:
        raise AATValidationError(f"provider {descriptor.provider!r} is already registered")
    _REGISTRY[descriptor.provider] = descriptor


def get_provider(provider: str) -> ProviderDescriptor:
    """Look up a vendor, failing closed on an unknown id."""
    try:
        return _REGISTRY[provider]
    except KeyError:
        raise AATValidationError(f"unregistered Actor provider {provider!r}") from None


def registered_providers() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


def provider_identity(descriptor: ProviderDescriptor, *, model_id: str,
                      prompt: Any, inference: Mapping[str, Any],
                      action_schema: Mapping[str, Any]) -> dict[str, Any]:
    """The identity block a protocol registers, with the provider named in it.

    A V1 protocol records the same four digests without ``provider``; the
    values are unchanged, so a V1 receipt keeps verifying. A V2 protocol can
    bind the provider explicitly and drop the mutability limitation.
    """
    return {
        "provider": descriptor.provider,
        "model_id": model_id,
        "model_hash": descriptor.model_hash(model_id),
        "prompt_hash": canonical_hash(prompt),
        "inference_hash": canonical_hash(inference),
        "action_schema_hash": canonical_hash(action_schema),
    }
