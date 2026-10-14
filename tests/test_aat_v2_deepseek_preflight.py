import importlib.util
import json
from pathlib import Path

import pytest

from athena_trading.athena_adapter.contracts import canonical_hash
from athena_trading.aat_v1.providers import registered_providers
from athena_trading.aat_v2.deepseek_preflight import (
    ACTOR_DECISION_KEYS,
    LEGAL_ACTIONS,
    MODEL_ID,
    PREFLIGHT_CALL_CEILING,
    PREFLIGHT_PROMPT,
    PREFLIGHT_SPEND_CEILING_USD,
    RESPONSE_FORMAT,
    SINGLE_CALL_OUTPUT_TOKENS,
    THINKING,
    DeepSeekPreflightError,
    MissingDeepSeekCredentialsError,
    api_key_from_env,
    build_deepseek_payload,
    forbid_output_path,
    load_macro_only_training_plan,
    plan_deepseek_flash_dry_run,
    run_deepseek_flash_preflight,
)
from athena_trading.aat_v2.deliberation import DELIBERATION_TURN_ROLES, turn_system_prompt
from athena_trading.aat_v2 import deepseek_preflight as deepseek_mod


ROOT = Path(__file__).parents[1]
PLAN = ROOT / "configs/aat_v2_training_plan_v2.json"
PRICING = ROOT / "configs/deepseek_flash_pricing_2026-09-14.json"
PROTOCOL = ROOT / "configs/aat_v2_registered_protocol_v1.json"
AMENDMENT = ROOT / "configs/aat_v2_e_arm_compact_schema_amendment_v1.json"
FIXTURE = ROOT / "configs/fixtures/deepseek_flash_preflight_v1.json"
SCRIPT = ROOT / "scripts/plan_aat_v2_deepseek_flash.py"
FIXTURE_KEY = "fixture-key-not-serialized"


def _script():
    spec = importlib.util.spec_from_file_location("plan_aat_v2_deepseek_flash", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _plan():
    return plan_deepseek_flash_dry_run(
        training_plan_path=PLAN, pricing_path=PRICING, protocol_path=PROTOCOL,
    )


def _fixture_transport(payload, key):
    assert key == FIXTURE_KEY
    assert payload["model"] == MODEL_ID
    assert payload["stream"] is False
    assert payload["thinking"] == THINKING
    assert payload["response_format"] == RESPONSE_FORMAT
    return deepseek_mod.fixture_transport(FIXTURE)(payload, key)


def test_dry_run_matches_the_documented_deepseek_estimate():
    plan = _plan()
    assert plan["status"] == "DRY_RUN_NOT_TRAINING"
    assert plan["dry_run"] is True
    assert plan["execution_authorized"] is False
    assert plan["claim_authorized"] is False
    assert plan["sealed_holdout_consumed"] is False
    assert plan["execution_authority"] == "ABSENT"
    assert plan["live_calls"] is False
    assert plan["actor_called"] is False
    assert plan["terra_protocol_not_reused"] is True
    assert plan["actor_identity_status"] == "CANDIDATE_PILOT"
    assert plan["pilot_is_not_training"] is True
    assert plan["declared_identity_hash"] == (
        "ee1133be82fd4a1bc20a03adb00685187a5a44aa10957312eaa6991eb42b33cd"
    )
    assert plan["planned_calls"] == 116935
    assert round(plan["off_peak_cost_usd"], 2) == 32.68
    assert round(plan["peak_cost_usd"], 2) == 65.35
    assert plan["worst_case_cost_usd"] == plan["peak_cost_usd"]
    assert plan["source_document"] == "docs/AAT_V2_MODEL_EXECUTION_OPTIONS.md"


def test_dry_run_does_not_require_a_deepseek_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    plan = _plan()
    assert plan["execution_authority"] == "ABSENT"


def test_superseded_v1_plan_is_refused():
    with pytest.raises(DeepSeekPreflightError, match="corrected v2"):
        load_macro_only_training_plan(ROOT / "configs/aat_v2_training_plan_v1.json")


def test_tampered_training_plan_hash_is_refused(tmp_path):
    payload = json.loads(PLAN.read_text(encoding="utf-8"))
    payload["output_token_ceiling"] = 1
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DeepSeekPreflightError, match="plan_hash"):
        plan_deepseek_flash_dry_run(
            training_plan_path=path, pricing_path=PRICING, protocol_path=PROTOCOL,
        )


