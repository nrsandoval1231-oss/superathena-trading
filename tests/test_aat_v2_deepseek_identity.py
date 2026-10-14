"""DeepSeek Flash is a hashed V2 candidate identity, not a Terra substitute."""
import json
from pathlib import Path

import pytest

from athena_trading.aat_v1.actor_canary import ACTION_SCHEMA, INFERENCE, PROMPT
from athena_trading.aat_v1.providers import DEEPSEEK, OPENAI, provider_identity, registered_providers
from athena_trading.aat_v2.deliberation import deliberation_plan
from athena_trading.aat_v2.identity import (
    IDENTITY_STATUS,
    MODEL_ID,
    PILOT_INFERENCE,
    PILOT_PROMPT,
    PROVIDER,
    TERRA_INFERENCE_HASH,
    TERRA_MODEL_HASH,
    TERRA_MODEL_ID,
    TERRA_PROMPT_HASH,
    TERRA_PROTOCOL_HASH,
    IdentityError,
    declared_deepseek_flash_identity,
    load_deepseek_flash_identity,
)
from athena_trading.athena_adapter.contracts import canonical_hash


ROOT = Path(__file__).parents[1]
IDENTITY = ROOT / "configs/aat_v2_deepseek_flash_actor_identity_v1.json"
PROTOCOL = ROOT / "configs/aat_v2_registered_protocol_v1.json"
TERRA_IDENTITY = ROOT / "configs/aat_v2_actor_identity_v1.json"

DEEPSEEK_MODEL_HASH = "fb29a56e6339dcb78992aa27c81639302223941cb19b65c020ee2c081720bf24"
DEEPSEEK_PROMPT_HASH = "77529c560194500af75602952634685fdc10e311105a01f07ac540fdcd2af734"
DEEPSEEK_INFERENCE_HASH = "a7424ce9fcd22701721825ed16188eea784b5bab582bb95da50e6dd5b750566e"
DEEPSEEK_IDENTITY_HASH = "ee1133be82fd4a1bc20a03adb00685187a5a44aa10957312eaa6991eb42b33cd"
SHARED_ACTION_SCHEMA_HASH = "852c32a80b5f4187ea6629270bfaf14162779e1a742690716a337eb107a26b3c"


def test_declared_identity_is_provider_scoped_and_not_terra():
    identity = declared_deepseek_flash_identity()
    terra = provider_identity(
        OPENAI, model_id=TERRA_MODEL_ID, prompt=PROMPT, inference=INFERENCE,
        action_schema=ACTION_SCHEMA,
    )
    assert identity["provider"] == PROVIDER == "deepseek"
    assert identity["model_id"] == MODEL_ID == "deepseek-flash"
    assert identity["identity_status"] == IDENTITY_STATUS == "CANDIDATE_PILOT"
    assert identity["bound_to_registered_protocol"] is False
    assert identity["rewrites_registered_protocol"] is False
    assert identity["execution_authorized"] is False
    assert identity["claim_authorized"] is False
    assert identity["execution_authority"] == "ABSENT"
    assert identity["sealed_holdout_consumed"] is False
    assert identity["pilot_is_not_training"] is True
    assert identity["terra_protocol_not_reused"] is True
    assert identity["consulted_terra_protocol_hash"] == TERRA_PROTOCOL_HASH
    assert identity["model_hash"] == DEEPSEEK_MODEL_HASH
    assert identity["prompt_hash"] == DEEPSEEK_PROMPT_HASH
    assert identity["inference_hash"] == DEEPSEEK_INFERENCE_HASH
    assert identity["identity_hash"] == DEEPSEEK_IDENTITY_HASH
    assert identity["model_hash"] != terra["model_hash"] == TERRA_MODEL_HASH
    assert identity["prompt_hash"] != terra["prompt_hash"] == TERRA_PROMPT_HASH
    assert identity["inference_hash"] != terra["inference_hash"] == TERRA_INFERENCE_HASH
    assert identity["action_schema_hash"] == terra["action_schema_hash"] == SHARED_ACTION_SCHEMA_HASH
    assert identity["deliberation_hash"] == deliberation_plan()["deliberation_hash"]
    assert identity["inference"] == PILOT_INFERENCE
    assert identity["prompt"] == PILOT_PROMPT
    assert identity["inference"]["thinking"] == {"type": "disabled"}
    assert identity["inference"]["max_output_tokens"] == 512


def test_committed_identity_matches_declaration_and_consults_terra():
    loaded = load_deepseek_flash_identity(IDENTITY, protocol_path=PROTOCOL)
    declared = declared_deepseek_flash_identity()
    assert loaded == declared
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    terra = json.loads(TERRA_IDENTITY.read_text(encoding="utf-8"))
    assert protocol["protocol_hash"] == TERRA_PROTOCOL_HASH
    assert protocol["protocol"]["actor_identity"]["provider"] == "openai"
    assert protocol["protocol"]["actor_identity"]["model_id"] == "gpt-5.6-terra"
    assert terra["provider"] == "openai"
    assert loaded["provider"] != terra["provider"]
    assert loaded["model_hash"] != terra["model_hash"]
    assert registered_providers() == ("openai",)
    assert DEEPSEEK.model_hash(MODEL_ID) == loaded["model_hash"]


def test_identity_hash_tamper_is_refused(tmp_path):
    payload = json.loads(IDENTITY.read_text(encoding="utf-8"))
    payload["prompt"] = "not the declared prompt"
    path = tmp_path / "identity.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(IdentityError, match="identity_hash"):
        load_deepseek_flash_identity(path, protocol_path=PROTOCOL)


def test_identity_refuses_a_terra_protocol_swap(tmp_path):
    payload = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    payload["protocol"]["actor_identity"]["provider"] = "deepseek"
    payload["protocol"]["actor_identity"]["model_id"] = MODEL_ID
    body = dict(payload)
    body.pop("protocol_hash")
    payload["protocol_hash"] = canonical_hash(body)
    path = tmp_path / "protocol.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(IdentityError, match="Terra"):
        load_deepseek_flash_identity(IDENTITY, protocol_path=path)


def test_holdout_identity_paths_are_forbidden(tmp_path):
    bad = tmp_path / "sealed_holdout_identity.json"
    bad.write_text("{}", encoding="utf-8")
    with pytest.raises(IdentityError, match="holdout"):
        load_deepseek_flash_identity(bad, protocol_path=PROTOCOL)
