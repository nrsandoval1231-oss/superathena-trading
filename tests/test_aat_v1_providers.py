import json

import pytest

from athena_trading.aat_v1 import AATValidationError
from athena_trading.aat_v1.actor_canary import (
    ACTION_SCHEMA,
    INFERENCE,
    PROMPT,
    build_actor_payload,
    load_pricing,
    validate_actor_identity,
)
from athena_trading.aat_v1.providers import (
    DEEPSEEK,
    OLLAMA,
    OLLAMA_USER_AGENT,
    OPENAI,
    ProviderDescriptor,
    get_provider,
    provider_identity,
    register_provider,
    registered_providers,
)

MODEL = "gpt-5.6-terra"


def _other_provider(name="acme"):
    return ProviderDescriptor(
        provider=name,
        endpoint="https://api.example.invalid/v1/chat",
        pricing_schema="acme-text-pricing-v1",
        pricing_source_prefix="https://docs.example.invalid/",
        build_payload=lambda model_id, packet, prompt, spec: {"m": model_id, "p": packet},
        read_output_text=lambda response: response["text"],
        read_usage=lambda response: (response["tin"], response["tout"]),
        build_headers=lambda key: {"X-Key": key},
    )


def test_openai_descriptor_reproduces_the_registered_identity():
    identity = provider_identity(
        OPENAI, model_id=MODEL, prompt=PROMPT, inference=INFERENCE, action_schema=ACTION_SCHEMA
    )
    assert identity["model_hash"] == (
        "9c4aaaa136ed098624bee45f5f75d0654f4d56ea526fc4cc51a1f3f3bf1ae5db"
    )
    assert identity["prompt_hash"] == (
        "b7fa5ec9928d3ec22225bd757aa25b408ffdc9a5d3897bf8717a9d7d44bca88a"
    )
    assert identity["provider"] == "openai"


def test_identity_is_scoped_by_provider_not_by_model_name():
    """The same model string under a different vendor is a different Actor."""
    assert _other_provider().model_hash(MODEL) != OPENAI.model_hash(MODEL)
    assert DEEPSEEK.model_hash(MODEL) != OPENAI.model_hash(MODEL)


def test_deepseek_descriptor_is_declared_not_v1_registered():
    assert DEEPSEEK.provider == "deepseek"
    assert DEEPSEEK.endpoint == "https://api.deepseek.com/chat/completions"
    assert DEEPSEEK.pricing_schema == "deepseek-text-pricing-v1"
    assert "deepseek" not in registered_providers()
    with pytest.raises(AATValidationError, match="unregistered"):
        get_provider("deepseek")
    payload = DEEPSEEK.build_payload(
        "deepseek-flash",
        {"candidate_hash": "abc"},
        "pilot",
        {"inference": {"max_output_tokens": 512, "thinking": {"type": "disabled"},
                       "response_format": {"type": "json_object"}}},
    )
    assert payload["model"] == "deepseek-flash"
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["max_tokens"] == 512
    assert "input" not in payload


def test_v1_identity_validation_still_passes_under_the_descriptor():
    actor = {
        "model_id": MODEL,
        "model_hash": OPENAI.model_hash(MODEL),
        "prompt_hash": provider_identity(
            OPENAI, model_id=MODEL, prompt=PROMPT, inference=INFERENCE,
            action_schema=ACTION_SCHEMA)["prompt_hash"],
        "inference_hash": provider_identity(
            OPENAI, model_id=MODEL, prompt=PROMPT, inference=INFERENCE,
            action_schema=ACTION_SCHEMA)["inference_hash"],
        "action_schema_hash": provider_identity(
            OPENAI, model_id=MODEL, prompt=PROMPT, inference=INFERENCE,
            action_schema=ACTION_SCHEMA)["action_schema_hash"],
    }
    validate_actor_identity(actor, model_id=MODEL)
    actor["model_hash"] = _other_provider().model_hash(MODEL)
    with pytest.raises(AATValidationError):
        validate_actor_identity(actor, model_id=MODEL)


