"""Offline 7b volume Ollama TRAINING path: mocked transport, no live GPU."""
import json
from pathlib import Path

import pytest

from athena_trading.aat_v2.identity import TERRA_PROTOCOL_HASH
from athena_trading.aat_v2.ollama_identity import (
    VOLUME_CLI_AUTHORIZATION_FLAG,
    declared_ollama_volume_identity,
)
from athena_trading.aat_v2.ollama_training import (
    DEFAULT_SMOKE_LIMIT,
    IN_SAMPLE_STATUS,
    SMOKE_STATUS,
    OllamaTrainingError,
    fixture_transport,
    run_ollama_local_training,
)
from athena_trading.aat_v2.training_subsample import (
    GOLD_KIND,
    SUBSAMPLE_RECEIPT_SCHEMA,
    VOLUME_KIND,
)
from athena_trading.athena_adapter.contracts import canonical_hash


ROOT = Path(__file__).parents[1]
PLAN = ROOT / "configs/aat_v2_training_plan_v2.json"
PROTOCOL = ROOT / "configs/aat_v2_registered_protocol_v1.json"
ASSIGNMENT = ROOT / "configs/aat_v2_dataset_assignment_v1.json"
AMENDMENT = ROOT / "configs/aat_v2_e_arm_compact_schema_amendment_v1.json"
LOCAL_IDENTITY = ROOT / "configs/aat_v2_ollama_qwen_actor_identity_v1.json"
LOCAL_AUTHORIZATION = ROOT / "configs/aat_v2_ollama_local_training_authorization_v1.json"
RUNPOD_IDENTITY = ROOT / "configs/aat_v2_ollama_qwen_14b_runpod_actor_identity_v1.json"
RUNPOD_AUTHORIZATION = ROOT / "configs/aat_v2_ollama_runpod_training_authorization_v1.json"
VOLUME_IDENTITY = ROOT / "configs/aat_v2_ollama_qwen_7b_volume_actor_identity_v1.json"
VOLUME_AUTHORIZATION = ROOT / "configs/aat_v2_ollama_volume_training_authorization_v1.json"
INDEX = ROOT / "configs/fixtures/aat_v2_training_opportunities_smoke_v1.jsonl"
SNAPSHOT = ROOT / "configs/fixtures/aat_v2_training_snapshot_smoke_v1.jsonl"
LOCAL_FIXTURE = ROOT / "configs/fixtures/ollama_qwen_training_v1.json"
RUNPOD_FIXTURE = ROOT / "configs/fixtures/ollama_qwen_14b_runpod_training_v1.json"
VOLUME_FIXTURE = ROOT / "configs/fixtures/ollama_qwen_7b_volume_training_v1.json"
SCRIPT = ROOT / "scripts/run_aat_v2_ollama_local_training.py"
ASSIGNMENT_HASH = "46f25ba0f64c5088add6d37a72752d6fbe156de6c33e8b8d7d4415e160f5e731"
VOLUME_IDENTITY_HASH = declared_ollama_volume_identity()["identity_hash"]
REMOTE_BASE_URL = "http://10.8.0.14:11434"
SMOKE_IDS = ("ollama-smoke-aapl-1", "ollama-smoke-msft-1")


def _receipt_payload(kind, ids, *, parent_kind, target=None):
    payload = {
        "schema_version": SUBSAMPLE_RECEIPT_SCHEMA,
        "subsample_kind": kind,
        "parent_kind": parent_kind,
        "parent_hash": "test-parent",
        "parent_partition": "TRAINING",
        "plan_hash": "test-plan",
        "seed": 20260916,
        "stratification": "symbol",
        "target_count": len(ids) if target is None else target,
        "selected_count": len(ids),
        "opportunity_ids": list(ids),
        "assignment_hash": ASSIGNMENT_HASH,
        "consulted_terra_protocol_hash": TERRA_PROTOCOL_HASH,
        "drawn_from_outcomes": False,
        "drawn_from_exogenous_features": False,
        "authorizes_full_16705_plan": False,
        "execution_authorized": False,
        "claim_authorized": False,
        "execution_authority": "ABSENT",
        "sealed_holdout_consumed": False,
        "source_document": "docs/AAT_V2_MODEL_EXECUTION_OPTIONS.md",
    }
    payload["subsample_hash"] = canonical_hash(payload)
    return payload


def _write_receipt(path, kind, ids, *, parent_kind, target=None):
    payload = _receipt_payload(kind, ids, parent_kind=parent_kind, target=target)
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return payload


