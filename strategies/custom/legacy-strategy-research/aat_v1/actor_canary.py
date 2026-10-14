"""Fail-closed OpenAI transport canary for outcome-free AAT packets."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from ..athena_adapter.contracts import canonical_hash
from .providers import OPENAI, ProviderDescriptor
from .training import AATValidationError, TrainingRow

API_URL = OPENAI.endpoint
PROMPT = (
    "You are Athena's fixed research Actor. Use only the supplied opaque features "
    "and lessons. Return one allowed entry action. Never claim execution authority."
)
INFERENCE = {"endpoint": "responses", "reasoning_effort": "low", "store": False, "max_output_tokens": 256}
ACTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["action", "confidence", "horizon", "invalidation", "rationale"],
    "properties": {
        "action": {"type": "string", "enum": ["PASS", "ENTER_REDUCED", "ENTER_STANDARD", "ENTER_HIGH_CONVICTION"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "horizon": {"type": "string", "minLength": 1},
        "invalidation": {"type": "string", "minLength": 1},
        "rationale": {"type": "string", "minLength": 1},
    },
}
ARMS = ("B_MEMORYLESS", "C_NAIVE_MEMORY", "D_ATHENA")


def load_local_key(path: str | Path) -> str:
    """Read only OPENAI_API_KEY from an ignored local env file."""
    env_path = Path(path)
    if not env_path.is_file():
        raise AATValidationError("BLOCKED_MODEL_CONFIGURATION")
    for line in env_path.read_text(encoding="utf-8").splitlines():
        name, separator, value = line.partition("=")
        if separator and name.strip() == "OPENAI_API_KEY":
            key = value.strip().strip("\"'")
            if key:
                return key
    raise AATValidationError("BLOCKED_MODEL_CONFIGURATION")


def load_pricing(path: str | Path, *, model_id: str,
                 provider: ProviderDescriptor = OPENAI) -> Mapping[str, Any]:
    """Load a priced model, rejecting a quote sourced from another vendor.

    The source-URL prefix is provider-scoped: a quote lifted from the wrong
    vendor's documentation would silently misprice every ceiling downstream.
    """
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if (value.get("schema_version") != provider.pricing_schema
            or value.get("model_id") != model_id
            or float(value.get("input_usd_per_million_tokens", 0)) <= 0
            or float(value.get("output_usd_per_million_tokens", 0)) <= 0
            or not str(value.get("source_url", "")).startswith(provider.pricing_source_prefix)):
        raise AATValidationError("pricing configuration is invalid")
    return value


def validate_actor_identity(actor: Mapping[str, Any], *, model_id: str,
                           provider: ProviderDescriptor = OPENAI) -> None:
    expected = {
        "model_id": model_id,
        "model_hash": provider.model_hash(model_id),
        "prompt_hash": canonical_hash(PROMPT),
        "inference_hash": canonical_hash(INFERENCE),
        "action_schema_hash": canonical_hash(ACTION_SCHEMA),
    }
    if any(actor.get(key) != value for key, value in expected.items()):
        raise AATValidationError("registered Actor identity drift")


def build_actor_packet(
    row: TrainingRow, actor_identity: str,
    memory: Sequence[Mapping[str, Any]] = (),
) -> Mapping[str, Any]:
    # Canary callers leave memory empty. The four-arm runner supplies only
    # separately verified, budget-equal lesson projections.
    return {
        "candidate_hash": row.opportunity_id,
        "features": dict(row.features),
        "memory": [dict(item) for item in memory],
        "actor_identity": actor_identity,
    }


def build_actor_payload(model_id: str, packet: Mapping[str, Any],
                       provider: ProviderDescriptor = OPENAI) -> Mapping[str, Any]:
    return provider.build_payload(
        model_id, packet, PROMPT,
        {"inference": INFERENCE, "action_schema": ACTION_SCHEMA},
    )


def price_requests(rows: Sequence[TrainingRow], *, model_id: str, actor_identity: str,
                   pricing: Mapping[str, Any],
                   provider: ProviderDescriptor = OPENAI) -> Mapping[str, Any]:
    requests = [
        {"arm": arm, "opportunity_id": row.opportunity_id,
         "payload": build_actor_payload(
             model_id, build_actor_packet(row, actor_identity), provider)}
        for row in rows for arm in ARMS
    ]
    # UTF-8 byte length is a conservative token ceiling for text tokenization.
    input_ceiling = sum(len(json.dumps(item["payload"], sort_keys=True, separators=(",", ":")).encode("utf-8")) for item in requests)
    output_ceiling = len(requests) * INFERENCE["max_output_tokens"]
    per_request_costs = [
        (
            len(json.dumps(item["payload"], sort_keys=True, separators=(",", ":")).encode("utf-8"))
            * float(pricing["input_usd_per_million_tokens"])
            + INFERENCE["max_output_tokens"] * float(pricing["output_usd_per_million_tokens"])
        ) / 1_000_000
        for item in requests
    ]
    worst_cost = (
        input_ceiling * float(pricing["input_usd_per_million_tokens"])
        + output_ceiling * float(pricing["output_usd_per_million_tokens"])
    ) / 1_000_000
    return {
        "request_count": len(requests), "input_token_ceiling": input_ceiling,
        "output_token_ceiling": output_ceiling, "worst_case_cost_usd": worst_cost,
        "per_request_cost_upper_bound_usd": max(per_request_costs),
        "requests": requests,
    }


def _output_text(response: Mapping[str, Any],
                 provider: ProviderDescriptor = OPENAI) -> str:
    return provider.read_output_text(response)


def _validate_decision(response: Mapping[str, Any]) -> Mapping[str, Any]:
    try:
        decision = json.loads(_output_text(response))
    except json.JSONDecodeError as exc:
        raise AATValidationError("Actor output is not JSON") from exc
    if not isinstance(decision, Mapping) or set(decision) != set(ACTION_SCHEMA["required"]):
        raise AATValidationError("Actor output schema mismatch")
    if decision["action"] not in ACTION_SCHEMA["properties"]["action"]["enum"]:
        raise AATValidationError("Actor action is not allowed")
    if not isinstance(decision["confidence"], (int, float)) or not 0 <= decision["confidence"] <= 1:
        raise AATValidationError("Actor confidence is invalid")
    if not all(isinstance(decision[key], str) and decision[key] for key in ("horizon", "invalidation", "rationale")):
        raise AATValidationError("Actor text fields are invalid")
    return decision


def execute_transport_canary(
    rows: Sequence[TrainingRow], *, model_id: str, actor_identity: str,
    pricing: Mapping[str, Any], spend_ceiling_usd: float, token_ceiling: int,
    ledger_path: str | Path,
    api_key: str, transport: Callable[[Mapping[str, Any], str], Mapping[str, Any]] | None = None,
    request_offset: int = 0, provider: ProviderDescriptor = OPENAI,
) -> Mapping[str, Any]:
    ledger = Path(ledger_path)
    if ledger.exists():
        raise AATValidationError("refusing to overwrite canary ledger")
    priced = price_requests(rows, model_id=model_id, actor_identity=actor_identity, pricing=pricing)
    if priced["worst_case_cost_usd"] > spend_ceiling_usd:
        raise AATValidationError("worst-case cost exceeds spend ceiling")
    if priced["request_count"] > 30:
        raise AATValidationError("call ceiling exceeded")

    def live(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            provider.endpoint, data=body, headers=provider.build_headers(key), method="POST",
        )
        with urlopen(request, timeout=60) as response:  # nosec B310: fixed HTTPS endpoint
            value = json.loads(response.read().decode("utf-8"))
        if not isinstance(value, Mapping):
            raise AATValidationError(f"{provider.provider} response is malformed")
        return value

    ledger.parent.mkdir(parents=True, exist_ok=True)
    if not 0 <= request_offset < priced["request_count"]:
        raise AATValidationError("request offset is invalid")
    total_input = total_output = 0
    records = []
    for index, item in enumerate(priced["requests"][request_offset:], start=request_offset):
        payload = item["payload"]
        request_input_ceiling = len(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        if total_input + total_output + request_input_ceiling + INFERENCE["max_output_tokens"] > token_ceiling:
            raise AATValidationError("next request could exceed token ceiling")
        response = (transport or live)(payload, api_key)
        input_tokens, output_tokens = provider.read_usage(response)
        total_input += input_tokens
        total_output += output_tokens
        if total_input + total_output > token_ceiling:
            raise AATValidationError("reported usage exceeds token ceiling")
        actual_cost = (
            total_input * float(pricing["input_usd_per_million_tokens"])
            + total_output * float(pricing["output_usd_per_million_tokens"])
        ) / 1_000_000
        if actual_cost > spend_ceiling_usd:
            raise AATValidationError("reported usage exceeds spend ceiling")
        rejection_reason = None
        decision = None
        if response.get("model") != model_id:
            rejection_reason = "MODEL_IDENTITY_DRIFT"
        elif response.get("status") != "completed":
            rejection_reason = "RESPONSE_NOT_COMPLETED"
        else:
            try:
                decision = _validate_decision(response)
            except AATValidationError as exc:
                rejection_reason = str(exc)
        record = {
            "sequence": index + 1,
            "arm": item["arm"],
            "opportunity_id": item["opportunity_id"],
            "request_hash": canonical_hash(payload),
            "response_id": response.get("id"),
            "response_model": response.get("model"),
            "response_status": response.get("status"),
            "decision": decision,
            "decision_hash": canonical_hash(decision) if decision is not None else None,
            "accepted": rejection_reason is None,
            "rejection_reason": rejection_reason,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cumulative_cost_usd": actual_cost,
            "status": "TRANSPORT_CANARY_NOT_ADAPTATION",
            "execution_authority": "ABSENT",
        }
        with ledger.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
        records.append(record)
    return {
        "schema_version": "aat-v1-terra-transport-canary-v1",
        "status": "TRANSPORT_CANARY_NOT_ADAPTATION",
        "request_count": len(records),
        "accepted_count": sum(record["accepted"] for record in records),
        "rejected_count": sum(not record["accepted"] for record in records),
        "input_tokens": total_input,
        "output_tokens": total_output,
        "recorded_actual_cost_usd": records[-1]["cumulative_cost_usd"],
        "ledger_sha256": hashlib.sha256(ledger.read_bytes()).hexdigest(),
        "execution_authority": "ABSENT",
    }
