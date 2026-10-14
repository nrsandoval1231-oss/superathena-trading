import json
from pathlib import Path

import pytest

from athena_trading.athena_adapter.contracts import canonical_hash
from athena_trading.aat_v2.arms import assert_equal_token_budget
from athena_trading.aat_v2.deliberation import (
    DELIBERATION_OUTPUT_TOKENS,
    DELIBERATION_PROMPT,
    DELIBERATION_TURN_ROLES,
    DELIBERATION_TURNS,
    OUTPUT_TRUNCATED,
    RAW_CONTENT_SNIPPET_CHARS,
    SINGLE_CALL_OUTPUT_TOKENS,
    DeliberationError,
    assert_compact_payloads_fit_budget,
    compact_user_payload,
    conservative_token_count,
    deliberation_plan,
    example_compact_payload,
    load_e_arm_amendment,
    parse_deliberation_turn,
    raw_content_snippet,
    scored_action_from_turns,
    truncate_to_token_budget,
    turn_system_prompt,
    worst_case_compact_payloads,
)


ROOT = Path(__file__).parents[1]
PROTOCOL = ROOT / "configs/aat_v2_registered_protocol_v1.json"
AMENDMENT = ROOT / "configs/aat_v2_e_arm_compact_schema_amendment_v1.json"
PLAN = ROOT / "configs/aat_v2_training_plan_v2.json"
CONTRACT = ROOT / "configs/aat_v2_claim_contract_v1.json"
MISMATCH = ROOT / "configs/fixtures/deepseek_flash_e_arm_mismatch_v1.json"

VERBOSE_ACTOR_JSON = json.dumps({
    "action": "ENTER_STANDARD",
    "confidence": 0.62,
    "horizon": "hold through the session close at 15:45 ET",
    "invalidation": "a break of the opening-range low on a closing basis",
    "rationale": (
        "Overnight macro surprise supports continuation into the range "
        "and the packet does not justify high conviction sizing."
    ),
}, separators=(",", ":"))


def test_compact_payloads_fit_the_registered_64_token_budget():
    counts = assert_compact_payloads_fit_budget()
    assert max(counts.values()) < DELIBERATION_OUTPUT_TOKENS
    assert_equal_token_budget(
        deliberation_turns=DELIBERATION_TURNS,
        per_turn_output_tokens=DELIBERATION_OUTPUT_TOKENS,
        single_call_output_tokens=SINGLE_CALL_OUTPUT_TOKENS,
    )


def test_five_field_actor_json_is_truncated_under_the_e_arm_budget():
    """The Qwen 0/400 failure: unbounded Actor text does not close at 64 tokens."""
    assert conservative_token_count(VERBOSE_ACTOR_JSON) > DELIBERATION_OUTPUT_TOKENS
    cut = truncate_to_token_budget(
        VERBOSE_ACTOR_JSON, max_output_tokens=DELIBERATION_OUTPUT_TOKENS,
    )
    with pytest.raises(json.JSONDecodeError):
        json.loads(cut)
    parsed, reason = parse_deliberation_turn(
        cut, turn="RISK", finish_reason="length", done_reason="length",
    )
    assert parsed is None
    assert reason == OUTPUT_TRUNCATED


def test_complete_compact_json_is_accepted_at_64_tokens():
    payloads = worst_case_compact_payloads()
    accepted = []
    for role, payload in payloads.items():
        text = json.dumps(payload, separators=(",", ":"))
        assert conservative_token_count(text) <= DELIBERATION_OUTPUT_TOKENS
        parsed, reason = parse_deliberation_turn(text, turn=role, finish_reason="stop")
        assert reason is None
        assert parsed == payload
        accepted.append(parsed)
    scored = scored_action_from_turns(accepted)
    assert scored["action"] == "ENTER_HIGH_CONVICTION"
    assert scored["execution_authority"] == "ABSENT"


def test_later_e_turns_receive_prior_compact_outputs():
    packet = {"schema_version": "athena-aat-v2-actor-packet-v1", "features": {"opaque": 1}}
    bull = compact_user_payload(packet, turn="BULL")
    assert "prior_turns" not in bull
    assert bull["example_json"] == example_compact_payload("BULL")
    assert bull["emit"]["example_json"] == bull["example_json"]
    assert bull["emit"]["stance_one_of"] == "IN|OUT"
    assert "action" not in bull["emit"]
    with pytest.raises(DeliberationError, match="first deliberation turn"):
        compact_user_payload(packet, turn="BULL", prior_turns=({"turn": "BULL"},))
    priors = (
        {"turn": "BULL", "stance": "IN", "confidence": 0.7, "claim": "MACRO"},
        {"turn": "BEAR", "stance": "OUT", "confidence": 0.6, "claim": "PRICE"},
        {"turn": "TRADER", "stance": "IN", "confidence": 0.55, "claim": "MACRO"},
    )
    risk = compact_user_payload(packet, turn="RISK", prior_turns=priors)
    assert [item["turn"] for item in risk["prior_turns"]] == ["BULL", "BEAR", "TRADER"]
    assert risk["emit"]["action_one_of"].startswith("PASS|")
    assert "stance" not in risk["emit"]


def test_ollama_done_reason_length_is_treated_as_truncation():
    parsed, reason = parse_deliberation_turn(
        '{"turn":"BULL","stance":"IN","confidence":0.7,"claim":"MAC',
        turn="BULL",
        done_reason="length",
    )
    assert parsed is None
    assert reason == OUTPUT_TRUNCATED


