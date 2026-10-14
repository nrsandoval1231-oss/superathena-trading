"""Byte-level pins on the registered AAT-V1 Actor identity.

Every AAT-V1 receipt records these digests.  If a refactor moves one, prior
receipts stop verifying and the audit trail breaks silently -- the code keeps
running and the evidence stops meaning what it says.

These literals were captured from the registered V1 protocol before the
provider registry existed.  They are not to be regenerated from the code they
guard: a test that recomputes its own expectation proves nothing.  If a change
makes one of these fail, the change is wrong, not the pin.
"""
from athena_trading.aat_v1.actor_canary import ACTION_SCHEMA, API_URL, ARMS, INFERENCE, PROMPT
from athena_trading.athena_adapter.contracts import canonical_hash

REGISTERED_MODEL_ID = "gpt-5.6-terra"

PROMPT_HASH = "b7fa5ec9928d3ec22225bd757aa25b408ffdc9a5d3897bf8717a9d7d44bca88a"
INFERENCE_HASH = "2c1cc91e081dd2f02283a520b0d01a226e9fc8320844e2126f95099de2b68633"
ACTION_SCHEMA_HASH = "852c32a80b5f4187ea6629270bfaf14162779e1a742690716a337eb107a26b3c"
MODEL_HASH = "9c4aaaa136ed098624bee45f5f75d0654f4d56ea526fc4cc51a1f3f3bf1ae5db"


def test_prompt_hash_is_unchanged():
    assert canonical_hash(PROMPT) == PROMPT_HASH


def test_inference_hash_is_unchanged():
    assert canonical_hash(INFERENCE) == INFERENCE_HASH


def test_action_schema_hash_is_unchanged():
    assert canonical_hash(ACTION_SCHEMA) == ACTION_SCHEMA_HASH


def test_model_hash_is_unchanged():
    assert canonical_hash({"provider": "openai", "model": REGISTERED_MODEL_ID}) == MODEL_HASH


def test_transport_endpoint_is_unchanged():
    assert API_URL == "https://api.openai.com/v1/responses"


def test_actor_arms_are_unchanged():
    assert ARMS == ("B_MEMORYLESS", "C_NAIVE_MEMORY", "D_ATHENA")


def test_inference_settings_are_unchanged():
    assert INFERENCE == {
        "endpoint": "responses", "reasoning_effort": "low",
        "store": False, "max_output_tokens": 256,
    }
