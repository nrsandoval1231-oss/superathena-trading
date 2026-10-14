"""Offline RunPod / remote-Ollama TRAINING path: mocked transport, no live GPU."""
import json
from pathlib import Path

import pytest

from athena_trading.aat_v2.ollama_identity import (
    RUNPOD_CLI_AUTHORIZATION_FLAG,
    declared_ollama_runpod_identity,
)
from athena_trading.aat_v2.ollama_training import (
    DEFAULT_SMOKE_LIMIT,
    IN_SAMPLE_STATUS,
    SMOKE_STATUS,
    OllamaTrainingError,
    fixture_transport,
    run_ollama_local_training,
)
from athena_trading.aat_v2.ollama_transport import (
    OLLAMA_USER_AGENT,
    OllamaTransportError,
    build_ollama_payload,
    live_ollama_transport,
    loopback_chat_url,
    ollama_chat_url,
    ollama_http_headers,
    transport_host_scope,
)
from athena_trading.aat_v2.packet import build_packet
from athena_trading.exogenous import feature_keys


ROOT = Path(__file__).parents[1]
PLAN = ROOT / "configs/aat_v2_training_plan_v2.json"
PROTOCOL = ROOT / "configs/aat_v2_registered_protocol_v1.json"
ASSIGNMENT = ROOT / "configs/aat_v2_dataset_assignment_v1.json"
AMENDMENT = ROOT / "configs/aat_v2_e_arm_compact_schema_amendment_v1.json"
LOCAL_IDENTITY = ROOT / "configs/aat_v2_ollama_qwen_actor_identity_v1.json"
LOCAL_AUTHORIZATION = ROOT / "configs/aat_v2_ollama_local_training_authorization_v1.json"
RUNPOD_IDENTITY = ROOT / "configs/aat_v2_ollama_qwen_14b_runpod_actor_identity_v1.json"
RUNPOD_AUTHORIZATION = ROOT / "configs/aat_v2_ollama_runpod_training_authorization_v1.json"
INDEX = ROOT / "configs/fixtures/aat_v2_training_opportunities_smoke_v1.jsonl"
SNAPSHOT = ROOT / "configs/fixtures/aat_v2_training_snapshot_smoke_v1.jsonl"
LOCAL_FIXTURE = ROOT / "configs/fixtures/ollama_qwen_training_v1.json"
RUNPOD_FIXTURE = ROOT / "configs/fixtures/ollama_qwen_14b_runpod_training_v1.json"
SCRIPT = ROOT / "scripts/run_aat_v2_ollama_local_training.py"
RUNPOD_IDENTITY_HASH = declared_ollama_runpod_identity()["identity_hash"]
REMOTE_BASE_URL = "http://10.8.0.14:11434"


def _run(tmp_path, **kwargs):
    defaults = dict(
        training_plan_path=PLAN,
        protocol_path=PROTOCOL,
        assignment_path=ASSIGNMENT,
        opportunity_index_path=INDEX,
        snapshot_path=SNAPSHOT,
        amendment_path=AMENDMENT,
        identity_path=RUNPOD_IDENTITY,
        authorization_path=RUNPOD_AUTHORIZATION,
        output_dir=tmp_path / "run",
        limit_opportunities=DEFAULT_SMOKE_LIMIT,
        authorize_local_training=False,
        authorize_runpod_training=False,
        allow_live=False,
        transport=fixture_transport(RUNPOD_FIXTURE, model_id="qwen2.5:14b"),
        include_deliberation=True,
        base_url=REMOTE_BASE_URL,
    )
    defaults.update(kwargs)
    return run_ollama_local_training(**defaults)


def test_runpod_smoke_uses_mocked_remote_transport_and_stays_absent(tmp_path):
    result = _run(tmp_path)
    assert result["status"] == SMOKE_STATUS
    assert result["dry_run"] is True
    assert result["live_calls"] is False
    assert result["execution_authorized"] is False
    assert result["execution_authority"] == "ABSENT"
    assert result["sealed_holdout_consumed"] is False
    assert result["registration_status"] == "REGISTERED_NOT_AUTHORIZED"
    assert result["terra_protocol_not_reused"] is True
    assert result["runpod_training"] is True
    assert result["local_9b_identity_not_reused"] is True
    assert result["candidate_model_id"] == "qwen2.5:14b"
    assert result["actor_identity_hash"] == RUNPOD_IDENTITY_HASH
    assert result["actor_identity_status"] == "RUNPOD_TRAINING_CANDIDATE"
    assert result["authorization_cli_flag"] == RUNPOD_CLI_AUTHORIZATION_FLAG
    assert result["authorize_runpod_training"] is False
    assert result["base_url"] == REMOTE_BASE_URL
    assert result["transport_host_scope"] == "remote"
    assert result["max_concurrent_calls"] == 1
    assert result["opportunity_count"] == 1
    assert result["request_count"] == 7
    assert result["accepted_count"] == 7
    assert all(row["execution_authority"] == "ABSENT" for row in result["records"])
    assert "Admin_i" not in json.dumps(result["records"])
    for row in result["records"]:
        if row["arm"] != "E_DELIBERATION" and row["decision"]:
            assert set(row["decision"]) == {
                "action", "confidence", "horizon", "invalidation", "rationale",
            }