def _run(tmp_path, **kwargs):
    defaults = dict(
        training_plan_path=PLAN,
        protocol_path=PROTOCOL,
        assignment_path=ASSIGNMENT,
        opportunity_index_path=INDEX,
        snapshot_path=SNAPSHOT,
        amendment_path=AMENDMENT,
        identity_path=VOLUME_IDENTITY,
        authorization_path=VOLUME_AUTHORIZATION,
        output_dir=tmp_path / "run",
        limit_opportunities=DEFAULT_SMOKE_LIMIT,
        authorize_local_training=False,
        authorize_runpod_training=False,
        authorize_volume_training=False,
        allow_live=False,
        transport=fixture_transport(VOLUME_FIXTURE, model_id="qwen2.5:7b"),
        include_deliberation=True,
        base_url=REMOTE_BASE_URL,
    )
    defaults.update(kwargs)
    return run_ollama_local_training(**defaults)


def test_volume_smoke_uses_mocked_remote_transport_and_stays_absent(tmp_path):
    result = _run(tmp_path)
    assert result["status"] == SMOKE_STATUS
    assert result["dry_run"] is True
    assert result["live_calls"] is False
    assert result["execution_authorized"] is False
    assert result["execution_authority"] == "ABSENT"
    assert result["sealed_holdout_consumed"] is False
    assert result["registration_status"] == "REGISTERED_NOT_AUTHORIZED"
    assert result["terra_protocol_not_reused"] is True
    assert result["volume_training"] is True
    assert result["runpod_training"] is False
    assert result["local_9b_identity_not_reused"] is True
    assert result["runpod_14b_identity_not_reused"] is True
    assert result["candidate_model_id"] == "qwen2.5:7b"
    assert result["actor_identity_hash"] == VOLUME_IDENTITY_HASH
    assert result["actor_identity_status"] == "VOLUME_TRAINING_CANDIDATE"
    assert result["authorization_cli_flag"] == VOLUME_CLI_AUTHORIZATION_FLAG
    assert result["authorize_volume_training"] is False
    assert result["full_plan"] is False
    assert result["base_url"] == REMOTE_BASE_URL
    assert result["transport_host_scope"] == "remote"
    assert result["opportunity_count"] == 1
    assert result["request_count"] == 7
    assert result["accepted_count"] == 7
    assert result["include_deliberation"] is True
    assert "Admin_i" not in json.dumps(result["records"])


def test_volume_ssh_tunnel_loopback_is_allowed_for_8b(tmp_path):
    result = _run(tmp_path, base_url="http://127.0.0.1:11434")
    assert result["transport_host_scope"] == "loopback"
    assert result["candidate_model_id"] == "qwen2.5:7b"
    assert result["execution_authority"] == "ABSENT"


def test_volume_plan_without_its_flag_is_refused(tmp_path):
    with pytest.raises(OllamaTrainingError, match=VOLUME_CLI_AUTHORIZATION_FLAG):
        _run(tmp_path, limit_opportunities=None, authorize_volume_training=False)


def test_volume_plan_without_subsample_receipt_is_refused(tmp_path):
    with pytest.raises(OllamaTrainingError, match="hashed subsample receipt"):
        _run(tmp_path, limit_opportunities=None, authorize_volume_training=True)


def test_runpod_flag_does_not_authorize_volume_7b(tmp_path):
    with pytest.raises(OllamaTrainingError, match="RunPod TRAINING flag"):
        _run(tmp_path, authorize_runpod_training=True, limit_opportunities=2)


def test_volume_flag_does_not_authorize_gold_14b(tmp_path):
    with pytest.raises(OllamaTrainingError, match="volume TRAINING authorization"):
        _run(
            tmp_path,
            identity_path=RUNPOD_IDENTITY,
            authorization_path=VOLUME_AUTHORIZATION,
            transport=fixture_transport(RUNPOD_FIXTURE, model_id="qwen2.5:14b"),
            authorize_volume_training=True,
            limit_opportunities=2,
        )


def test_local_training_flag_does_not_authorize_volume_7b(tmp_path):
    with pytest.raises(OllamaTrainingError, match="local TRAINING flag"):
        _run(tmp_path, authorize_local_training=True, limit_opportunities=2)


