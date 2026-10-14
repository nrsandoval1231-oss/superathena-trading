"""Source inventory stays reconciled with the files in this checkout."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/migration/source-manifest.json"
ANCHOR = "8bd0e7289e0a4899ec7e12291ca02a2c883c583d"
IMMUTABLE = (
    "configs/aat_consumed_holdouts_v1.json",
    "configs/aat_v1_final_claim_contract_v1.json",
    "configs/aat_v1_sealed_holdout_authorization_v1.json",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_every_source_file_is_accounted_for_and_hashes_match():
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert payload["source_commit"] == ANCHOR
    assert payload["source_remote_head_verified"] == ANCHOR
    files = payload["files"]
    assert len(files) == payload["source_file_count"] == 265
    assert len({item["source_path"] for item in files}) == 265
    for item in files:
        destination = ROOT / item["destination_path"]
        assert destination.is_file(), item["destination_path"]
        assert _sha256(destination) == item["destination_sha256"]
        if item["disposition"] == "migrated":
            assert item["source_sha256"] == item["destination_sha256"]
        elif item["disposition"] == "migrated-import-adjusted":
            assert item["source_sha256"] != item["destination_sha256"]
        elif item["disposition"] == "preserved-lineage":
            assert item["source_sha256"] == item["destination_sha256"]
        else:
            raise AssertionError(item["disposition"])
    core = payload["athena_core"]
    assert core["anchor"] == "adba694563751256f5f5e95ad47079b37c7697ec"
    assert core["disposition"] == "external-dependency-unavailable"
    assert "Repository not found" in core["blocker"]


def test_consumed_holdouts_remain_byte_for_byte():
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    by_source = {item["source_path"]: item for item in payload["files"]}
    for relative in IMMUTABLE:
        item = by_source[relative]
        assert item["disposition"] == "migrated"
        assert _sha256(ROOT / relative) == item["source_sha256"]
    holdout = (ROOT / "configs/aat_consumed_holdouts_v1.json").read_text(encoding="utf-8")
    assert "INVALID_EVIDENCE" in holdout