def test_unbounded_actor_object_is_not_a_compact_e_turn():
    parsed, reason = parse_deliberation_turn(
        VERBOSE_ACTOR_JSON, turn="RISK", finish_reason="stop",
    )
    assert parsed is None
    assert reason == "deliberation output schema mismatch"


def test_amendment_is_non_authorizing_and_does_not_rewrite_the_protocol():
    amendment = load_e_arm_amendment(AMENDMENT, protocol_path=PROTOCOL)
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    expected = deliberation_plan()
    assert amendment["rewrites_registered_protocol"] is False
    assert amendment["registration_status"] == "REGISTERED_NOT_AUTHORIZED"
    assert amendment["execution_authorized"] is False
    assert amendment["claim_authorized"] is False
    assert amendment["execution_authority"] == "ABSENT"
    assert amendment["sealed_holdout_consumed"] is False
    assert amendment["training_spend_unchanged"] is True
    assert amendment["base_protocol_hash"] == protocol["protocol_hash"]
    assert protocol["protocol_hash"] == "85d97d923f7b502dea20a936abe6334b57df64a677afdb6510376c5ea5b08027"
    assert protocol["protocol"]["arms"]["deliberation"]["per_turn_output_tokens"] == 64
    assert plan["max_output_tokens_per_deliberation_turn"] == 64
    assert plan["output_token_ceiling"] == 17105920
    assert plan["execution_authorized"] is False
    assert contract["contract_hash"] == "d41d17982495305f341930c6ac15e9e0680eba554f6e6c650df7fd888638b813"
    assert contract["execution_authority"] == "ABSENT"
    assert protocol["execution_authority"] == "ABSENT"
    assert protocol["protocol"]["execution_authority"] == "ABSENT"
    assert amendment["deliberation"]["deliberation_hash"] == expected["deliberation_hash"]
    assert amendment["deliberation"]["turn_roles"] == list(DELIBERATION_TURN_ROLES)


def test_tampered_amendment_hash_is_refused(tmp_path):
    payload = json.loads(AMENDMENT.read_text(encoding="utf-8"))
    payload["purpose"] = "silently authorize TRAINING"
    path = tmp_path / "amendment.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DeliberationError, match="unusable"):
        load_e_arm_amendment(path, protocol_path=PROTOCOL)


def test_authorizing_amendment_is_refused(tmp_path):
    payload = json.loads(AMENDMENT.read_text(encoding="utf-8"))
    payload["execution_authorized"] = True
    body = dict(payload)
    body.pop("amendment_hash")
    payload["amendment_hash"] = canonical_hash(body)
    path = tmp_path / "amendment.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DeliberationError, match="must not authorize"):
        load_e_arm_amendment(path, protocol_path=PROTOCOL)


def test_per_turn_prompt_pins_example_json_and_keeps_json_object():
    plan = deliberation_plan()
    assert plan["per_turn_output_tokens"] == 64
    assert plan["response_format"] == {"type": "json_object"}
    assert plan["json_schema_not_available_on_chat_completions"] is True
    for role in DELIBERATION_TURN_ROLES:
        prompt = turn_system_prompt(role)
        assert prompt.startswith(DELIBERATION_PROMPT)
        assert "EXAMPLE json OUTPUT" in prompt
        assert role in prompt
        assert "json_schema" not in prompt
        example = json.dumps(example_compact_payload(role), separators=(",", ":"), sort_keys=True)
        assert example in prompt
        assert plan["turn_prompts"][role] == prompt


def test_live_flash_mismatch_fixtures_fail_closed():
    envelope = json.loads(MISMATCH.read_text(encoding="utf-8"))
    assert envelope["execution_authority"] == "ABSENT"
    cases = envelope["cases"]
    assert set(cases) >= {
        "extra_keys", "missing_claim", "wrong_turn_string",
        "actor_shaped_payload", "copied_emit_contract", "truncated_json",
    }
    for name, case in cases.items():
        parsed, reason = parse_deliberation_turn(
            case["content"],
            turn=case["turn"],
            finish_reason=case.get("finish_reason", "stop"),
        )
        assert parsed is None, name
        assert reason == case["rejection_reason"], name
        preview = raw_content_snippet(case["content"])
        assert preview
        assert preview in case["content"] or preview == case["content"][:RAW_CONTENT_SNIPPET_CHARS]


def test_lowercase_enums_and_numeric_strings_are_accepted():
    parsed, reason = parse_deliberation_turn(
        '{"turn":"trader","stance":"out","confidence":"0.5","claim":"none"}',
        turn="TRADER",
        finish_reason="stop",
    )
    assert reason is None
    assert parsed == {
        "claim": "NONE", "confidence": 0.5, "stance": "OUT", "turn": "TRADER",
    }


def test_markdown_fence_around_compact_json_is_accepted():
    payload = example_compact_payload("RISK")
    fenced = "```json\n" + json.dumps(payload, separators=(",", ":")) + "\n```"
    parsed, reason = parse_deliberation_turn(fenced, turn="RISK", finish_reason="stop")
    assert reason is None
    assert parsed == payload


def test_boolean_confidence_is_rejected():
    parsed, reason = parse_deliberation_turn(
        '{"turn":"RISK","action":"PASS","confidence":true}',
        turn="RISK",
        finish_reason="stop",
    )
    assert parsed is None
    assert reason == "deliberation confidence is invalid"


def test_rejected_content_snippet_is_capped():
    blob = "x" * (RAW_CONTENT_SNIPPET_CHARS + 25)
    snippet = raw_content_snippet(blob)
    assert snippet == blob[:RAW_CONTENT_SNIPPET_CHARS]
    assert raw_content_snippet(None) is None
    assert raw_content_snippet("") == ""
