import json

import pytest

from athena_trading.aat_v1 import (
    AATValidationError,
    TrainingRow,
    execute_transport_canary,
    price_requests,
)


PRICING = {
    "input_usd_per_million_tokens": 2.0,
    "output_usd_per_million_tokens": 12.0,
}


def _rows():
    return (TrainingRow("o1", "c1", {"direction": "LONG", "signal_minute": 15}),)


def _response(payload, key):
    assert key == "secret-not-serialized"
    return {
        "id": "resp_test",
        "model": "gpt-5.6-terra",
        "status": "completed",
        "output_text": json.dumps({
            "action": "PASS", "confidence": 0.5, "horizon": "SESSION",
            "invalidation": "RANGE", "rationale": "Insufficient evidence.",
        }),
        "usage": {"input_tokens": 100, "output_tokens": 20},
    }


def test_prices_three_actor_arms_conservatively():
    priced = price_requests(_rows(), model_id="gpt-5.6-terra", actor_identity="a", pricing=PRICING)
    assert priced["request_count"] == 3
    assert priced["output_token_ceiling"] == 768
    assert priced["worst_case_cost_usd"] > 0
    assert priced["per_request_cost_upper_bound_usd"] * 3 == pytest.approx(priced["worst_case_cost_usd"])


def test_transport_canary_writes_no_key_and_claims_no_adaptation(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    result = execute_transport_canary(
        _rows(), model_id="gpt-5.6-terra", actor_identity="a", pricing=PRICING,
        spend_ceiling_usd=1, token_ceiling=10000, ledger_path=ledger, api_key="secret-not-serialized",
        transport=_response,
    )
    assert result["request_count"] == 3
    assert result["recorded_actual_cost_usd"] == pytest.approx(0.00132)
    assert result["status"] == "TRANSPORT_CANARY_NOT_ADAPTATION"
    assert result["execution_authority"] == "ABSENT"
    assert "secret-not-serialized" not in ledger.read_text(encoding="utf-8")
    assert {json.loads(line)["arm"] for line in ledger.read_text().splitlines()} == {
        "B_MEMORYLESS", "C_NAIVE_MEMORY", "D_ATHENA",
    }


def test_worst_case_cost_blocks_before_transport(tmp_path):
    called = False

    def transport(payload, key):
        nonlocal called
        called = True
        return _response(payload, key)

    with pytest.raises(AATValidationError, match="worst-case cost"):
        execute_transport_canary(
            _rows(), model_id="gpt-5.6-terra", actor_identity="a", pricing=PRICING,
            spend_ceiling_usd=0, token_ceiling=10000, ledger_path=tmp_path / "ledger.jsonl",
            api_key="secret-not-serialized", transport=transport,
        )
    assert called is False


def test_response_identity_drift_is_recorded_as_rejected(tmp_path):
    def drift(payload, key):
        return {**_response(payload, key), "model": "different-model"}

    result = execute_transport_canary(
        _rows(), model_id="gpt-5.6-terra", actor_identity="a", pricing=PRICING,
        spend_ceiling_usd=1, token_ceiling=10000, ledger_path=tmp_path / "ledger.jsonl",
        api_key="secret-not-serialized", transport=drift,
    )
    assert result["accepted_count"] == 0
    assert result["rejected_count"] == 3


def test_request_offset_preserves_total_sequence(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    result = execute_transport_canary(
        _rows(), model_id="gpt-5.6-terra", actor_identity="a", pricing=PRICING,
        spend_ceiling_usd=1, token_ceiling=10000, ledger_path=ledger,
        api_key="secret-not-serialized", transport=_response, request_offset=2,
    )
    assert result["request_count"] == 1
    assert json.loads(ledger.read_text())["sequence"] == 3


def test_token_ceiling_blocks_before_transport(tmp_path):
    called = False

    def transport(payload, key):
        nonlocal called
        called = True
        return _response(payload, key)

    with pytest.raises(AATValidationError, match="token ceiling"):
        execute_transport_canary(
            _rows(), model_id="gpt-5.6-terra", actor_identity="a", pricing=PRICING,
            spend_ceiling_usd=1, token_ceiling=1, ledger_path=tmp_path / "ledger.jsonl",
            api_key="secret-not-serialized", transport=transport,
        )
    assert called is False