def test_non_absent_authority_is_refused(tmp_path):
    payload = json.loads(PLAN.read_text(encoding="utf-8"))
    payload["execution_authority"] = "PAPER"
    payload.pop("plan_hash")
    payload["plan_hash"] = canonical_hash(payload)
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DeepSeekPreflightError, match="ABSENT"):
        plan_deepseek_flash_dry_run(
            training_plan_path=path, pricing_path=PRICING, protocol_path=PROTOCOL,
        )


def test_deepseek_cannot_reuse_the_terra_protocol_identity(tmp_path):
    payload = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    payload["protocol"]["actor_identity"]["provider"] = "deepseek"
    payload["protocol"]["actor_identity"]["model_id"] = MODEL_ID
    body = dict(payload)
    body.pop("protocol_hash")
    payload["protocol_hash"] = canonical_hash(body)
    path = tmp_path / "protocol.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DeepSeekPreflightError, match="Terra"):
        plan_deepseek_flash_dry_run(
            training_plan_path=PLAN, pricing_path=PRICING, protocol_path=path,
        )


def test_missing_api_key_fails_closed_before_preflight(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(MissingDeepSeekCredentialsError, match="DEEPSEEK_API_KEY"):
        api_key_from_env()
    called = False

    def transport(payload, key):
        nonlocal called
        called = True
        return _fixture_transport(payload, key)

    with pytest.raises(MissingDeepSeekCredentialsError, match="DEEPSEEK_API_KEY"):
        run_deepseek_flash_preflight(
            fixture_path=FIXTURE, pricing_path=PRICING, protocol_path=PROTOCOL,
            call_ceiling=3, spend_ceiling_usd=0.05, transport=transport,
        )
    assert called is False


def test_fixture_preflight_stays_absent_and_does_not_consume_a_holdout():
    result = run_deepseek_flash_preflight(
        fixture_path=FIXTURE, pricing_path=PRICING, protocol_path=PROTOCOL,
        call_ceiling=3, spend_ceiling_usd=0.05, api_key=FIXTURE_KEY,
        transport=_fixture_transport,
    )
    assert result["status"] == "PREFLIGHT_NOT_TRAINING"
    assert result["request_count"] == 3
    assert result["accepted_count"] == 3
    assert result["execution_authority"] == "ABSENT"
    assert result["sealed_holdout_consumed"] is False
    assert result["execution_authorized"] is False
    assert result["live_calls"] is False
    assert result["terra_protocol_not_reused"] is True
    assert result["actor_identity_status"] == "CANDIDATE_PILOT"
    assert result["pilot_is_not_training"] is True
    assert {row["arm"] for row in result["records"]} == {
        "B_MEMORYLESS", "C_NAIVE_MEMORY", "D_ATHENA",
    }
    dumped = json.dumps(result)
    assert FIXTURE_KEY not in dumped
    assert all(row["execution_authority"] == "ABSENT" for row in result["records"])


def test_preflight_refuses_a_training_sized_call_ceiling():
    with pytest.raises(DeepSeekPreflightError, match="call ceiling"):
        run_deepseek_flash_preflight(
            fixture_path=FIXTURE, pricing_path=PRICING, protocol_path=PROTOCOL,
            call_ceiling=116935, spend_ceiling_usd=0.05, api_key=FIXTURE_KEY,
            transport=_fixture_transport,
        )


def test_preflight_refuses_spend_above_the_tiny_ceiling():
    with pytest.raises(DeepSeekPreflightError, match="spend ceiling"):
        run_deepseek_flash_preflight(
            fixture_path=FIXTURE, pricing_path=PRICING, protocol_path=PROTOCOL,
            call_ceiling=3, spend_ceiling_usd=1.01, api_key=FIXTURE_KEY,
            transport=_fixture_transport,
        )


def test_preflight_allows_the_authorized_one_dollar_ceiling():
    result = run_deepseek_flash_preflight(
        fixture_path=FIXTURE, pricing_path=PRICING, protocol_path=PROTOCOL,
        call_ceiling=3, spend_ceiling_usd=1.00, api_key=FIXTURE_KEY,
        transport=_fixture_transport,
    )
    assert result["status"] == "PREFLIGHT_NOT_TRAINING"
    assert result["execution_authority"] == "ABSENT"
    assert result["accepted_count"] == 3


def test_preflight_without_allow_live_never_opens_a_network_transport():
    with pytest.raises(DeepSeekPreflightError, match="not authorized"):
        run_deepseek_flash_preflight(
            fixture_path=FIXTURE, pricing_path=PRICING, protocol_path=PROTOCOL,
            call_ceiling=3, spend_ceiling_usd=0.05, api_key=FIXTURE_KEY,
        )


def test_injected_live_transport_still_requires_allow_live():
    with pytest.raises(DeepSeekPreflightError, match="not authorized"):
        run_deepseek_flash_preflight(
            fixture_path=FIXTURE, pricing_path=PRICING, protocol_path=PROTOCOL,
            call_ceiling=3, spend_ceiling_usd=0.05, api_key=FIXTURE_KEY,
            transport=deepseek_mod._live_transport,
        )


def test_allow_live_without_a_key_fails_closed(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(MissingDeepSeekCredentialsError, match="DEEPSEEK_API_KEY"):
        run_deepseek_flash_preflight(
            fixture_path=FIXTURE, pricing_path=PRICING, protocol_path=PROTOCOL,
            call_ceiling=3, spend_ceiling_usd=0.05, allow_live=True,
        )


def test_holdout_paths_are_forbidden(tmp_path):
    bad = tmp_path / "sealed_holdout.json"
    bad.write_text("{}", encoding="utf-8")
    with pytest.raises(DeepSeekPreflightError, match="holdout"):
        plan_deepseek_flash_dry_run(
            training_plan_path=bad, pricing_path=PRICING, protocol_path=PROTOCOL,
        )


def test_output_cannot_overwrite_the_consumed_holdout_registry(tmp_path):
    with pytest.raises(DeepSeekPreflightError, match="holdout"):
        forbid_output_path(ROOT / "configs/aat_consumed_holdouts_v1.json")
    with pytest.raises(DeepSeekPreflightError, match="registered or consumed"):
        forbid_output_path(ROOT / "configs/aat_v2_registered_protocol_v1.json")
    with pytest.raises(DeepSeekPreflightError, match="registered or consumed"):
        forbid_output_path(AMENDMENT)
    with pytest.raises(DeepSeekPreflightError, match="registered or consumed"):
        forbid_output_path(ROOT / "configs/aat_v2_deepseek_flash_actor_identity_v1.json")
    existing = tmp_path / "out.json"
    existing.write_text("{}\n", encoding="utf-8")
    with pytest.raises(DeepSeekPreflightError, match="overwrite"):
        forbid_output_path(existing)


def test_invalid_decisions_are_rejected_not_accepted():
    envelope = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cases = (
        ({"action": "NOPE", "confidence": 0.5, "horizon": "H", "invalidation": "I",
          "rationale": "R"}, "Actor action is not allowed"),
        ({"action": "PASS", "confidence": "high", "horizon": "H", "invalidation": "I",
          "rationale": "R"}, "Actor confidence is invalid"),
        ({"action": "PASS", "confidence": 1.5, "horizon": "H", "invalidation": "I",
          "rationale": "R"}, "Actor confidence is invalid"),
        ({"action": "PASS", "confidence": 0.5, "horizon": "", "invalidation": "I",
          "rationale": "R"}, "Actor text fields are invalid"),
        ({"type": "PASS", "reason": "opaque"}, "Actor output schema mismatch"),
    )

    for decision, reason in cases:
        response = json.loads(json.dumps(envelope["response"]))
        response["choices"][0]["message"]["content"] = json.dumps(decision)

        def transport(payload, key, *, _response=response):
            return _response

        result = run_deepseek_flash_preflight(
            fixture_path=FIXTURE, pricing_path=PRICING, protocol_path=PROTOCOL,
            call_ceiling=3, spend_ceiling_usd=0.05, api_key=FIXTURE_KEY,
            transport=transport,
        )
        assert result["accepted_count"] == 0
        assert result["rejected_count"] == 3
        assert result["records"][0]["rejection_reason"] == reason


def test_empty_content_is_rejected_as_non_json():
    envelope = json.loads(FIXTURE.read_text(encoding="utf-8"))
    response = json.loads(json.dumps(envelope["response"]))
    response["choices"][0]["finish_reason"] = "length"
    response["choices"][0]["message"]["content"] = ""

    def transport(payload, key):
        return response

    result = run_deepseek_flash_preflight(
        fixture_path=FIXTURE, pricing_path=PRICING, protocol_path=PROTOCOL,
        call_ceiling=3, spend_ceiling_usd=0.05, api_key=FIXTURE_KEY,
        transport=transport,
    )
    assert result["accepted_count"] == 0
    assert result["rejected_count"] == 3
    assert result["records"][0]["rejection_reason"] == "Actor output is not JSON"
    assert result["execution_authority"] == "ABSENT"


def test_preflight_payload_disables_thinking_and_pins_actor_schema():
    packet = {"schema_version": "athena-aat-v2-actor-packet-v1", "features": {"opaque": 1}}
    payload = build_deepseek_payload(packet, max_output_tokens=SINGLE_CALL_OUTPUT_TOKENS)
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["max_tokens"] == 512
    system = payload["messages"][0]["content"]
    assert system == PREFLIGHT_PROMPT
    for key in ACTOR_DECISION_KEYS:
        assert key in system
    for action in LEGAL_ACTIONS:
        assert action in system
    assert "markdown" in system
    assert "execution_authority" in system
    assert "PREFLIGHT" in system
    assert "TRAINING" in system


def test_deliberation_preflight_keeps_e_arm_budget_and_accepts_compact_json():
    seen = []

    def transport(payload, key):
        seen.append(payload)
        return _fixture_transport(payload, key)

    result = run_deepseek_flash_preflight(
        fixture_path=FIXTURE, pricing_path=PRICING, protocol_path=PROTOCOL,
        call_ceiling=7, spend_ceiling_usd=1.00, api_key=FIXTURE_KEY,
        transport=transport, include_deliberation=True, amendment_path=AMENDMENT,
    )
    assert result["request_count"] == 7
    assert result["accepted_count"] == 7
    assert result["rejected_count"] == 0
    assert result["execution_authority"] == "ABSENT"
    assert result["sealed_holdout_consumed"] is False
    assert result["execution_authorized"] is False
    assert [payload["max_tokens"] for payload in seen] == [512, 512, 512, 64, 64, 64, 64]
    assert all(payload["thinking"] == THINKING for payload in seen)
    assert all(payload["response_format"] == RESPONSE_FORMAT for payload in seen)
    e_rows = [row for row in result["records"] if row["arm"] == "E_DELIBERATION"]
    assert [row["turn"] for row in e_rows] == ["BULL", "BEAR", "TRADER", "RISK"]
    assert all(row["accepted"] for row in e_rows)
    assert e_rows[-1]["decision"]["action"] == "PASS"
    e_payloads = seen[3:]
    assert all(
        payload["messages"][0]["content"] == turn_system_prompt(role)
        for payload, role in zip(e_payloads, DELIBERATION_TURN_ROLES, strict=True)
    )
    assert all("EXAMPLE json OUTPUT" in payload["messages"][0]["content"] for payload in e_payloads)
    assert all('"turn":"' in payload["messages"][1]["content"] for payload in e_payloads)
    assert all(row["raw_content_snippet"] is None for row in result["records"])


def test_e_arm_preflight_requires_the_non_authorizing_amendment():
    with pytest.raises(DeepSeekPreflightError, match="compact-schema amendment"):
        run_deepseek_flash_preflight(
            fixture_path=FIXTURE, pricing_path=PRICING, protocol_path=PROTOCOL,
            call_ceiling=7, spend_ceiling_usd=1.00, api_key=FIXTURE_KEY,
            transport=_fixture_transport, include_deliberation=True,
        )


def test_truncated_actor_json_is_rejected_on_e_turns_compact_json_is_not():
    envelope = json.loads(FIXTURE.read_text(encoding="utf-8"))
    verbose = json.dumps({
        "action": "ENTER_STANDARD",
        "confidence": 0.62,
        "horizon": "hold through the session close at 15:45 ET",
        "invalidation": "a break of the opening-range low on a closing basis",
        "rationale": (
            "Overnight macro surprise supports continuation into the range "
            "and the packet does not justify high conviction sizing."
        ),
    }, separators=(",", ":"))
    truncated = verbose[:256]
    cut = json.loads(json.dumps(envelope["deliberation_responses"]["BULL"]))
    cut["choices"][0]["finish_reason"] = "length"
    cut["choices"][0]["message"]["content"] = truncated
    cut["usage"]["completion_tokens"] = 64

    def transport(payload, key):
        user = json.loads(payload["messages"][1]["content"])
        if isinstance(user, dict) and user.get("turn"):
            return cut
        return _fixture_transport(payload, key)

    result = run_deepseek_flash_preflight(
        fixture_path=FIXTURE, pricing_path=PRICING, protocol_path=PROTOCOL,
        call_ceiling=7, spend_ceiling_usd=1.00, api_key=FIXTURE_KEY,
        transport=transport, include_deliberation=True, amendment_path=AMENDMENT,
    )
    e_rows = [row for row in result["records"] if row["arm"] == "E_DELIBERATION"]
    actor_rows = [row for row in result["records"] if row["arm"] != "E_DELIBERATION"]
    assert all(row["accepted"] for row in actor_rows)
    assert all(row["rejection_reason"] == "OUTPUT_TRUNCATED" for row in e_rows)
    assert all(row["accepted"] is False for row in e_rows)
    assert all(row["raw_content_snippet"] for row in e_rows)
    assert all("horizon" in row["raw_content_snippet"] for row in e_rows)


def test_full_actor_schema_on_an_e_turn_is_a_schema_mismatch():
    envelope = json.loads(FIXTURE.read_text(encoding="utf-8"))
    actor = envelope["response"]

    def transport(payload, key):
        user = json.loads(payload["messages"][1]["content"])
        if isinstance(user, dict) and user.get("turn"):
            return actor
        return _fixture_transport(payload, key)

    result = run_deepseek_flash_preflight(
        fixture_path=FIXTURE, pricing_path=PRICING, protocol_path=PROTOCOL,
        call_ceiling=7, spend_ceiling_usd=1.00, api_key=FIXTURE_KEY,
        transport=transport, include_deliberation=True, amendment_path=AMENDMENT,
    )
    e_rows = [row for row in result["records"] if row["arm"] == "E_DELIBERATION"]
    assert all(row["rejection_reason"] == "deliberation output schema mismatch" for row in e_rows)
    assert all(row["raw_content_snippet"] for row in e_rows)
    assert all("rationale" in row["raw_content_snippet"] for row in e_rows)


def test_deepseek_is_not_registered_as_a_v1_provider():
    assert registered_providers() == ("openai",)
    from athena_trading.aat_v1.providers import DEEPSEEK, get_provider
    from athena_trading.aat_v1 import AATValidationError
    with pytest.raises(AATValidationError, match="unregistered"):
        get_provider(DEEPSEEK.provider)
    assert PREFLIGHT_CALL_CEILING == 7
    assert PREFLIGHT_SPEND_CEILING_USD == 1.00
    assert SINGLE_CALL_OUTPUT_TOKENS == 512
    assert THINKING == {"type": "disabled"}
    assert RESPONSE_FORMAT == {"type": "json_object"}
    assert ACTOR_DECISION_KEYS == (
        "action", "confidence", "horizon", "invalidation", "rationale",
    )


def test_documented_plan_only_command(capsys):
    code = _script().main([])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["execution_authority"] == "ABSENT"
    assert payload["live_calls"] is False


def test_documented_preflight_fails_closed_without_key(monkeypatch, capsys):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    code = _script().main(["--preflight"])
    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "DEEPSEEK_API_KEY" in payload["error"]
    assert payload["execution_authority"] == "ABSENT"
    assert payload["sealed_holdout_consumed"] is False


def test_documented_preflight_with_key_uses_the_fixture_not_the_network(
    monkeypatch, capsys,
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", FIXTURE_KEY)
    code = _script().main(["--preflight"])
    assert code == 0
    captured = capsys.readouterr().out
    payload = json.loads(captured)
    assert payload["ok"] is True
    assert payload["status"] == "PREFLIGHT_NOT_TRAINING"
    assert payload["live_calls"] is False
    assert payload["execution_authority"] == "ABSENT"
    assert payload["request_count"] == 3
    assert FIXTURE_KEY not in captured
