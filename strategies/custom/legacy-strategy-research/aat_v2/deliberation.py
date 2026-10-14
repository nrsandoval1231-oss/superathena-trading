"""Compact arm-E deliberation schema for the registered 4 x 64 token budget.

The local Qwen 100-opportunity pilot accepted 0/400 E-arm responses because
each turn required the five-field Actor object (``action``, ``confidence``,
``horizon``, ``invalidation``, ``rationale``). Those last three fields are
unbounded strings. At 64 output tokens the model hit ``done_reason: length``
before the JSON closed.

A later live DeepSeek Flash pilot (7 opportunities, 49 calls, not TRAINING)
accepted B/C/D 21/21 but E only 3/28: 24 ``deliberation output schema
mismatch`` and 1 ``OUTPUT_TRUNCATED``. Most rejects had completion counts
well under 64, so the failure was extra keys / wrong enums / Actor-shaped
payloads, not compact-schema overflow. Chat Completions only supports
``response_format: json_object`` (not ``json_schema``); the per-turn prompt
therefore carries an example json object.

Arm E stays equal-budget with one arm-D call: four turns, 64 tokens each,
256 total. This module does not raise TRAINING spend. It does not bump the
E-only token ceiling: worst-case compact payloads still fit, and a 64-token
RISK truncation is treated as extra-key verbosity, not budget exhaustion of
a valid compact object.

B/C/D still emit the five-field Actor schema. Only E uses the compact turns.
The registered protocol JSON is not rewritten; the compact schema is bound
by a non-authorizing amendment. ``execution_authority`` stays ``ABSENT``.
"""
from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ..athena_adapter.contracts import canonical_hash, canonical_json
from .arms import assert_equal_token_budget

AMENDMENT_SCHEMA = "athena-aat-v2-e-arm-compact-schema-amendment-v1"
AMENDMENT_KIND = "NON_AUTHORIZING_PROTOCOL_NOTE"
PROTOCOL_SCHEMA = "athena-aat-v2-registered-protocol-v1"

DELIBERATION_TURNS = 4
DELIBERATION_OUTPUT_TOKENS = 64
SINGLE_CALL_OUTPUT_TOKENS = 256
DELIBERATION_TURN_ROLES = ("BULL", "BEAR", "TRADER", "RISK")
STANCE_TURNS = ("BULL", "BEAR", "TRADER")
DECISION_TURN = "RISK"
STANCES = ("IN", "OUT")
CLAIMS = ("MACRO", "PRICE", "NONE")
LEGAL_ACTIONS = ("PASS", "ENTER_REDUCED", "ENTER_STANDARD", "ENTER_HIGH_CONVICTION")
STANCE_KEYS = ("turn", "stance", "confidence", "claim")
DECISION_KEYS = ("turn", "action", "confidence")
ACTOR_TEXT_KEYS = ("horizon", "invalidation", "rationale")
TRUNCATION_FINISH_REASONS = ("length", "max_tokens")

#: Conservative planning proxy used by AAT-V1 training plans.
BYTES_PER_TOKEN_PROXY = 4

#: Rejected-receipt preview. Long enough to diagnose extra keys; not a dump.
RAW_CONTENT_SNIPPET_CHARS = 512

OUTPUT_TRUNCATED = "OUTPUT_TRUNCATED"
INCOMPLETE_JSON = "INCOMPLETE_JSON"
SCHEMA_MISMATCH = "deliberation output schema mismatch"
INVALID_CONFIDENCE = "deliberation confidence is invalid"
INVALID_ACTION = "deliberation action is not allowed"

DELIBERATION_PROMPT = (
    "Fail-closed AAT-V2 arm-E turn. Return exactly one compact json object and "
    "nothing else: no markdown, no code fences, no commentary, no extra keys, "
    "no prose. Copy the EXAMPLE json OUTPUT shape for this turn. Never claim "
    "execution_authority. This is not TRAINING."
)


class DeliberationError(ValueError):
    """The compact E-arm schema cannot be used as specified."""