def test_payload_shape_is_unchanged_for_openai():
    payload = build_actor_payload(MODEL, {"candidate_hash": "abc"})
    assert payload["model"] == MODEL
    assert payload["store"] is False
    assert payload["max_output_tokens"] == INFERENCE["max_output_tokens"]
    assert payload["input"][0]["content"][0]["text"] == PROMPT
    assert payload["text"]["format"]["schema"] == ACTION_SCHEMA


def test_a_different_provider_builds_a_different_payload():
    payload = build_actor_payload(MODEL, {"candidate_hash": "abc"}, _other_provider())
    assert payload == {"m": MODEL, "p": {"candidate_hash": "abc"}}


def test_unregistered_provider_fails_closed():
    with pytest.raises(AATValidationError):
        get_provider("nope")


def test_ollama_descriptor_is_declared_not_v1_registered():
    assert OLLAMA.provider == "ollama"
    assert OLLAMA.endpoint == "http://127.0.0.1:11434/api/chat"
    assert OLLAMA.pricing_schema == "ollama-local-unpriced-v1"
    assert "ollama" not in registered_providers()
    with pytest.raises(AATValidationError, match="unregistered"):
        get_provider("ollama")
    payload = OLLAMA.build_payload(
        "qwen3.5:9b",
        {"candidate_hash": "abc"},
        "local-training",
        {"inference": {"max_output_tokens": 256}},
    )
    assert payload["model"] == "qwen3.5:9b"
    assert payload["think"] is False
    assert payload["format"] == "json"
    assert payload["options"]["num_predict"] == 256
    assert "input" not in payload
    headers = OLLAMA.build_headers("")
    assert headers["Content-Type"] == "application/json"
    assert headers["User-Agent"] == OLLAMA_USER_AGENT
    assert "urllib" not in headers["User-Agent"].lower()


def test_openai_is_the_only_registered_provider():
    """A second vendor is a V2 candidate identity, not a V1 registry default."""
    assert registered_providers() == ("openai",)


def test_registering_a_duplicate_provider_is_refused():
    descriptor = _other_provider("dupe-check")
    register_provider(descriptor)
    try:
        assert "dupe-check" in registered_providers()
        with pytest.raises(AATValidationError):
            register_provider(_other_provider("dupe-check"))
    finally:
        from athena_trading.aat_v1 import providers
        providers._REGISTRY.pop("dupe-check", None)


def test_pricing_from_the_wrong_vendors_documentation_is_rejected(tmp_path):
    path = tmp_path / "pricing.json"
    path.write_text(json.dumps({
        "schema_version": "openai-text-pricing-v1", "model_id": MODEL,
        "input_usd_per_million_tokens": 1.0, "output_usd_per_million_tokens": 2.0,
        "source_url": "https://docs.example.invalid/pricing",
    }), encoding="utf-8")
    with pytest.raises(AATValidationError):
        load_pricing(path, model_id=MODEL)


def test_pricing_schema_is_provider_scoped(tmp_path):
    path = tmp_path / "pricing.json"
    path.write_text(json.dumps({
        "schema_version": "acme-text-pricing-v1", "model_id": MODEL,
        "input_usd_per_million_tokens": 1.0, "output_usd_per_million_tokens": 2.0,
        "source_url": "https://docs.example.invalid/pricing",
    }), encoding="utf-8")
    assert load_pricing(path, model_id=MODEL, provider=_other_provider())["model_id"] == MODEL
    with pytest.raises(AATValidationError):
        load_pricing(path, model_id=MODEL)


def test_registered_pricing_config_still_loads():
    pricing = load_pricing(
        "configs/openai_gpt_5_6_terra_pricing_2026-09-03.json", model_id=MODEL
    )
    assert pricing["schema_version"] == "openai-text-pricing-v1"
