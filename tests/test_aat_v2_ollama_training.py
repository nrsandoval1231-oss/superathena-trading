"""Offline local Ollama TRAINING runner: mocked transport, no DeepSeek, no live GPU."""
import importlib.util
import json
from pathlib import Path

import pytest

from athena_trading.aat_v2.ollama_identity import CLI_AUTHORIZATION_FLAG, declared_ollama_qwen_identity
from athena_trading.aat_v2.ollama_training import (
    DEFAULT_SMOKE_LIMIT,
    FROZEN_PLANNED_CALLS,
    IN_SAMPLE_STATUS,
    SMOKE_STATUS,
    OllamaTrainingError,
    fixture_transport,
    run_ollama_local_training,
)
from athena_trading.aat_v2.ollama_transport import (
    USAGE_ESTIMATED,
    USAGE_REPORTED,
    OllamaTransportError,
    build_ollama_payload,
    loopback_chat_url,
    read_usage,
)
from athena_trading.aat_v2.packet import build_packet
from athena_trading.exogenous import feature_keys


ROOT = Path(__file__).parents[1]
PLAN = ROOT / "configs/aat_v2_training_plan_v2.json"
PROTOCOL = ROOT / "configs/aat_v2_registered_protocol_v1.json"
ASSIGNMENT = ROOT / "configs/aat_v2_dataset_assignment_v1.json"
AMENDMENT = ROOT / "configs/aat_v2_e_arm_compact_schema_amendment_v1.json"
IDENTITY = ROOT / "configs/aat_v2_ollama_qwen_actor_identity_v1.json"
AUTHORIZATION = ROOT / "configs/aat_v2_ollama_local_training_authorization_v1.json"
INDEX = ROOT / "configs/fixtures/aat_v2_training_opportunities_smoke_v1.jsonl"
SNAPSHOT = ROOT / "configs/fixtures/aat_v2_training_snapshot_smoke_v1.jsonl"
FIXTURE = ROOT / "configs/fixtures/ollama_qwen_training_v1.json"
SCRIPT = ROOT / "scripts/run_aat_v2_ollama_local_training.py"
IDENTITY_HASH = declared_ollama_qwen_identity()["identity_hash"]