def conservative_token_count(text: str) -> int:
    """``utf-8 bytes / 4``, matching the AAT planning proxy. Minimum 1."""
    if not isinstance(text, str):
        raise DeliberationError("token estimate requires text")
    return max(1, len(text.encode("utf-8")) // BYTES_PER_TOKEN_PROXY)


def truncate_to_token_budget(text: str, *, max_output_tokens: int) -> str:
    """Cut ``text`` to the conservative byte budget for ``max_output_tokens``."""
    if max_output_tokens < 1:
        raise DeliberationError("token budgets must be positive")
    limit = max_output_tokens * BYTES_PER_TOKEN_PROXY
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    return encoded[:limit].decode("utf-8", errors="ignore")


def is_truncation_finish(response: Mapping[str, Any] | None, *, finish_reason: str | None = None) -> bool:
    """True when the provider stopped because the output budget was exhausted."""
    reason = finish_reason
    if reason is None and isinstance(response, Mapping):
        reason = _finish_reason(response)
    return reason in TRUNCATION_FINISH_REASONS


def example_compact_payload(turn: str) -> dict[str, Any]:
    """Short legal object for the prompt example. Shorter than worst-case."""
    role = _validate_turn(turn)
    if role == DECISION_TURN:
        return {"action": "PASS", "confidence": 0.5, "turn": role}
    return {"claim": "NONE", "confidence": 0.5, "stance": "OUT", "turn": role}


def turn_system_prompt(turn: str) -> str:
    """Per-turn system prompt with an example json object.

    DeepSeek Chat Completions JSON mode requires the word ``json`` plus an
    example of the desired shape. ``json_schema`` is not available on this
    endpoint, so the example is the schema pin.
    """
    role = _validate_turn(turn)
    example = json.dumps(example_compact_payload(role), separators=(",", ":"), sort_keys=True)
    if role == DECISION_TURN:
        contract = (
            "This turn is RISK. Required keys: turn, action, confidence. "
            "turn must equal RISK. action must be one of PASS, ENTER_REDUCED, "
            "ENTER_STANDARD, ENTER_HIGH_CONVICTION. confidence must be a number "
            "in [0, 1]. Do not emit stance, claim, horizon, invalidation, "
            "rationale, or extra keys."
        )
    else:
        contract = (
            f"This turn is {role}. Required keys: turn, stance, confidence, claim. "
            f"turn must equal {role}. stance must be IN or OUT. claim must be "
            "MACRO, PRICE, or NONE. confidence must be a number in [0, 1]. "
            "Do not emit action, horizon, invalidation, rationale, or extra keys."
        )
    return (
        f"{DELIBERATION_PROMPT} {contract} EXAMPLE json OUTPUT: {example}"
    )


def deliberation_plan() -> dict[str, Any]:
    """Hashable compact-schema plan. Equal-budget with one 256-token call."""
    assert_equal_token_budget(
        deliberation_turns=DELIBERATION_TURNS,
        per_turn_output_tokens=DELIBERATION_OUTPUT_TOKENS,
        single_call_output_tokens=SINGLE_CALL_OUTPUT_TOKENS,
    )
    if DELIBERATION_TURN_ROLES != ("BULL", "BEAR", "TRADER", "RISK"):
        raise DeliberationError("turn roles must stay bull, bear, trader, risk")
    plan = {
        "schema_version": AMENDMENT_SCHEMA,
        "turns": DELIBERATION_TURNS,
        "turn_roles": list(DELIBERATION_TURN_ROLES),
        "per_turn_output_tokens": DELIBERATION_OUTPUT_TOKENS,
        "single_call_output_tokens": SINGLE_CALL_OUTPUT_TOKENS,
        "stance_turns": list(STANCE_TURNS),
        "decision_turn": DECISION_TURN,
        "stances": list(STANCES),
        "claims": list(CLAIMS),
        "legal_actions": list(LEGAL_ACTIONS),
        "stance_keys": list(STANCE_KEYS),
        "decision_keys": list(DECISION_KEYS),
        "unbounded_text_fields": False,
        "prompt": DELIBERATION_PROMPT,
        "turn_prompts": {role: turn_system_prompt(role) for role in DELIBERATION_TURN_ROLES},
        "response_format": {"type": "json_object"},
        "json_schema_not_available_on_chat_completions": True,
    }
    plan["deliberation_hash"] = canonical_hash(plan)
    return plan


def turn_instruction(turn: str) -> dict[str, Any]:
    """Closed-enum emit contract for one E-arm turn. No free-text fields.

    Enums are pipe-separated strings so Flash cannot copy a JSON array into
    ``stance`` / ``claim`` / ``action``. The example object is the emit shape.
    """
    role = _validate_turn(turn)
    example = example_compact_payload(role)
    if role == DECISION_TURN:
        return {
            "turn": role,
            "required_keys": list(DECISION_KEYS),
            "forbidden_keys": ["stance", "claim", *ACTOR_TEXT_KEYS],
            "action_one_of": "|".join(LEGAL_ACTIONS),
            "confidence": "number in [0,1]",
            "example_json": example,
        }
    return {
        "turn": role,
        "required_keys": list(STANCE_KEYS),
        "forbidden_keys": ["action", *ACTOR_TEXT_KEYS],
        "stance_one_of": "|".join(STANCES),
        "claim_one_of": "|".join(CLAIMS),
        "confidence": "number in [0,1]",
        "example_json": example,
    }


def compact_user_payload(
    packet: Mapping[str, Any],
    *,
    turn: str,
    prior_turns: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """User-message body for one E turn: packet, emit contract, and prior turns.

    Later turns must see earlier compact outputs so RISK can adjudicate the
    debate rather than emit an isolated schema object.
    """
    role = _validate_turn(turn)
    payload: dict[str, Any] = {
        "packet": dict(packet),
        "turn": role,
        "emit": turn_instruction(turn),
        "example_json": example_compact_payload(role),
    }
    if prior_turns:
        if role == DELIBERATION_TURN_ROLES[0]:
            raise DeliberationError("the first deliberation turn cannot carry prior turns")
        payload["prior_turns"] = [dict(item) for item in prior_turns]
    return payload


def worst_case_compact_payloads() -> dict[str, dict[str, Any]]:
    """Largest legal compact object per turn role. Used to prove the budget."""
    payloads = {
        role: {
            "turn": role,
            "stance": "OUT",
            "confidence": 1.0,
            "claim": "PRICE",
        }
        for role in STANCE_TURNS
    }
    payloads[DECISION_TURN] = {
        "turn": DECISION_TURN,
        "action": "ENTER_HIGH_CONVICTION",
        "confidence": 1.0,
    }
    return payloads


def assert_compact_payloads_fit_budget(
    payloads: Mapping[str, Mapping[str, Any]] | None = None,
    *,
    max_output_tokens: int = DELIBERATION_OUTPUT_TOKENS,
) -> dict[str, int]:
    """Refuse a compact schema whose worst-case serialization exceeds the budget."""
    items = payloads if payloads is not None else worst_case_compact_payloads()
    counts: dict[str, int] = {}
    for role, payload in items.items():
        serialized = canonical_json(payload)
        tokens = conservative_token_count(serialized)
        counts[str(role)] = tokens
        if tokens > max_output_tokens:
            raise DeliberationError(
                f"compact payload for {role} needs {tokens} tokens; "
                f"budget is {max_output_tokens}"
            )
    return counts


def raw_content_snippet(
    content: str | None, *, limit: int = RAW_CONTENT_SNIPPET_CHARS,
) -> str | None:
    """Redacted preview of rejected model content. ``None`` means no content."""
    if not isinstance(content, str):
        return None
    text = content.replace("\x00", "")
    if len(text) > limit:
        return text[:limit]
    return text


def parse_deliberation_turn(
    content: str,
    *,
    turn: str,
    finish_reason: str | None = None,
    done_reason: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Parse one E-arm turn. Truncated or unbounded Actor JSON is not accepted.

    Minimal fail-closed coercions: markdown fences, enum case, and numeric
    confidence strings. Extra keys, missing keys, synonyms, and Actor-shaped
    payloads still mismatch.
    """
    role = _validate_turn(turn)
    truncated = (finish_reason in TRUNCATION_FINISH_REASONS) or (
        done_reason in TRUNCATION_FINISH_REASONS
    )
    if not isinstance(content, str) or not content.strip():
        return None, OUTPUT_TRUNCATED if truncated else INCOMPLETE_JSON
    try:
        parsed = json.loads(_json_text(content))
    except json.JSONDecodeError:
        return None, OUTPUT_TRUNCATED if truncated else INCOMPLETE_JSON
    if not isinstance(parsed, Mapping):
        return None, SCHEMA_MISMATCH
    expected_keys = DECISION_KEYS if role == DECISION_TURN else STANCE_KEYS
    if set(parsed) != set(expected_keys):
        return None, SCHEMA_MISMATCH
    if _closed_enum(parsed.get("turn"), DELIBERATION_TURN_ROLES) != role:
        return None, SCHEMA_MISMATCH
    confidence = _parse_confidence(parsed.get("confidence"))
    if confidence is None:
        return None, INVALID_CONFIDENCE
    if role == DECISION_TURN:
        action = _closed_enum(parsed.get("action"), LEGAL_ACTIONS)
        if action is None:
            return None, INVALID_ACTION
        return {"action": action, "confidence": confidence, "turn": role}, None
    stance = _closed_enum(parsed.get("stance"), STANCES)
    claim = _closed_enum(parsed.get("claim"), CLAIMS)
    if stance is None or claim is None:
        return None, SCHEMA_MISMATCH
    return {
        "claim": claim,
        "confidence": confidence,
        "stance": stance,
        "turn": role,
    }, None


def scored_action_from_turns(turns: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The RISK turn is the scored Actor action. Earlier turns are debate only."""
    if len(turns) != DELIBERATION_TURNS:
        raise DeliberationError("deliberation requires exactly four accepted turns")
    roles = tuple(item.get("turn") for item in turns)
    if roles != DELIBERATION_TURN_ROLES:
        raise DeliberationError("deliberation turns must be BULL, BEAR, TRADER, RISK")
    decision = turns[-1]
    return {
        "action": decision["action"],
        "confidence": float(decision["confidence"]),
        "source_turn": DECISION_TURN,
        "execution_authority": "ABSENT",
    }


def load_e_arm_amendment(path: str | Path, *, protocol_path: str | Path) -> dict[str, Any]:
    """Load the non-authorizing compact-schema note. Does not rewrite the protocol."""
    amendment = _load_json(path)
    protocol = _load_json(protocol_path)
    payload = dict(amendment)
    claimed = payload.pop("amendment_hash", None)
    if (
        amendment.get("schema_version") != AMENDMENT_SCHEMA
        or amendment.get("amendment_kind") != AMENDMENT_KIND
        or amendment.get("rewrites_registered_protocol") is not False
        or claimed != canonical_hash(payload)
    ):
        raise DeliberationError("E-arm amendment is unusable")
    if amendment.get("base_protocol_hash") != protocol.get("protocol_hash"):
        raise DeliberationError("E-arm amendment does not bind the registered protocol")
    if protocol.get("schema_version") != PROTOCOL_SCHEMA:
        raise DeliberationError("registered protocol schema is unexpected")
    if (
        amendment.get("registration_status") != "REGISTERED_NOT_AUTHORIZED"
        or amendment.get("execution_authorized") is not False
        or amendment.get("claim_authorized") is not False
        or amendment.get("execution_authority") != "ABSENT"
        or amendment.get("sealed_holdout_consumed") is not False
        or amendment.get("training_spend_unchanged") is not True
    ):
        raise DeliberationError("E-arm amendment must not authorize TRAINING")
    expected = deliberation_plan()
    bound = amendment.get("deliberation")
    if not isinstance(bound, Mapping) or bound.get("deliberation_hash") != expected["deliberation_hash"]:
        raise DeliberationError("E-arm amendment deliberation hash drifted")
    return amendment


def _validate_turn(turn: str) -> str:
    if turn not in DELIBERATION_TURN_ROLES:
        raise DeliberationError(f"unknown deliberation turn {turn!r}")
    return turn


def _json_text(content: str) -> str:
    """Strip optional markdown fences. Does not repair truncated JSON."""
    text = content.strip()
    if not text.startswith("```"):
        return text
    text = text[3:]
    if text[:4].lower() == "json":
        text = text[4:]
    text = text.strip()
    if text.endswith("```"):
        text = text[:-3].strip()
    return text


def _closed_enum(value: Any, allowed: Sequence[str]) -> str | None:
    if not isinstance(value, str):
        return None
    token = value.strip().upper()
    if token in allowed:
        return token
    return None


def _parse_confidence(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    if not math.isfinite(number) or not 0 <= number <= 1:
        return None
    return number


def _finish_reason(response: Mapping[str, Any]) -> str | None:
    done = response.get("done_reason")
    if isinstance(done, str) and done:
        return done
    choices = response.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], Mapping):
        finish = choices[0].get("finish_reason")
        if isinstance(finish, str) and finish:
            return finish
    return None


def _load_json(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    text = str(target).lower()
    if "holdout" in text or "sealed" in text:
        raise DeliberationError("holdout paths are forbidden")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeliberationError("E-arm amendment input is unreadable") from exc
    if not isinstance(value, dict):
        raise DeliberationError("E-arm amendment input is not an object")
    return value
