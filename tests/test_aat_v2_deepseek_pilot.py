import importlib.util
import json
from pathlib import Path

import pytest

from athena_trading.aat_v1.providers import registered_providers
from athena_trading.aat_v2.deepseek_pilot import (
    CALLS_PER_OPPORTUNITY_WITH_E,
    DEFAULT_PILOT_CALL_CEILING,
    DEFAULT_PILOT_OPPORTUNITIES,
    DEFAULT_PILOT_SPEND_CEILING_USD,
    PILOT_CALL_CEILING,
    PILOT_OPPORTUNITY_CEILING,
    PILOT_SPEND_CEILING_USD,
    PILOT_STATUS,
    RECOMMENDED_LIVE_CALL_CEILING,
    RECOMMENDED_LIVE_OPPORTUNITIES,
    RECOMMENDED_LIVE_SPEND_CEILING_USD,
    DeepSeekPilotError,
    run_deepseek_flash_pilot,
)
from athena_trading.aat_v2.deepseek_preflight import (
    RESPONSE_FORMAT,
    SINGLE_CALL_OUTPUT_TOKENS,
    THINKING,
    MissingDeepSeekCredentialsError,
    _live_transport,
)
from athena_trading.aat_v2.deliberation import (
    DELIBERATION_OUTPUT_TOKENS,
    DELIBERATION_PROMPT,
    DELIBERATION_TURN_ROLES,
    turn_system_prompt,
)
from athena_trading.aat_v2.identity import PILOT_PROMPT, declared_deepseek_flash_identity


ROOT = Path(__file__).parents[1]
PRICING = ROOT / "configs/deepseek_flash_pricing_2026-09-14.json"
PROTOCOL = ROOT / "configs/aat_v2_registered_protocol_v1.json"
AMENDMENT = ROOT / "configs/aat_v2_e_arm_compact_schema_amendment_v1.json"
IDENTITY = ROOT / "configs/aat_v2_deepseek_flash_actor_identity_v1.json"
FIXTURE = ROOT / "configs/fixtures/deepseek_flash_preflight_v1.json"
MISMATCH = ROOT / "configs/fixtures/deepseek_flash_e_arm_mismatch_v1.json"
SCRIPT = ROOT / "scripts/run_aat_v2_deepseek_flash_pilot.py"
FIXTURE_KEY = "fixture-key-not-serialized"
IDENTITY_HASH = declared_deepseek_flash_identity()["identity_hash"]