def test_runpod_ssh_tunnel_loopback_is_allowed_for_14b(tmp_path):
    result = _run(tmp_path, base_url="http://127.0.0.1:11434")
    assert result["transport_host_scope"] == "loopback"
    assert result["candidate_model_id"] == "qwen2.5:14b"
    assert result["execution_authority"] == "ABSENT"


def test_desktop_9b_identity_refuses_a_remote_base_url(tmp_path):
    with pytest.raises(OllamaTrainingError, match="non-loopback"):
        _run(
            tmp_path,
            identity_path=LOCAL_IDENTITY,
            authorization_path=LOCAL_AUTHORIZATION,
            transport=fixture_transport(LOCAL_FIXTURE),
            base_url=REMOTE_BASE_URL,
        )


def test_runpod_full_plan_without_its_flag_is_refused(tmp_path):
    with pytest.raises(OllamaTrainingError, match=RUNPOD_CLI_AUTHORIZATION_FLAG):
        _run(tmp_path, limit_opportunities=None, authorize_runpod_training=False)


def test_local_training_flag_does_not_authorize_runpod_14b(tmp_path):
    with pytest.raises(OllamaTrainingError, match="local TRAINING flag"):
        _run(tmp_path, authorize_local_training=True, limit_opportunities=2)


def test_runpod_flag_does_not_authorize_desktop_9b(tmp_path):
    with pytest.raises(OllamaTrainingError, match="RunPod TRAINING authorization"):
        _run(
            tmp_path,
            identity_path=LOCAL_IDENTITY,
            authorization_path=RUNPOD_AUTHORIZATION,
            transport=fixture_transport(LOCAL_FIXTURE),
            base_url="http://127.0.0.1:11434",
            authorize_runpod_training=True,
            limit_opportunities=2,
        )


def test_authorized_runpod_warmup_is_in_sample_not_a_terra_flip(tmp_path):
    result = _run(tmp_path, authorize_runpod_training=True, limit_opportunities=2)
    assert result["status"] == IN_SAMPLE_STATUS
    assert result["authorize_runpod_training"] is True
    assert result["authorize_local_training"] is False
    assert result["full_plan"] is False
    assert result["opportunity_count"] == 2
    assert result["request_count"] == 14
    assert result["execution_authorized"] is False
    assert result["execution_authority"] == "ABSENT"
    assert result["registration_status"] == "REGISTERED_NOT_AUTHORIZED"


def test_model_tag_swap_without_matching_identity_fails_closed(tmp_path):
    with pytest.raises(OllamaTrainingError, match="model id"):
        _run(tmp_path, model_id="qwen3.5:9b")
    with pytest.raises(OllamaTrainingError, match="model id"):
        _run(tmp_path, model_id="qwen3:14b")


def test_semaphore_64_style_concurrency_is_refused(tmp_path):
    with pytest.raises(OllamaTrainingError, match="cannot exceed 4"):
        _run(tmp_path, max_concurrent_calls=64)


def test_bounded_concurrency_two_is_honest_and_keeps_e_sequential(tmp_path):
    result = _run(
        tmp_path,
        authorize_runpod_training=True,
        limit_opportunities=2,
        max_concurrent_calls=2,
    )
    assert result["max_concurrent_calls"] == 2
    assert result["request_count"] == 14
    assert result["accepted_count"] == 14
    sequences = [row["sequence"] for row in result["records"]]
    assert sorted(sequences) == list(range(1, 15))
    assert len(set(sequences)) == 14
    by_opp = {}
    for row in result["records"]:
        by_opp.setdefault(row["opportunity_id"], []).append(row)
    for rows in by_opp.values():
        e_turns = [row["turn"] for row in rows if row["arm"] == "E_DELIBERATION"]
        assert e_turns == ["BULL", "BEAR", "TRADER", "RISK"]


def test_remote_chat_url_requires_opt_in_and_stays_on_native_api():
    with pytest.raises(OllamaTransportError, match="loopback"):
        loopback_chat_url(REMOTE_BASE_URL)
    with pytest.raises(OllamaTransportError, match="non-loopback"):
        ollama_chat_url(REMOTE_BASE_URL, allow_remote=False)
    assert ollama_chat_url(REMOTE_BASE_URL, allow_remote=True) == (
        "http://10.8.0.14:11434/api/chat"
    )
    assert ollama_chat_url("https://pod.example:11434", allow_remote=True) == (
        "https://pod.example:11434/api/chat"
    )
    with pytest.raises(OllamaTransportError, match="only uses /api/chat"):
        ollama_chat_url("http://10.8.0.14:11434/v1/chat/completions", allow_remote=True)
    with pytest.raises(OllamaTransportError, match="credentials"):
        ollama_chat_url("http://user:pass@10.8.0.14:11434", allow_remote=True)
    assert transport_host_scope(REMOTE_BASE_URL) == "remote"
    assert transport_host_scope("http://127.0.0.1:11434") == "loopback"