def _script():
    spec = importlib.util.spec_from_file_location("run_aat_v2_ollama_local_training", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _run(tmp_path, **kwargs):
    defaults = dict(
        training_plan_path=PLAN,
        protocol_path=PROTOCOL,
        assignment_path=ASSIGNMENT,
        opportunity_index_path=INDEX,
        snapshot_path=SNAPSHOT,
        amendment_path=AMENDMENT,
        identity_path=IDENTITY,
        authorization_path=AUTHORIZATION,
        output_dir=tmp_path / "run",
        limit_opportunities=DEFAULT_SMOKE_LIMIT,
        authorize_local_training=False,
        allow_live=False,
        transport=fixture_transport(FIXTURE),
        include_deliberation=True,
    )
    defaults.update(kwargs)
    return run_ollama_local_training(**defaults)


def test_smoke_defaults_are_tiny_mocked_and_absent_authority(tmp_path):
    result = _run(tmp_path)
    assert result["status"] == SMOKE_STATUS
    assert result["dry_run"] is True
    assert result["live_calls"] is False
    assert result["execution_authorized"] is False
    assert result["claim_authorized"] is False
    assert result["execution_authority"] == "ABSENT"
    assert result["sealed_holdout_consumed"] is False
    assert result["registration_status"] == "REGISTERED_NOT_AUTHORIZED"
    assert result["terra_protocol_not_reused"] is True
    assert result["deepseek_identity_not_reused"] is True
    assert result["authorize_local_training"] is False
    assert result["full_plan"] is False
    assert result["opportunity_count"] == 1
    assert result["request_count"] == 7
    assert result["accepted_count"] == 7
    assert result["rejected_count"] == 0
    assert result["actor_identity_hash"] == IDENTITY_HASH
    assert result["frozen_plan_calls"] == FROZEN_PLANNED_CALLS == 116935
    assert result["candidate_model_id"] == "qwen3.5:9b"
    assert result["v2_lessons_bound"] is False
    assert all(row["usage_source"] == USAGE_REPORTED for row in result["records"])
    assert all(row["execution_authority"] == "ABSENT" for row in result["records"])
    assert all(row["partition"] == "TRAINING" for row in result["records"])
    e_turns = [row["turn"] for row in result["records"] if row["arm"] == "E_DELIBERATION"]
    assert e_turns == ["BULL", "BEAR", "TRADER", "RISK"]
    assert (tmp_path / "run" / "ledger.jsonl").is_file()
    assert (tmp_path / "run" / "checkpoint.json").is_file()
    assert (tmp_path / "run" / "receipt.json").is_file()


def test_authorized_warmup_is_in_sample_not_a_terra_flip(tmp_path):
    result = _run(tmp_path, authorize_local_training=True, limit_opportunities=2)
    assert result["status"] == IN_SAMPLE_STATUS
    assert result["authorize_local_training"] is True
    assert result["full_plan"] is False
    assert result["opportunity_count"] == 2
    assert result["request_count"] == 14
    assert result["execution_authorized"] is False
    assert result["execution_authority"] == "ABSENT"
    assert result["registration_status"] == "REGISTERED_NOT_AUTHORIZED"
    symbols = {row["symbol"] for row in result["records"]}
    assert symbols == {"AAPL", "MSFT"}


def test_full_plan_without_the_cli_flag_is_refused(tmp_path):
    with pytest.raises(OllamaTrainingError, match=CLI_AUTHORIZATION_FLAG):
        _run(tmp_path, limit_opportunities=None, authorize_local_training=False)


def test_full_plan_with_flag_still_requires_the_frozen_16705_index(tmp_path):
    with pytest.raises(OllamaTrainingError, match="16,705"):
        _run(tmp_path, limit_opportunities=None, authorize_local_training=True)


def test_holdout_symbols_are_refused(tmp_path):
    row = json.loads(INDEX.read_text(encoding="utf-8").splitlines()[0])
    row["symbol"] = "TSLA"
    row["opportunity_id"] = "should-not-run-holdout"
    path = tmp_path / "mixed.jsonl"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(OllamaTrainingError, match="holdout"):
        _run(tmp_path, opportunity_index_path=path)


def test_holdout_paths_are_forbidden(tmp_path):
    bad = tmp_path / "sealed_holdout.jsonl"
    bad.write_text("{}\n", encoding="utf-8")
    with pytest.raises(OllamaTrainingError, match="holdout"):
        _run(tmp_path, opportunity_index_path=bad)


def test_resume_continues_from_the_ledger_after_a_transport_fault(tmp_path):
    fixture = fixture_transport(FIXTURE)
    seen = {"n": 0}

    def boom(payload):
        seen["n"] += 1
        if seen["n"] == 4:
            raise OllamaTransportError("simulated GPU hitch")
        return fixture(payload)

    with pytest.raises(OllamaTrainingError, match="GPU hitch"):
        _run(tmp_path, transport=boom)
    ledger = (tmp_path / "run" / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(ledger) == 3
    result = _run(tmp_path, resume=True, transport=fixture)
    assert result["request_count"] == 7
    assert result["accepted_count"] == 7
    assert result["status"] == SMOKE_STATUS
    sequences = [row["sequence"] for row in result["records"]]
    assert sequences == [1, 2, 3, 4, 5, 6, 7]


def test_payload_disables_thinking_and_keeps_compact_e_budget():
    packet = build_packet(
        arm="D_ATHENA",
        opportunity_id="op-1",
        features={"opaque": 1},
        actor_identity=IDENTITY_HASH,
        exogenous_features={key: 0 for key in feature_keys()},
    )
    actor = build_ollama_payload(packet, max_output_tokens=256)
    assert actor["think"] is False
    assert actor["stream"] is False
    assert actor["format"] == "json"
    assert actor["model"] == "qwen3.5:9b"
    assert actor["options"]["num_predict"] == 256
    compact = build_ollama_payload(packet, max_output_tokens=64, arm="E_DELIBERATION", turn="RISK")
    assert compact["options"]["num_predict"] == 64
    assert "EXAMPLE json OUTPUT" in compact["messages"][0]["content"]


def test_missing_ollama_usage_is_labeled_as_a_byte_proxy_estimate():
    prompt, completion, source = read_usage(
        {"message": {"content": '{"action":"PASS"}'}},
        payload={"model": "qwen3.5:9b"},
        content='{"action":"PASS"}',
    )
    assert source == USAGE_ESTIMATED
    assert prompt >= 1
    assert completion >= 1


def test_loopback_transport_refuses_non_local_hosts():
    with pytest.raises(OllamaTransportError, match="loopback"):
        loopback_chat_url("http://8.8.8.8:11434")
    with pytest.raises(OllamaTransportError, match="HTTP only"):
        loopback_chat_url("https://127.0.0.1:11434")
    assert loopback_chat_url() == "http://127.0.0.1:11434/api/chat"


def test_live_flag_without_injected_transport_still_does_not_run_in_tests(tmp_path):
    with pytest.raises(OllamaTrainingError, match="mixed"):
        _run(tmp_path, allow_live=True, transport=fixture_transport(FIXTURE))


def test_cli_smoke_prints_ok_and_does_not_call_deepseek(tmp_path, capsys):
    module = _script()
    code = module.main([
        "--output-dir", str(tmp_path / "cli"),
        "--limit-opportunities", "1",
    ])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["status"] == SMOKE_STATUS
    assert payload["live_calls"] is False
    assert payload["execution_authority"] == "ABSENT"
    assert "DEEPSEEK" not in json.dumps(payload)


def test_cli_authorized_full_run_refuses_the_smoke_index(tmp_path, capsys):
    module = _script()
    code = module.main([
        "--output-dir", str(tmp_path / "cli"),
        "--authorize-local-training",
    ])
    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "16,705" in payload["error"]
    assert payload["execution_authority"] == "ABSENT"
    assert payload["registration_status"] == "REGISTERED_NOT_AUTHORIZED"