def test_volume_authorization_does_not_cover_desktop_9b(tmp_path):
    with pytest.raises(OllamaTrainingError, match="volume TRAINING authorization"):
        _run(
            tmp_path,
            identity_path=LOCAL_IDENTITY,
            authorization_path=VOLUME_AUTHORIZATION,
            transport=fixture_transport(LOCAL_FIXTURE),
            base_url="http://127.0.0.1:11434",
            authorize_volume_training=True,
            limit_opportunities=2,
        )


def test_authorized_volume_warmup_is_in_sample_not_a_terra_flip(tmp_path):
    result = _run(tmp_path, authorize_volume_training=True, limit_opportunities=2)
    assert result["status"] == IN_SAMPLE_STATUS
    assert result["authorize_volume_training"] is True
    assert result["authorize_runpod_training"] is False
    assert result["authorize_local_training"] is False
    assert result["full_plan"] is False
    assert result["volume_plan"] is False
    assert result["opportunity_count"] == 2
    assert result["request_count"] == 14
    assert result["execution_authorized"] is False
    assert result["execution_authority"] == "ABSENT"
    assert result["registration_status"] == "REGISTERED_NOT_AUTHORIZED"


def test_volume_thin_e_skips_deliberation_on_the_same_7b_actor(tmp_path):
    result = _run(
        tmp_path,
        authorize_volume_training=True,
        limit_opportunities=2,
        include_deliberation=False,
    )
    assert result["include_deliberation"] is False
    assert result["request_count"] == 6
    assert result["candidate_model_id"] == "qwen2.5:7b"
    assert result["actor_identity_hash"] == VOLUME_IDENTITY_HASH
    assert all(row["arm"] != "E_DELIBERATION" for row in result["records"])
    assert result["execution_authority"] == "ABSENT"


def test_volume_subsample_receipt_selects_pinned_ids(tmp_path):
    _write_receipt(
        tmp_path / "volume.receipt.json",
        VOLUME_KIND,
        [SMOKE_IDS[1]],
        parent_kind="TRAINING",
    )
    with pytest.raises(OllamaTrainingError, match="frozen opportunity receipt"):
        _run(
            tmp_path, authorize_volume_training=True, limit_opportunities=2,
            subsample_receipt_path=tmp_path / "volume.receipt.json",
        )


def test_gold_14b_keeps_e_and_does_not_reuse_the_7b_identity(tmp_path):
    _write_receipt(
        tmp_path / "gold.receipt.json",
        GOLD_KIND,
        list(SMOKE_IDS),
        parent_kind=VOLUME_KIND,
    )
    with pytest.raises(OllamaTrainingError, match="frozen opportunity receipt"):
        _run(
            tmp_path, identity_path=RUNPOD_IDENTITY,
            authorization_path=RUNPOD_AUTHORIZATION,
            transport=fixture_transport(RUNPOD_FIXTURE, model_id="qwen2.5:14b"),
            authorize_runpod_training=True, limit_opportunities=2,
            subsample_receipt_path=tmp_path / "gold.receipt.json",
        )


def test_volume_identity_refuses_a_gold_receipt(tmp_path):
    _write_receipt(
        tmp_path / "gold.receipt.json",
        GOLD_KIND,
        list(SMOKE_IDS),
        parent_kind=VOLUME_KIND,
    )
    with pytest.raises(OllamaTrainingError, match="subsample receipt kind"):
        _run(
            tmp_path,
            authorize_volume_training=True,
            limit_opportunities=2,
            subsample_receipt_path=tmp_path / "gold.receipt.json",
        )


def test_model_tag_swap_without_matching_volume_identity_fails_closed(tmp_path):
    with pytest.raises(OllamaTrainingError, match="model id"):
        _run(tmp_path, model_id="qwen2.5:14b")
    with pytest.raises(OllamaTrainingError, match="model id"):
        _run(tmp_path, model_id="qwen3.5:9b")


def test_cli_volume_smoke_prints_ok_without_live_http(tmp_path, capsys):
    import importlib.util

    spec = importlib.util.spec_from_file_location("run_aat_v2_ollama_local_training", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    code = module.main([
        "--identity", str(VOLUME_IDENTITY),
        "--authorization", str(VOLUME_AUTHORIZATION),
        "--base-url", REMOTE_BASE_URL,
        "--output-dir", str(tmp_path / "cli"),
        "--limit-opportunities", "1",
    ])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["live_calls"] is False
    assert payload["candidate_model_id"] == "qwen2.5:7b"
    assert payload["execution_authority"] == "ABSENT"
    assert payload["volume_training"] is True
    assert payload["runpod_training"] is False
    assert "DEEPSEEK" not in json.dumps(payload)