def test_https_runpod_proxy_without_port_does_not_force_11434():
    proxy = "https://svy1eeqveu3tnp-11434.proxy.runpod.net"
    with pytest.raises(OllamaTransportError, match="non-loopback"):
        ollama_chat_url(proxy, allow_remote=False)
    chat = ollama_chat_url(proxy, allow_remote=True)
    assert chat == f"{proxy}/api/chat"
    assert chat != f"{proxy}:11434/api/chat"
    assert ollama_chat_url(f"{proxy}:443", allow_remote=True) == f"{proxy}:443/api/chat"
    assert ollama_chat_url("https://pod.example", allow_remote=True) == (
        "https://pod.example/api/chat"
    )
    assert ollama_chat_url("http://10.8.0.14", allow_remote=True) == (
        "http://10.8.0.14:11434/api/chat"
    )
    assert loopback_chat_url() == "http://127.0.0.1:11434/api/chat"
    assert loopback_chat_url("http://127.0.0.1") == "http://127.0.0.1:11434/api/chat"
    with pytest.raises(OllamaTransportError, match="HTTP only"):
        loopback_chat_url("https://127.0.0.1")


def _request_headers(request) -> dict[str, str]:
    return {key.lower(): value for key, value in request.header_items()}


def test_live_https_runpod_request_omits_11434_and_sets_safe_user_agent(monkeypatch):
    captured: dict = {}

    class FakeResponse:
        def read(self):
            return b'{"done":true,"message":{"content":"{}"}}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=None):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("athena_trading.aat_v2.ollama_transport.urlopen", fake_urlopen)
    proxy = "https://svy1eeqveu3tnp-11434.proxy.runpod.net"
    send = live_ollama_transport(
        base_url=proxy,
        allow_remote=True,
        retries=1,
        timeout_seconds=5,
    )
    send({"think": False, "stream": False, "model": "qwen2.5:14b"})
    request = captured["request"]
    assert request.full_url == f"{proxy}/api/chat"
    assert request.get_method() == "POST"
    headers = _request_headers(request)
    assert headers["user-agent"] == OLLAMA_USER_AGENT
    assert "urllib" not in headers["user-agent"].lower()
    assert headers["content-type"] == "application/json"
    built = ollama_http_headers()
    assert built["User-Agent"] == OLLAMA_USER_AGENT
    assert "urllib" not in built["User-Agent"].lower()

    send_443 = live_ollama_transport(
        base_url=f"{proxy}:443",
        allow_remote=True,
        retries=1,
        timeout_seconds=5,
    )
    send_443({"think": False, "stream": False, "model": "qwen2.5:14b"})
    assert captured["request"].full_url == f"{proxy}:443/api/chat"
    assert _request_headers(captured["request"])["user-agent"] == OLLAMA_USER_AGENT


def test_live_https_without_remote_opt_in_never_opens(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("urlopen must not run without allow_remote")

    monkeypatch.setattr("athena_trading.aat_v2.ollama_transport.urlopen", boom)
    with pytest.raises(OllamaTransportError, match="non-loopback"):
        live_ollama_transport(
            base_url="https://svy1eeqveu3tnp-11434.proxy.runpod.net",
            allow_remote=False,
        )


def test_runpod_payload_keeps_real_actor_schema_not_a_toy_instructor_shape():
    packet = build_packet(
        arm="D_ATHENA",
        opportunity_id="op-1",
        features={"opaque": 1},
        actor_identity=RUNPOD_IDENTITY_HASH,
        exogenous_features={key: 0 for key in feature_keys()},
    )
    payload = build_ollama_payload(
        packet, max_output_tokens=256, model_id="qwen2.5:14b",
    )
    assert payload["model"] == "qwen2.5:14b"
    assert payload["think"] is False
    assert payload["format"] == "json"
    system = payload["messages"][0]["content"]
    assert "ENTER_HIGH_CONVICTION" in system
    assert "Admin_i" not in system


def test_cli_runpod_smoke_prints_ok_without_live_http(tmp_path, capsys):
    import importlib.util

    spec = importlib.util.spec_from_file_location("run_aat_v2_ollama_local_training", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    code = module.main([
        "--identity", str(RUNPOD_IDENTITY),
        "--authorization", str(RUNPOD_AUTHORIZATION),
        "--base-url", REMOTE_BASE_URL,
        "--output-dir", str(tmp_path / "cli"),
        "--limit-opportunities", "1",
    ])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["live_calls"] is False
    assert payload["candidate_model_id"] == "qwen2.5:14b"
    assert payload["execution_authority"] == "ABSENT"
    assert payload["runpod_training"] is True
    assert "DEEPSEEK" not in json.dumps(payload)