def _script():
    spec = importlib.util.spec_from_file_location("run_aat_v2_deepseek_flash_pilot", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _fixture_transport(payload, key):
    from athena_trading.aat_v2 import deepseek_preflight as deepseek_mod

    assert key == FIXTURE_KEY
    assert payload["model"] == "deepseek-flash"
    assert payload["thinking"] == THINKING
    assert payload["response_format"] == RESPONSE_FORMAT
    return deepseek_mod.fixture_transport(FIXTURE)(payload, key)


def test_fixture_pilot_accepts_compact_e_and_actor_json():
    seen = []

    def transport(payload, key):
        seen.append(payload)
        return _fixture_transport(payload, key)

    result = run_deepseek_flash_pilot(
        fixture_path=FIXTURE, pricing_path=PRICING, protocol_path=PROTOCOL,
        identity_path=IDENTITY, amendment_path=AMENDMENT,
        opportunity_count=1, call_ceiling=7, spend_ceiling_usd=1.00,
        api_key=FIXTURE_KEY, transport=transport, include_deliberation=True,
    )
    assert result["status"] == PILOT_STATUS == "PILOT_NOT_TRAINING"
    assert result["execution_authority"] == "ABSENT"
    assert result["execution_authorized"] is False
    assert result["claim_authorized"] is False
    assert result["sealed_holdout_consumed"] is False
    assert result["live_calls"] is False
    assert result["dry_run"] is True
    assert result["terra_protocol_not_reused"] is True
    assert result["pilot_is_not_training"] is True
    assert result["actor_identity_status"] == "CANDIDATE_PILOT"
    assert result["actor_identity_hash"] == IDENTITY_HASH
    assert result["request_count"] == 7
    assert result["accepted_count"] == 7
    assert result["rejected_count"] == 0
    assert result["opportunity_count"] == 1
    assert [payload["max_tokens"] for payload in seen] == [512, 512, 512, 64, 64, 64, 64]
    assert all(payload["thinking"] == THINKING for payload in seen)
    actor_payloads = seen[:3]
    e_payloads = seen[3:]
    assert all(payload["messages"][0]["content"] == PILOT_PROMPT for payload in actor_payloads)
    assert all(
        payload["messages"][0]["content"] == turn_system_prompt(role)
        for payload, role in zip(e_payloads, DELIBERATION_TURN_ROLES, strict=True)
    )
    assert all(payload["messages"][0]["content"].startswith(DELIBERATION_PROMPT) for payload in e_payloads)
    assert all("EXAMPLE json OUTPUT" in payload["messages"][0]["content"] for payload in e_payloads)
    assert all(payload["response_format"] == {"type": "json_object"} for payload in e_payloads)
    assert all(payload["response_format"].get("type") != "json_schema" for payload in seen)
    assert "PILOT_NOT_TRAINING" in PILOT_PROMPT
    e_rows = [row for row in result["records"] if row["arm"] == "E_DELIBERATION"]
    actor_rows = [row for row in result["records"] if row["arm"] != "E_DELIBERATION"]
    assert [row["turn"] for row in e_rows] == ["BULL", "BEAR", "TRADER", "RISK"]
    assert all(row["accepted"] for row in e_rows)
    assert all(set(row["decision"]) == {
        "action", "confidence", "horizon", "invalidation", "rationale",
    } for row in actor_rows)
    assert e_rows[-1]["decision"]["action"] == "PASS"
    assert [row["prior_turn_count"] for row in e_rows] == [0, 1, 2, 3]
    assert all(row["raw_content_snippet"] is None for row in result["records"])
    risk_user = json.loads(e_payloads[-1]["messages"][1]["content"])
    assert [item["turn"] for item in risk_user["prior_turns"]] == ["BULL", "BEAR", "TRADER"]
    bull_user = json.loads(e_payloads[0]["messages"][1]["content"])
    assert "prior_turns" not in bull_user
    assert bull_user["example_json"]["turn"] == "BULL"
    assert "EXAMPLE json OUTPUT" in e_payloads[0]["messages"][0]["content"]
    assert all(row["actor_identity_hash"] == IDENTITY_HASH for row in result["records"])
    assert FIXTURE_KEY not in json.dumps(result)
    assert SINGLE_CALL_OUTPUT_TOKENS == 512
    assert DELIBERATION_OUTPUT_TOKENS == 64


def test_two_opportunity_fixture_pilot_stays_absent():
    result = run_deepseek_flash_pilot(
        fixture_path=FIXTURE, pricing_path=PRICING, protocol_path=PROTOCOL,
        identity_path=IDENTITY, amendment_path=AMENDMENT,
        opportunity_count=2, call_ceiling=14, spend_ceiling_usd=1.00,
        api_key=FIXTURE_KEY, transport=_fixture_transport, include_deliberation=True,
    )
    assert result["opportunity_count"] == 2
    assert result["request_count"] == 14
    assert result["accepted_count"] == 14
    assert result["status"] == "PILOT_NOT_TRAINING"
    assert result["execution_authority"] == "ABSENT"
    ids = {row["opportunity_id"] for row in result["records"]}
    assert ids == {"preflight-fixture-1-1", "preflight-fixture-1-2"}


def test_pilot_without_allow_live_never_opens_a_network_transport():
    with pytest.raises(DeepSeekPilotError, match="not authorized"):
        run_deepseek_flash_pilot(
            fixture_path=FIXTURE, pricing_path=PRICING, protocol_path=PROTOCOL,
            identity_path=IDENTITY, amendment_path=AMENDMENT,
            opportunity_count=1, call_ceiling=7, spend_ceiling_usd=1.00,
            api_key=FIXTURE_KEY,
        )


def test_injected_live_transport_still_requires_allow_live():
    with pytest.raises(DeepSeekPilotError, match="not authorized"):
        run_deepseek_flash_pilot(
            fixture_path=FIXTURE, pricing_path=PRICING, protocol_path=PROTOCOL,
            identity_path=IDENTITY, amendment_path=AMENDMENT,
            opportunity_count=1, call_ceiling=7, spend_ceiling_usd=1.00,
            api_key=FIXTURE_KEY, transport=_live_transport,
        )


def test_allow_live_without_a_key_fails_closed(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(MissingDeepSeekCredentialsError, match="DEEPSEEK_API_KEY"):
        run_deepseek_flash_pilot(
            fixture_path=FIXTURE, pricing_path=PRICING, protocol_path=PROTOCOL,
            identity_path=IDENTITY, amendment_path=AMENDMENT,
            opportunity_count=1, call_ceiling=7, spend_ceiling_usd=1.00,
            allow_live=True,
        )


def test_missing_api_key_fails_closed_before_pilot(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    called = False

    def transport(payload, key):
        nonlocal called
        called = True
        return _fixture_transport(payload, key)

    with pytest.raises(MissingDeepSeekCredentialsError, match="DEEPSEEK_API_KEY"):
        run_deepseek_flash_pilot(
            fixture_path=FIXTURE, pricing_path=PRICING, protocol_path=PROTOCOL,
            identity_path=IDENTITY, amendment_path=AMENDMENT,
            opportunity_count=1, call_ceiling=7, spend_ceiling_usd=1.00,
            transport=transport,
        )
    assert called is False


def test_pilot_refuses_training_sized_ceilings():
    with pytest.raises(DeepSeekPilotError, match="call ceiling"):
        run_deepseek_flash_pilot(
            fixture_path=FIXTURE, pricing_path=PRICING, protocol_path=PROTOCOL,
            identity_path=IDENTITY, amendment_path=AMENDMENT,
            opportunity_count=1,             call_ceiling=116935, spend_ceiling_usd=1.00,
            api_key=FIXTURE_KEY, transport=_fixture_transport,
        )
    with pytest.raises(DeepSeekPilotError, match="call ceiling"):
        run_deepseek_flash_pilot(
            fixture_path=FIXTURE, pricing_path=PRICING, protocol_path=PROTOCOL,
            identity_path=IDENTITY, amendment_path=AMENDMENT,
            opportunity_count=1, call_ceiling=501, spend_ceiling_usd=50.00,
            api_key=FIXTURE_KEY, transport=_fixture_transport,
        )
    with pytest.raises(DeepSeekPilotError, match="spend ceiling"):
        run_deepseek_flash_pilot(
            fixture_path=FIXTURE, pricing_path=PRICING, protocol_path=PROTOCOL,
            identity_path=IDENTITY, amendment_path=AMENDMENT,
            opportunity_count=1, call_ceiling=7, spend_ceiling_usd=50.01,
            api_key=FIXTURE_KEY, transport=_fixture_transport,
        )
    with pytest.raises(DeepSeekPilotError, match="opportunity count"):
        run_deepseek_flash_pilot(
            fixture_path=FIXTURE, pricing_path=PRICING, protocol_path=PROTOCOL,
            identity_path=IDENTITY, amendment_path=AMENDMENT,
            opportunity_count=81, call_ceiling=7, spend_ceiling_usd=1.00,
            api_key=FIXTURE_KEY, transport=_fixture_transport,
        )
    with pytest.raises(DeepSeekPilotError, match="opportunity count"):
        run_deepseek_flash_pilot(
            fixture_path=FIXTURE, pricing_path=PRICING, protocol_path=PROTOCOL,
            identity_path=IDENTITY, amendment_path=AMENDMENT,
            opportunity_count=16705, call_ceiling=7, spend_ceiling_usd=1.00,
            api_key=FIXTURE_KEY, transport=_fixture_transport,
        )


def test_pilot_refuses_a_call_ceiling_below_the_arm_sequence():
    with pytest.raises(DeepSeekPilotError, match="call ceiling"):
        run_deepseek_flash_pilot(
            fixture_path=FIXTURE, pricing_path=PRICING, protocol_path=PROTOCOL,
            identity_path=IDENTITY, amendment_path=AMENDMENT,
            opportunity_count=2, call_ceiling=7, spend_ceiling_usd=1.00,
            api_key=FIXTURE_KEY, transport=_fixture_transport,
        )


def test_e_arm_pilot_requires_the_non_authorizing_amendment():
    with pytest.raises(DeepSeekPilotError, match="compact-schema amendment"):
        run_deepseek_flash_pilot(
            fixture_path=FIXTURE, pricing_path=PRICING, protocol_path=PROTOCOL,
            identity_path=IDENTITY, amendment_path=None,
            opportunity_count=1, call_ceiling=7, spend_ceiling_usd=1.00,
            api_key=FIXTURE_KEY, transport=_fixture_transport,
            include_deliberation=True,
        )


def test_holdout_fixture_paths_are_forbidden(tmp_path):
    bad = tmp_path / "sealed_holdout.json"
    bad.write_text("{}", encoding="utf-8")
    with pytest.raises(DeepSeekPilotError, match="holdout"):
        run_deepseek_flash_pilot(
            fixture_path=bad, pricing_path=PRICING, protocol_path=PROTOCOL,
            identity_path=IDENTITY, amendment_path=AMENDMENT,
            opportunity_count=1, call_ceiling=7, spend_ceiling_usd=1.00,
            api_key=FIXTURE_KEY, transport=_fixture_transport,
        )


def test_recommended_knobs_stay_inside_hard_caps():
    assert DEFAULT_PILOT_OPPORTUNITIES == 1
    assert DEFAULT_PILOT_CALL_CEILING == 7
    assert DEFAULT_PILOT_SPEND_CEILING_USD == 1.00
    assert CALLS_PER_OPPORTUNITY_WITH_E == 7
    assert RECOMMENDED_LIVE_OPPORTUNITIES == 71
    assert RECOMMENDED_LIVE_CALL_CEILING == 500
    assert RECOMMENDED_LIVE_SPEND_CEILING_USD == 50.00
    # Bigger live pilot: 71 opportunities × (B/C/D + four E) = 497 calls.
    assert RECOMMENDED_LIVE_OPPORTUNITIES * CALLS_PER_OPPORTUNITY_WITH_E == 497
    assert 497 <= RECOMMENDED_LIVE_CALL_CEILING
    assert RECOMMENDED_LIVE_OPPORTUNITIES <= PILOT_OPPORTUNITY_CEILING == 80
    assert RECOMMENDED_LIVE_CALL_CEILING <= PILOT_CALL_CEILING == 500
    assert RECOMMENDED_LIVE_SPEND_CEILING_USD <= PILOT_SPEND_CEILING_USD == 50.00
    assert registered_providers() == ("openai",)


def test_bigger_pilot_opportunity_cap_still_binds_before_call_count():
    """80 opportunities × 7 calls = 560, above the 500-call hard cap."""
    with pytest.raises(DeepSeekPilotError, match="call ceiling"):
        run_deepseek_flash_pilot(
            fixture_path=FIXTURE, pricing_path=PRICING, protocol_path=PROTOCOL,
            identity_path=IDENTITY, amendment_path=AMENDMENT,
            opportunity_count=80, call_ceiling=500, spend_ceiling_usd=50.00,
            api_key=FIXTURE_KEY, transport=_fixture_transport,
        )


def test_recommended_71_opportunities_are_legal_at_the_hard_caps():
    """71 is inside the opportunity cap; 71 × 7 = 497 needs the 500-call ceiling."""
    with pytest.raises(DeepSeekPilotError, match="pilot arm sequence exceeds call ceiling"):
        run_deepseek_flash_pilot(
            fixture_path=FIXTURE, pricing_path=PRICING, protocol_path=PROTOCOL,
            identity_path=IDENTITY, amendment_path=AMENDMENT,
            opportunity_count=71, call_ceiling=496, spend_ceiling_usd=50.00,
            api_key=FIXTURE_KEY, transport=_fixture_transport,
        )


def test_cli_default_is_fixture_dry(monkeypatch, capsys):
    monkeypatch.setenv("DEEPSEEK_API_KEY", FIXTURE_KEY)
    code = _script().main([])
    assert code == 0
    captured = capsys.readouterr().out
    payload = json.loads(captured)
    assert payload["ok"] is True
    assert payload["status"] == "PILOT_NOT_TRAINING"
    assert payload["live_calls"] is False
    assert payload["dry_run"] is True
    assert payload["execution_authority"] == "ABSENT"
    assert payload["request_count"] == 7
    assert payload["accepted_count"] == 7
    assert payload["actor_identity_hash"] == IDENTITY_HASH
    assert FIXTURE_KEY not in captured


def test_cli_fails_closed_without_key(monkeypatch, capsys):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    code = _script().main([])
    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "DEEPSEEK_API_KEY" in payload["error"]
    assert payload["execution_authority"] == "ABSENT"
    assert payload["sealed_holdout_consumed"] is False


def test_cli_allow_live_requires_explicit_ceilings(monkeypatch, capsys):
    monkeypatch.setenv("DEEPSEEK_API_KEY", FIXTURE_KEY)
    code = _script().main(["--allow-live"])
    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "explicit --call-ceiling" in payload["error"]
    assert payload["live_calls"] is False
    assert payload["execution_authority"] == "ABSENT"


def test_cli_allow_live_without_key_fails_closed(monkeypatch, capsys):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    code = _script().main([
        "--allow-live", "--call-ceiling", "7", "--spend-ceiling-usd", "1",
    ])
    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "DEEPSEEK_API_KEY" in payload["error"]
    assert payload["live_calls"] is False


def test_non_finite_spend_ceiling_fails_closed_before_transport():
    called = False

    def transport(payload, key):
        nonlocal called
        called = True
        return _fixture_transport(payload, key)

    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(DeepSeekPilotError, match="finite"):
            run_deepseek_flash_pilot(
                fixture_path=FIXTURE, pricing_path=PRICING, protocol_path=PROTOCOL,
                identity_path=IDENTITY, amendment_path=AMENDMENT,
                opportunity_count=1, call_ceiling=7, spend_ceiling_usd=value,
                api_key=FIXTURE_KEY, transport=transport,
            )
    assert called is False


def test_mid_run_failure_preserves_completed_and_attempted_calls():
    from athena_trading.aat_v2.deepseek_preflight import DeepSeekPreflightError

    seen = {"n": 0}

    def transport(payload, key):
        seen["n"] += 1
        if seen["n"] > 2:
            raise DeepSeekPreflightError("DeepSeek preflight failed closed with HTTP 500")
        return _fixture_transport(payload, key)

    with pytest.raises(DeepSeekPilotError, match="HTTP 500") as err:
        run_deepseek_flash_pilot(
            fixture_path=FIXTURE, pricing_path=PRICING, protocol_path=PROTOCOL,
            identity_path=IDENTITY, amendment_path=AMENDMENT,
            opportunity_count=1, call_ceiling=7, spend_ceiling_usd=1.00,
            api_key=FIXTURE_KEY, transport=transport,
        )
    assert err.value.completed_calls == 2
    assert err.value.attempted_calls == 3
    assert err.value.live_calls is False
    assert err.value.allow_live is False


def test_cli_reports_live_attempt_evidence_on_failure(monkeypatch, capsys):
    monkeypatch.setenv("DEEPSEEK_API_KEY", FIXTURE_KEY)
    mod = _script()

    def boom(**kwargs):
        raise DeepSeekPilotError(
            "DeepSeek preflight failed closed with HTTP 500",
            live_calls=True,
            allow_live=True,
            completed_calls=2,
            attempted_calls=3,
        )

    monkeypatch.setattr(mod, "run_deepseek_flash_pilot", boom)
    code = mod.main(["--allow-live", "--call-ceiling", "7", "--spend-ceiling-usd", "1"])
    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["live_calls"] is True
    assert payload["allow_live"] is True
    assert payload["completed_calls"] == 2
    assert payload["attempted_calls"] == 3
    assert payload["execution_authority"] == "ABSENT"
    assert payload["sealed_holdout_consumed"] is False


def _chat_reply(content, *, finish_reason="stop", completion_tokens=24):
    return {
        "id": "chatcmpl-fixture-mismatch",
        "model": "deepseek-flash",
        "object": "chat.completion",
        "choices": [{
            "finish_reason": finish_reason,
            "index": 0,
            "message": {"content": content, "role": "assistant"},
        }],
        "usage": {
            "completion_tokens": completion_tokens,
            "prompt_tokens": 80,
            "total_tokens": 80 + completion_tokens,
        },
    }


def test_pilot_replays_flash_mismatch_fixtures_and_stores_snippets():
    cases = json.loads(MISMATCH.read_text(encoding="utf-8"))["cases"]
    by_turn = {
        "BULL": cases["extra_keys"],
        "BEAR": cases["missing_claim"],
        "TRADER": cases["wrong_turn_string"],
        "RISK": cases["truncated_json"],
    }

    def transport(payload, key):
        user = json.loads(payload["messages"][1]["content"])
        turn = user.get("turn") if isinstance(user, dict) else None
        if turn in by_turn:
            case = by_turn[turn]
            return _chat_reply(
                case["content"],
                finish_reason=case.get("finish_reason", "stop"),
                completion_tokens=20,
            )
        return _fixture_transport(payload, key)

    result = run_deepseek_flash_pilot(
        fixture_path=FIXTURE, pricing_path=PRICING, protocol_path=PROTOCOL,
        identity_path=IDENTITY, amendment_path=AMENDMENT,
        opportunity_count=1, call_ceiling=7, spend_ceiling_usd=1.00,
        api_key=FIXTURE_KEY, transport=transport, include_deliberation=True,
    )
    assert result["status"] == "PILOT_NOT_TRAINING"
    assert result["execution_authority"] == "ABSENT"
    assert result["sealed_holdout_consumed"] is False
    actor_rows = [row for row in result["records"] if row["arm"] != "E_DELIBERATION"]
    e_rows = [row for row in result["records"] if row["arm"] == "E_DELIBERATION"]
    assert all(row["accepted"] for row in actor_rows)
    assert all(row["raw_content_snippet"] is None for row in actor_rows)
    assert [row["turn"] for row in e_rows] == ["BULL", "BEAR", "TRADER", "RISK"]
    assert all(row["accepted"] is False for row in e_rows)
    assert [row["rejection_reason"] for row in e_rows] == [
        "deliberation output schema mismatch",
        "deliberation output schema mismatch",
        "deliberation output schema mismatch",
        "OUTPUT_TRUNCATED",
    ]
    for row in e_rows:
        expected = by_turn[row["turn"]]["content"]
        assert row["raw_content_snippet"] == expected
        assert row["decision"] is None
        assert row["output_tokens"] == 20
        assert row["execution_authority"] == "ABSENT"


def test_pilot_stores_actor_shaped_e_payload_snippet():
    actor = json.loads(MISMATCH.read_text(encoding="utf-8"))["cases"]["actor_shaped_payload"]

    def transport(payload, key):
        user = json.loads(payload["messages"][1]["content"])
        if isinstance(user, dict) and user.get("turn") == "RISK":
            return _chat_reply(actor["content"], completion_tokens=32)
        return _fixture_transport(payload, key)

    result = run_deepseek_flash_pilot(
        fixture_path=FIXTURE, pricing_path=PRICING, protocol_path=PROTOCOL,
        identity_path=IDENTITY, amendment_path=AMENDMENT,
        opportunity_count=1, call_ceiling=7, spend_ceiling_usd=1.00,
        api_key=FIXTURE_KEY, transport=transport, include_deliberation=True,
    )
    risk = [row for row in result["records"] if row["turn"] == "RISK"][0]
    assert risk["accepted"] is False
    assert risk["rejection_reason"] == "deliberation output schema mismatch"
    assert risk["raw_content_snippet"] == actor["content"]
    assert "horizon" in risk["raw_content_snippet"]
    assert result["execution_authority"] == "ABSENT"
