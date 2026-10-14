"""Fixture self-improve lab: one-field mutation, sealed holdout, ABSENT receipts."""
from __future__ import annotations

import ast
import importlib.util
import json
import socket
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from athena_trading.execution.authority import ExecutionAuthority
from athena_trading.orb_m.constitution import ManagementParameters
from athena_trading.paper.self_improve import (
    BUILTIN_CATALOG_IDENTITY,
    EXECUTION_AUTHORITY,
    PRECOMMITTED_GATES,
    FieldStep,
    GatePolicy,
    HoldoutSealError,
    MutationScope,
    SliceMetrics,
    builtin_catalog,
    default_scope,
    evaluate_sealed_holdout,
    judge_holdout,
    judge_search,
    lab_constitution,
    lab_parent,
    materialize,
    partition_identity,
    propose_candidates,
    run_fixture_lab,
    run_search,
    score_sessions,
    split_catalog,
)

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "src" / "athena_trading" / "paper" / "self_improve.py"
SCRIPT = ROOT / "scripts" / "run_fixture_self_improve.py"


def _script():
    spec = importlib.util.spec_from_file_location("run_fixture_self_improve", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _candidate(receipt: dict, suffix: str) -> dict:
    matches = [
        record for record in receipt["candidates"] if record["candidate_id"].endswith(suffix)
    ]
    assert len(matches) == 1
    return matches[0]


def test_scope_rejects_constitution_unknown_and_mapping_fields():
    with pytest.raises(ValueError, match="adaptive surface"):
        MutationScope((FieldStep("opening_minutes", 1),))
    with pytest.raises(ValueError, match="adaptive surface"):
        MutationScope((FieldStep("secret_edge", 1.0),))
    with pytest.raises(ValueError, match="scalar"):
        MutationScope((FieldStep("deterioration_weights", 0.1),))


def test_each_proposal_evolves_exactly_one_field(monkeypatch):
    calls: list[tuple[str, ...]] = []
    real = ManagementParameters.evolve

    def wrapped(self, **changes):
        assert len(changes) == 1
        calls.append(tuple(changes))
        return real(self, **changes)

    monkeypatch.setattr(ManagementParameters, "evolve", wrapped)
    candidates = propose_candidates(lab_parent(), default_scope(), 0)
    assert candidates
    assert calls
    assert all(len(change) == 1 for change in calls)
    assert "opening_minutes" not in {name for change in calls for name in change}
    for candidate in candidates:
        assert candidate.legal
        assert candidate.fields_changed == (candidate.field,)
        assert len(candidate.lineage) == 1


def test_illegal_step_is_not_retried_on_another_field():
    candidates = propose_candidates(
        lab_parent(), MutationScope((FieldStep("peak_retention", 1.0),)), 0,
    )
    assert len(candidates) == 2
    assert {candidate.field for candidate in candidates} == {"peak_retention"}
    assert all(not candidate.legal for candidate in candidates)
    assert all(candidate.fields_changed == () for candidate in candidates)
    assert all(candidate.parameters.identity_hash == lab_parent().identity_hash
               for candidate in candidates)


def test_materialize_applies_one_field_per_step(monkeypatch):
    calls: list[tuple[str, ...]] = []
    real = ManagementParameters.evolve

    def wrapped(self, **changes):
        assert len(changes) == 1
        calls.append(tuple(changes))
        return real(self, **changes)

    monkeypatch.setattr(ManagementParameters, "evolve", wrapped)
    child = materialize((
        {"field": "peak_retention", "value": 0.75},
        {"field": "explore_minutes", "value": 6},
    ))
    assert calls == [("peak_retention",), ("explore_minutes",)]
    assert child.peak_retention == 0.75
    assert child.explore_minutes == 6


def test_precommitted_gates_reject_assignment_and_label_samples():
    with pytest.raises(FrozenInstanceError):
        PRECOMMITTED_GATES.min_closed_episodes = 1
    unknown, reason = judge_search(
        SliceMetrics(1, 5.0, 5.0, 0.0, ("s",)),
        SliceMetrics(2, 0.0, 0.0, 0.0, ("s", "t")),
        PRECOMMITTED_GATES,
    )
    assert (unknown, reason) == ("UNKNOWN", "INSUFFICIENT_EVIDENCE")
    failed, fail_reason = judge_search(
        SliceMetrics(3, 0.0, 0.0, -1.0, ("a", "b", "c")),
        SliceMetrics(3, 0.0, 0.0, -1.0, ("a", "b", "c")),
        PRECOMMITTED_GATES,
    )
    assert (failed, fail_reason) == ("FAIL", "DOES_NOT_BEAT_PARENT")
    passed, pass_reason = judge_search(
        SliceMetrics(3, 0.2, 0.6, -0.2, ("a", "b", "c")),
        SliceMetrics(3, 0.1, 0.3, -0.2, ("a", "b", "c")),
        PRECOMMITTED_GATES,
    )
    assert (passed, pass_reason) == ("PASS", "BEATS_PARENT")
    harm, harm_reason = judge_holdout(
        SliceMetrics(1, 0.0, 0.0, -1.0, ("h",)),
        SliceMetrics(1, 0.05, 0.05, -1.0, ("h",)),
        PRECOMMITTED_GATES,
    )
    assert (harm, harm_reason) == ("FAIL", "HOLDOUT_HARM")
    quiet, quiet_reason = judge_holdout(
        SliceMetrics(1, 0.01, 0.01, 0.0, ("h",)),
        SliceMetrics(1, 0.0, 0.0, 0.0, ("h",)),
        PRECOMMITTED_GATES,
    )
    assert (quiet, quiet_reason) == ("UNKNOWN", "HOLDOUT_INCONCLUSIVE")


def test_catalog_is_frozen_and_holdout_starts_after_search():
    sessions = builtin_catalog()
    assert partition_identity(sessions) == BUILTIN_CATALOG_IDENTITY
    search, seal = split_catalog(sessions)
    assert [session.session_id for session in search] == [
        "search-001", "search-002", "search-003",
    ]
    assert seal.accesses == []
    assert seal.identity != partition_identity(search)
    assert lab_constitution().opening_minutes == 15
    assert "LIVE" not in {item.value for item in ExecutionAuthority}
    assert EXECUTION_AUTHORITY == "ABSENT"


def test_scoring_refuses_a_holdout_session_during_search():
    search, _seal = split_catalog(builtin_catalog())
    leaked = replace(search[0], partition="HOLDOUT", session_id="holdout-x")
    with pytest.raises(HoldoutSealError, match="SEARCH"):
        score_sessions(lab_parent(), (leaked,), partition="SEARCH")


def test_search_does_not_open_or_name_the_holdout(tmp_path):
    search, seal = split_catalog(builtin_catalog())
    receipts = run_search(search, holdout_identity=seal.identity, out_dir=tmp_path)
    assert seal.accesses == []
    text = (tmp_path / "generation-000.json").read_text(encoding="utf-8")
    assert "holdout-001" not in text
    assert "2026-04-16" not in text
    receipt = receipts[0]
    assert receipt["sealed_holdout_accessed"] is False
    assert receipt["selection_uses_holdout"] is False
    assert receipt["holdout_identity"] == seal.identity
    seen: set[str] = set()
    for record in receipt["candidates"]:
        seen.update(record["selection"]["session_ids"])
        seen.update(record["burn_in"]["session_ids"])
    assert seen.isdisjoint({"holdout-001"})
    opened = evaluate_sealed_holdout(seal, receipts)
    assert seal.accesses == ["SEALED_EVALUATION"]
    assert opened["holdout_session_ids"] == ["holdout-001"]
    with pytest.raises(HoldoutSealError, match="already opened"):
        seal.open_for_sealed_evaluation()


def test_search_rejects_a_non_search_session(tmp_path):
    search, _seal = split_catalog(builtin_catalog())
    leaked = replace(search[0], partition="HOLDOUT", session_id="holdout-x")
    with pytest.raises(HoldoutSealError, match="non-search"):
        run_search((leaked,), holdout_identity="abc", out_dir=tmp_path)


def test_lab_kills_most_candidates_and_writes_absent_receipts(tmp_path, monkeypatch):
    def _network(*_args, **_kwargs):
        raise AssertionError("network")

    monkeypatch.setattr(socket, "create_connection", _network)
    summary = run_fixture_lab(tmp_path, generations=1)
    assert summary["execution_authority"] == "ABSENT"
    assert summary["promoted_to_paper_pilot"] is False
    assert summary["aat_v1_holdout_consumed"] is False
    assert summary["live_enabled"] is False
    assert summary["holdout_open_count"] == 1
    assert summary["killed"] > summary["survived"]
    assert summary["survived"] >= 1

    receipt = json.loads((tmp_path / "generation-000.json").read_text(encoding="utf-8"))
    assert receipt["schema_version"] == "athena-fixture-self-improve-generation-v1"
    assert receipt["execution_authority"] == "ABSENT"
    assert receipt["alpaca_called"] is False
    assert receipt["typesafe_called"] is False
    assert receipt["network_calls"] is False
    assert receipt["sealed_holdout_accessed"] is False
    assert receipt["paper_walker"]["broker_class"] == "FixtureBroker"
    assert receipt["paper_walker"]["submitted_count"] == 0
    assert receipt["paper_walker"]["halt_reason"] == "AUTHORITY_ABSENT"
    assert receipt["walk_forward"]["burn_in_session_ids"] == ["search-001"]
    assert receipt["walk_forward"]["selection_session_ids"] == ["search-002", "search-003"]
    assert receipt["roles"]["market_lab"] == "athena-trading-paper-walker"
    assert receipt["next_search_parent_candidate"] == "g0-peak_retention-+0.1"
    floor = receipt["gate_policy"]["improvement_floor_r"]
    parent_mean = receipt["parent_selection"]["mean_r"]
    for record in receipt["candidates"]:
        assert record["legal"]
        assert record["fields_changed"] == [record["field"]]
        assert len(record["lineage"]) == 1
        assert materialize(record["lineage"]).identity_hash == record["parameter_identity"]
        assert record["paper_walker"]["submitted_count"] == 0
        assert record["paper_walker"]["execution_authority"] == "ABSENT"
        delta = record["selection"]["mean_r"] - parent_mean
        if record["verdict"] == "PASS":
            assert delta >= floor
        else:
            assert record["verdict"] == "FAIL"
            assert delta < floor

    tighter = _candidate(receipt, "peak_retention-+0.1")
    looser = _candidate(receipt, "peak_retention--0.1")
    assert tighter["verdict"] == "PASS"
    assert looser["verdict"] == "FAIL"
    ignored = _candidate(receipt, "exit_pressure_threshold--0.5")
    assert ignored["verdict"] == "FAIL"
    assert ignored["selection"]["mean_r"] == parent_mean
    assert ignored["burn_in"]["mean_r"] != receipt["parent_burn_in"]["mean_r"]

    holdout = json.loads((tmp_path / "holdout-evaluation.json").read_text(encoding="utf-8"))
    assert holdout["sealed_holdout_accessed"] is True
    assert holdout["holdout_open_count"] == 1
    assert holdout["holdout_session_ids"] == ["holdout-001"]
    assert holdout["execution_authority"] == "ABSENT"
    assert holdout["promoted_to_paper_pilot"] is False
    assert holdout["selection_uses_holdout"] is False
    by_id = {record["candidate_id"]: record for record in holdout["candidates"]}
    assert by_id["g0-peak_retention-+0.1"]["verdict"] == "FAIL"
    assert by_id["g0-atr_trail_multiple--0.5"]["verdict"] == "UNKNOWN"
    assert by_id["g0-first_harvest_fraction--0.05"]["verdict"] == "PASS"
    edge = holdout["gate_policy"]["holdout_confirmation_edge_r"]
    harm = holdout["gate_policy"]["holdout_harm_tolerance_r"]
    for record in holdout["candidates"]:
        assert len(record["fields_changed"]) == 1
        if record["verdict"] == "PASS":
            assert record["delta_r"] >= edge
        elif record["verdict"] == "FAIL":
            assert record["delta_r"] <= -harm
        else:
            assert record["verdict"] == "UNKNOWN"
            assert abs(record["delta_r"]) < edge


def test_second_generation_still_mutates_one_field_and_keeps_the_holdout_shut(tmp_path):
    summary = run_fixture_lab(tmp_path, generations=2)
    assert summary["holdout_open_count"] == 1
    first = json.loads((tmp_path / "generation-000.json").read_text(encoding="utf-8"))
    second = json.loads((tmp_path / "generation-001.json").read_text(encoding="utf-8"))
    assert first["sealed_holdout_accessed"] is False
    assert second["sealed_holdout_accessed"] is False
    assert second["search_partition_reused"] is True
    assert "holdout-001" not in (tmp_path / "generation-001.json").read_text(encoding="utf-8")
    for record in second["candidates"]:
        assert record["fields_changed"] == [record["field"]]
        assert len(record["lineage"]) == 2


def test_sources_do_not_import_broker_or_model_clients():
    banned = ("alpaca", "jev", "aat_v1", "aat_v2", "urllib", "socket", "http", "requests", "massive")
    for path in (MODULE, SCRIPT):
        for name in _imports(path):
            lowered = name.lower()
            assert not any(part in lowered for part in banned), name


def test_default_run_seeds_three_generations_and_opens_holdout_once(tmp_path, monkeypatch):
    def _network(*_args, **_kwargs):
        raise AssertionError("network")

    monkeypatch.setattr(socket, "create_connection", _network)
    summary = run_fixture_lab(tmp_path)
    assert summary["generations"] == 3
    assert summary["holdout_open_count"] == 1
    assert summary["promoted_to_paper_pilot"] is False
    assert summary["execution_authority"] == "ABSENT"
    assert summary["aat_v1_holdout_consumed"] is False
    kept = [row["kept_candidate"] for row in summary["search_lineage"]]
    assert kept == [
        "g0-peak_retention-+0.1",
        "g1-peak_retention-+0.1",
        "g2-peak_retention-+0.1",
    ]
    assert summary["search_lineage"][1]["seeded_from"] == "g0-peak_retention-+0.1"
    assert summary["search_lineage"][2]["seeded_from"] == "g1-peak_retention-+0.1"
    receipts = [
        json.loads((tmp_path / f"generation-{index:03d}.json").read_text(encoding="utf-8"))
        for index in range(3)
    ]
    assert receipts[1]["parent_parameter_identity"] == receipts[0]["next_search_parent_identity"]
    assert receipts[2]["parent_parameter_identity"] == receipts[1]["next_search_parent_identity"]
    assert receipts[1]["search_partition_reused"] is True
    assert receipts[2]["search_partition_reused"] is True
    assert receipts[2]["parent_lineage"] == [
        {"field": "peak_retention", "value": 0.75},
        {"field": "peak_retention", "value": 0.85},
    ]
    for receipt in receipts:
        assert receipt["sealed_holdout_accessed"] is False
        assert receipt["execution_authority"] == "ABSENT"
        assert receipt["promoted_to_paper_pilot"] is False
        assert "holdout-001" not in receipt["readable"]
        assert "Parent selection mean R" in receipt["readable"]
        for record in receipt["candidates"]:
            assert record["fields_changed"] == [record["field"]]
    holdout = json.loads((tmp_path / "holdout-evaluation.json").read_text(encoding="utf-8"))
    by_id = {record["candidate_id"]: record for record in holdout["candidates"]}
    assert by_id["g0-peak_retention-+0.1"]["verdict"] == "FAIL"
    assert by_id["g2-peak_retention-+0.1"]["verdict"] == "FAIL"
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert report == summary["report_text"]
    assert "Execution authority: ABSENT" in report
    assert "Promoted to paper pilot: false" in report
    assert "Search lineage" in report
    assert "## Holdout" in report
    assert "harmful on the sealed holdout" in report
    assert "g1-peak_retention-+0.1" in report


def test_cli_rejects_live_and_authority_and_writes_receipts(tmp_path, capsys):
    script = _script()
    assert script.main(["LIVE", "--out", str(tmp_path)]) == 2
    assert script.main(["--authority", "LIVE", "--out", str(tmp_path)]) == 2
    assert script.main(["--authority", "PAPER", "--out", str(tmp_path / "paper")]) == 2
    assert script.main(["--out", str(tmp_path), "--generations", "0"]) == 2
    assert list(tmp_path.iterdir()) == []
    assert script.main(["--out", str(tmp_path)]) == 0
    assert (tmp_path / "generation-000.json").is_file()
    assert (tmp_path / "generation-002.json").is_file()
    assert (tmp_path / "holdout-evaluation.json").is_file()
    assert (tmp_path / "summary.json").is_file()
    assert (tmp_path / "report.md").is_file()
    stdout = capsys.readouterr().out
    assert stdout == (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "Execution authority: ABSENT" in stdout
    payload = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert payload["execution_authority"] == "ABSENT"
    assert payload["generations"] == 3
    assert payload["promoted_to_paper_pilot"] is False
    assert "report_text" not in payload
    assert script.main(["--out", str(tmp_path)]) == 2


def test_custom_policy_can_be_passed_without_changing_the_precommitted_object():
    strict = GatePolicy(min_closed_episodes=2, improvement_floor_r=1.0)
    failed, reason = judge_search(
        SliceMetrics(2, 0.2, 0.4, 0.0, ("a", "b")),
        SliceMetrics(2, 0.0, 0.0, 0.0, ("a", "b")),
        strict,
    )
    assert (failed, reason) == ("FAIL", "DOES_NOT_BEAT_PARENT")
    assert PRECOMMITTED_GATES.improvement_floor_r == 0.05
