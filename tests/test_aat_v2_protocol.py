import json
from pathlib import Path

import pytest

from athena_trading.aat_v2 import ProtocolError, register_protocol


ROOT = Path(__file__).parents[1]


def _write_inputs(tmp_path, *, macro=1.0):
    contract = json.loads((ROOT / "configs/aat_v2_claim_contract_v1.json").read_text())
    assignment = json.loads((ROOT / "configs/aat_v2_dataset_assignment_v1.json").read_text())
    opportunity = {
        "schema_version": "athena-aat-v2-opportunity-index-v1",
        "row_count": 1,
        "index_hash": "i" * 64,
        "contains_outcomes": False,
        "contains_sealed_holdout": False,
    }
    snapshot = {
        "schema_version": "athena-exogenous-snapshot-v1",
        "row_count": 1,
        "snapshot_hash": "s" * 64,
        "coverage_rates": {"macro": macro},
        "contains_outcomes": False,
        "execution_authority": "ABSENT",
    }
    paths = {}
    for name, value in (("contract", contract), ("assignment", assignment), ("opportunity", opportunity), ("snapshot", snapshot)):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        paths[name] = path
    return paths


def test_registers_non_authorizing_protocol(tmp_path):
    paths = _write_inputs(tmp_path)
    output = tmp_path / "protocol.json"

    result = register_protocol(paths["contract"], paths["assignment"], paths["opportunity"], paths["snapshot"], output)

    assert result["protocol"]["registration_status"] == "REGISTERED_NOT_AUTHORIZED"
    assert result["protocol"]["claim_authorized"] is False
    assert result["execution_authority"] == "ABSENT"
    assert result["protocol_hash"]


def test_rejects_snapshot_below_contract_floor(tmp_path):
    paths = _write_inputs(tmp_path, macro=0.89)

    with pytest.raises(ProtocolError, match="coverage floor"):
        register_protocol(paths["contract"], paths["assignment"], paths["opportunity"], paths["snapshot"], tmp_path / "protocol.json")
