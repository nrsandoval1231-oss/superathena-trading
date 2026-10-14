"""Fail-closed Ollama AAT-V2 TRAINING runner.

Reads the frozen macro-only V2 TRAINING plan and a real opportunity index /
macro snapshot. Defaults to a tiny dry-run smoke against the desktop
``qwen3.5:9b`` identity. Recommended live TRAINING is the dual-Actor plan:
stratified 1,000-opportunity volume on ``qwen2.5:7b`` plus a 100-opportunity
gold slice on ``qwen2.5:14b``. Those runs require the matching authorization
artifact *and* either ``--authorize-volume-training`` (7b volume subsample)
or ``--authorize-runpod-training`` (14b gold). Desktop 9b still uses
``--authorize-local-training``. None of those flags rewrite the Terra
protocol, raise ``execution_authority`` above ``ABSENT``, or consume a
holdout. The frozen 16,705-opportunity / 116,935-call plan remains plumbing,
not the recommended next step.

Live HTTP is a separate opt-in (``allow_live=True``). Non-loopback
``base_url`` is allowed for the RunPod 14b gold identity and the volume 7b
identity (pod IP, HTTPS proxy, or an SSH tunnel to loopback). Tests inject a
mocked transport and never contact DeepSeek, RunPod, or Ollama.
"""
from __future__ import annotations

import json
import threading
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from ..athena_adapter.contracts import canonical_hash
from ..exogenous import feature_keys
from .arms import ACTOR_ARMS, B_MEMORYLESS, C_NAIVE_MEMORY, D_ATHENA, E_DELIBERATION
from .assignment import AssignmentError, filter_opportunities, partition_for
from .deliberation import (
    DELIBERATION_OUTPUT_TOKENS,
    DELIBERATION_TURN_ROLES,
    DELIBERATION_TURNS,
    DeliberationError,
    load_e_arm_amendment,
)
from .identity import TERRA_PROTOCOL_HASH, IdentityError
from .ollama_identity import (
    AUTHORIZATION_STATUS,
    CLI_AUTHORIZATION_FLAG,
    COMMITTED_AUTHORIZATION_PATH,
    COMMITTED_IDENTITY_PATH,
    COMMITTED_RUNPOD_AUTHORIZATION_PATH,
    COMMITTED_VOLUME_AUTHORIZATION_PATH,
    DEFAULT_MODEL_ID,
    GOLD_SUBSAMPLE_OPPORTUNITIES,
    IDENTITY_STATUS,
    RUNPOD_CLI_AUTHORIZATION_FLAG,
    RUNPOD_IDENTITY_STATUS,
    VOLUME_CLI_AUTHORIZATION_FLAG,
    VOLUME_IDENTITY_STATUS,
    VOLUME_SUBSAMPLE_OPPORTUNITIES,
    AuthorizationError,
    allows_remote_ollama,
    assert_full_run_authorized,
    identity_digest,
    is_runpod_identity,
    is_volume_identity,
    load_committed_ollama_training_authorization,
    load_committed_ollama_training_identity,
)
from .ollama_transport import (
    OllamaTransportError,
    Transport,
    assistant_content,
    build_ollama_payload,
    is_loopback_base_url,
    live_ollama_transport,
    ollama_chat_url,
    payload_turn,
    read_decision,
    read_usage,
    reject_snippet,
    request_hash,
    transport_host_scope,
)
from .packet import build_packet, packet_hash
from .training_subsample import (
    GOLD_KIND,
    VOLUME_KIND,
    SubsampleError,
    load_subsample_receipt,
    load_training_subsample_plan,
    COMMITTED_SUBSAMPLE_PLAN_PATH,
    select_opportunities_for_receipt,
    verify_committed_subsample,
    verify_opportunity_index_receipt,
)

TRAINING_PLAN_SCHEMA = "athena-aat-v2-training-plan-v2"
PROTOCOL_SCHEMA = "athena-aat-v2-registered-protocol-v1"
ASSIGNMENT_SCHEMA = "athena-aat-v2-dataset-assignment-v1"
RUN_SCHEMA = "athena-aat-v2-ollama-local-training-v1"
FIXTURE_SCHEMA = "athena-aat-v2-ollama-qwen-training-fixture-v1"
CHECKPOINT_SCHEMA = "athena-aat-v2-ollama-local-training-checkpoint-v1"

SMOKE_STATUS = "LOCAL_TRAINING_SMOKE"
IN_SAMPLE_STATUS = "LOCAL_TRAINING_IN_SAMPLE"
INCOMPLETE_STATUS = "LOCAL_TRAINING_INCOMPLETE"

DEFAULT_SMOKE_LIMIT = 1
SINGLE_CALL_OUTPUT_TOKENS = 256
DEFAULT_ACTOR_ARMS = (B_MEMORYLESS, C_NAIVE_MEMORY, D_ATHENA)
CALLS_PER_OPPORTUNITY = len(DEFAULT_ACTOR_ARMS) + DELIBERATION_TURNS
FROZEN_ROW_COUNT = 16705
FROZEN_PLANNED_CALLS = 116935
DEFAULT_MAX_CONCURRENT_CALLS = 1
MAX_CONCURRENT_CALLS_CEILING = 4

_FORBIDDEN_PATH_TOKENS = ("holdout", "sealed")
_PROTECTED_ARTIFACTS = (
    "aat_v2_registered_protocol_v1.json",
    "aat_v2_claim_contract_v1.json",
    "aat_consumed_holdouts_v1.json",
    "aat_v2_e_arm_compact_schema_amendment_v1.json",
    "aat_v2_deepseek_flash_actor_identity_v1.json",
    "aat_v2_actor_identity_v1.json",
    "aat_v2_ollama_qwen_actor_identity_v1.json",
    "aat_v2_ollama_local_training_authorization_v1.json",
    "aat_v2_ollama_qwen_14b_runpod_actor_identity_v1.json",
    "aat_v2_ollama_runpod_training_authorization_v1.json",
    "aat_v2_ollama_qwen_7b_volume_actor_identity_v1.json",
    "aat_v2_ollama_volume_training_authorization_v1.json",
    "aat_v2_training_subsample_plan_v1.json",
    "aat_v2_dataset_assignment_v1.json",
    "aat_v2_training_plan_v2.json",
)


class OllamaTrainingError(ValueError):
    """Local Ollama TRAINING cannot proceed safely."""

    def __init__(
        self,
        message: str,
        *,
        live_calls: bool = False,
        authorize_local_training: bool = False,
        completed_calls: int = 0,
        attempted_calls: int = 0,
        status: str = SMOKE_STATUS,
    ) -> None:
        super().__init__(message)
        self.live_calls = live_calls
        self.authorize_local_training = authorize_local_training
        self.completed_calls = completed_calls
        self.attempted_calls = attempted_calls
        self.status = status


def load_macro_only_training_plan(path: str | Path) -> dict[str, Any]:
    """Load the corrected dry-run TRAINING plan. The v1 undercount is refused."""
    payload = _load_json(path)
    if payload.get("schema_version") != TRAINING_PLAN_SCHEMA:
        raise OllamaTrainingError(
            "Ollama TRAINING requires the corrected v2 TRAINING plan; "
            "the 66,820-call v1 estimate is superseded"
        )
    _require_bound_hash(payload, "plan_hash")
    _assert_absent_authority(payload)
    if (
        payload.get("dry_run") is not True
        or payload.get("execution_authorized") is not False
        or payload.get("claim_authorized") is not False
        or payload.get("partition") != "TRAINING"
        or payload.get("planned_calls") != FROZEN_PLANNED_CALLS
        or payload.get("row_count") != FROZEN_ROW_COUNT
        or payload.get("protocol_hash") != TERRA_PROTOCOL_HASH
    ):
        raise OllamaTrainingError("TRAINING plan is not the frozen non-authorizing v2 plan")
    return payload


def load_registered_v2_protocol(path: str | Path) -> dict[str, Any]:
    """Consult the registered Terra protocol without rewriting it."""
    payload = _load_json(path)
    protocol = payload.get("protocol")
    if (
        payload.get("schema_version") != PROTOCOL_SCHEMA
        or not isinstance(protocol, Mapping)
        or protocol.get("registration_status") != "REGISTERED_NOT_AUTHORIZED"
        or protocol.get("claim_authorized") is not False
        or payload.get("protocol_hash") != TERRA_PROTOCOL_HASH
    ):
        raise OllamaTrainingError("V2 protocol is not REGISTERED_NOT_AUTHORIZED Terra")
    _require_bound_hash(payload, "protocol_hash")
    _assert_absent_authority(payload)
    _assert_absent_authority(protocol)
    actor = protocol.get("actor_identity")
    if not isinstance(actor, Mapping) or actor.get("provider") != "openai":
        raise OllamaTrainingError(
            "registered Actor is not the Terra identity; refusing a silent swap"
        )
    return payload


def load_training_assignment(path: str | Path) -> dict[str, Any]:
    payload = _load_json(path)
    if payload.get("schema_version") != ASSIGNMENT_SCHEMA:
        raise OllamaTrainingError("dataset assignment schema is unusable")
    _require_bound_hash(payload, "assignment_hash")
    _assert_absent_authority(payload)
    return payload


def load_training_opportunities(path: str | Path) -> tuple[dict[str, Any], ...]:
    """JSONL opportunity index with price features. Holdout paths are forbidden."""
    target = Path(path)
    _forbid_holdout_path(target)
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise OllamaTrainingError("opportunity index is unreadable") from exc
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise OllamaTrainingError(f"opportunity {number} is not JSON") from exc
        if not isinstance(raw, dict):
            raise OllamaTrainingError(f"opportunity {number} is not an object")
        identifier = raw.get("opportunity_id")
        symbol = raw.get("symbol")
        features = raw.get("features")
        if not isinstance(identifier, str) or not identifier.strip():
            raise OllamaTrainingError(f"opportunity {number} is missing opportunity_id")
        if any(token in identifier.lower() for token in _FORBIDDEN_PATH_TOKENS):
            raise OllamaTrainingError("holdout identifiers are forbidden")
        if not isinstance(symbol, str) or not symbol.strip():
            raise OllamaTrainingError(f"opportunity {number} is missing symbol")
        if not isinstance(features, Mapping):
            raise OllamaTrainingError(f"opportunity {number} is missing features")
        if identifier in seen:
            raise OllamaTrainingError(f"duplicate opportunity {identifier}")
        seen.add(identifier)
        rows.append({
            "opportunity_id": identifier,
            "symbol": symbol,
            "decision_at": raw.get("decision_at"),
            "features": dict(features),
        })
    if not rows:
        raise OllamaTrainingError("opportunity index is empty")
    return tuple(rows)


def load_training_snapshot_rows(path: str | Path) -> dict[str, dict[str, Any]]:
    """JSONL exogenous snapshot keyed by opportunity_id."""
    target = Path(path)
    _forbid_holdout_path(target)
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise OllamaTrainingError("snapshot is unreadable") from exc
    expected = set(feature_keys())
    rows: dict[str, dict[str, Any]] = {}
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise OllamaTrainingError(f"snapshot row {number} is not JSON") from exc
        if not isinstance(raw, dict):
            raise OllamaTrainingError(f"snapshot row {number} is not an object")
        identifier = raw.get("opportunity_id")
        features = raw.get("features")
        if not isinstance(identifier, str) or not identifier.strip():
            raise OllamaTrainingError(f"snapshot row {number} is missing opportunity_id")
        if identifier in rows:
            raise OllamaTrainingError(f"duplicate snapshot opportunity {identifier}")
        if not isinstance(features, Mapping) or set(features) != expected:
            raise OllamaTrainingError(f"snapshot row {identifier} has drifted exogenous keys")
        rows[identifier] = dict(features)
    if not rows:
        raise OllamaTrainingError("snapshot is empty")
    return rows


def arm_sequence(*, include_deliberation: bool = True) -> tuple[dict[str, Any], ...]:
    items: list[dict[str, Any]] = [{"arm": arm, "turn": None} for arm in DEFAULT_ACTOR_ARMS]
    if include_deliberation:
        items.extend({"arm": E_DELIBERATION, "turn": role} for role in DELIBERATION_TURN_ROLES)
    for item in items:
        if item["arm"] not in ACTOR_ARMS:
            raise OllamaTrainingError(f"TRAINING cannot call arm {item['arm']}")
    return tuple(items)


def fixture_transport(
    fixture_path: str | Path, *, model_id: str | None = None,
) -> Transport:
    envelope = _load_training_fixture(fixture_path, expected_model_id=model_id)
    expected_model = envelope["model_id"]

    def _replay(payload: Mapping[str, Any]) -> Mapping[str, Any]:
        if payload.get("model") != expected_model:
            raise OllamaTrainingError("fixture transport received a non-matching model payload")
        if payload.get("think") is not False:
            raise OllamaTrainingError("fixture transport requires thinking disabled")
        turn = payload_turn(payload)
        if turn is None:
            return dict(envelope["response"])
        replies = envelope.get("deliberation_responses")
        if not isinstance(replies, Mapping) or turn not in replies:
            raise OllamaTrainingError("fixture lacks a compact E-arm turn reply")
        reply = replies[turn]
        if not isinstance(reply, Mapping):
            raise OllamaTrainingError("fixture E-arm turn reply is unusable")
        return dict(reply)

    return _replay


def run_ollama_local_training(
    *,
    training_plan_path: str | Path,
    protocol_path: str | Path,
    assignment_path: str | Path,
    opportunity_index_path: str | Path,
    snapshot_path: str | Path,
    amendment_path: str | Path,
    identity_path: str | Path | None = None,
    authorization_path: str | Path | None = None,
    opportunity_receipt_path: str | Path | None = None,
    snapshot_receipt_path: str | Path | None = None,
    subsample_receipt_path: str | Path | None = None,
    output_dir: str | Path,
    limit_opportunities: int | None = DEFAULT_SMOKE_LIMIT,
    authorize_local_training: bool = False,
    authorize_runpod_training: bool = False,
    authorize_volume_training: bool = False,
    allow_live: bool = False,
    transport: Transport | None = None,
    model_id: str | None = None,
    include_deliberation: bool = True,
    resume: bool = False,
    base_url: str = "http://127.0.0.1:11434",
    max_concurrent_calls: int = DEFAULT_MAX_CONCURRENT_CALLS,
) -> dict[str, Any]:
    """Run smoke or authorized in-sample Ollama TRAINING. Never touches holdout."""
    plan = load_macro_only_training_plan(training_plan_path)
    protocol = load_registered_v2_protocol(protocol_path)
    assignment = load_training_assignment(assignment_path)
    if assignment.get("assignment_hash") != protocol["protocol"]["assignment_hash"]:
        raise OllamaTrainingError("assignment does not match the registered protocol")
    identity_file = COMMITTED_IDENTITY_PATH if identity_path is None else identity_path
    try:
        identity = load_committed_ollama_training_identity(
            identity_file, protocol_path=protocol_path, expected_model_id=model_id,
        )
        if authorization_path is None:
            if is_volume_identity(identity):
                authorization_file = COMMITTED_VOLUME_AUTHORIZATION_PATH
            elif is_runpod_identity(identity):
                authorization_file = COMMITTED_RUNPOD_AUTHORIZATION_PATH
            else:
                authorization_file = COMMITTED_AUTHORIZATION_PATH
        else:
            authorization_file = authorization_path
        authorization = load_committed_ollama_training_authorization(
            authorization_file, identity=identity, protocol_path=protocol_path,
        )
    except (IdentityError, AuthorizationError) as exc:
        raise OllamaTrainingError(str(exc)) from exc
    actor_id = identity_digest(identity)
    runpod = is_runpod_identity(identity)
    volume = is_volume_identity(identity)
    _assert_base_url_matches_identity(identity, base_url)
    if not isinstance(max_concurrent_calls, int) or max_concurrent_calls < 1:
        raise OllamaTrainingError("max-concurrent-calls must be a positive integer")
    if max_concurrent_calls > MAX_CONCURRENT_CALLS_CEILING:
        raise OllamaTrainingError(
            "max-concurrent-calls cannot exceed 4; Ollama on one GPU serializes "
            "inference and Semaphore-64-style blasts are refused"
        )
    try:
        load_e_arm_amendment(amendment_path, protocol_path=protocol_path)
    except DeliberationError as exc:
        raise OllamaTrainingError(str(exc)) from exc

    volume_plan = volume and (
        limit_opportunities is None
        or limit_opportunities >= VOLUME_SUBSAMPLE_OPPORTUNITIES
    )
    full_plan = limit_opportunities is None and not volume
    using_auth_flag = (
        authorize_local_training or authorize_runpod_training or authorize_volume_training
    )
    if full_plan or volume_plan or using_auth_flag:
        try:
            assert_full_run_authorized(
                authorization=authorization,
                authorize_local_training=authorize_local_training,
                authorize_runpod_training=authorize_runpod_training,
                authorize_volume_training=authorize_volume_training,
            )
        except AuthorizationError as exc:
            raise OllamaTrainingError(str(exc)) from exc
    if limit_opportunities is not None and limit_opportunities < 1:
        raise OllamaTrainingError("limit-opportunities must be a positive integer")

    opportunities = _training_partition(
        load_training_opportunities(opportunity_index_path), assignment,
    )
    snapshot_rows = load_training_snapshot_rows(snapshot_path)
    subsample_receipt = None
    if full_plan and subsample_receipt_path is not None:
        raise OllamaTrainingError(
            "full 16,705-opportunity plan cannot mix a volume/gold subsample receipt"
        )
    if volume_plan and subsample_receipt_path is None:
        raise OllamaTrainingError(
            "volume subsample TRAINING requires a hashed subsample receipt; "
            "taking the first 1,000 index rows is not the stratified sample"
        )
    if subsample_receipt_path is not None:
        try:
            subsample_receipt = load_subsample_receipt(subsample_receipt_path)
        except SubsampleError as exc:
            raise OllamaTrainingError(str(exc)) from exc
        expected_kind = VOLUME_KIND if volume else GOLD_KIND if runpod else None
        if expected_kind is None:
            raise OllamaTrainingError(
                "desktop qwen3.5:9b identity does not consume a volume/gold subsample receipt"
            )
        if subsample_receipt.get("subsample_kind") != expected_kind:
            raise OllamaTrainingError(
                "subsample receipt kind does not match this Actor: "
                f"volume 7b requires {VOLUME_KIND}, gold 14b requires {GOLD_KIND}"
            )
        try:
            committed_plan = load_training_subsample_plan(COMMITTED_SUBSAMPLE_PLAN_PATH)
            if opportunity_receipt_path is None:
                raise SubsampleError("subsample runs require the frozen opportunity receipt")
            verify_opportunity_index_receipt(
                opportunity_index_path, opportunity_receipt_path,
                expected_hash=plan["dataset_hash"],
            )
            verify_committed_subsample(
                subsample_receipt, opportunities, assignment, plan=committed_plan,
            )
        except SubsampleError as exc:
            raise OllamaTrainingError(str(exc)) from exc
        if volume_plan and subsample_receipt.get("target_count") != VOLUME_SUBSAMPLE_OPPORTUNITIES:
            raise OllamaTrainingError(
                "volume subsample receipt must pin the documented 1,000-opportunity sample"
            )
        gold_plan = (
            runpod
            and subsample_receipt.get("subsample_kind") == GOLD_KIND
            and (
                limit_opportunities is None
                or limit_opportunities >= GOLD_SUBSAMPLE_OPPORTUNITIES
            )
        )
        if gold_plan and subsample_receipt.get("target_count") != GOLD_SUBSAMPLE_OPPORTUNITIES:
            raise OllamaTrainingError(
                "gold subsample receipt must pin the documented 100-opportunity slice"
            )
        try:
            selected = select_opportunities_for_receipt(
                opportunities, subsample_receipt, limit=limit_opportunities,
            )
        except SubsampleError as exc:
            raise OllamaTrainingError(str(exc)) from exc
    elif full_plan:
        selected = opportunities
    else:
        selected = opportunities[:limit_opportunities]
    if not selected:
        raise OllamaTrainingError("no TRAINING opportunities selected")
    if full_plan:
        if len(opportunities) != FROZEN_ROW_COUNT:
            raise OllamaTrainingError(
                "full local TRAINING requires the frozen 16,705-opportunity index"
            )
        _assert_full_plan_receipts(
            plan,
            opportunity_receipt_path=opportunity_receipt_path,
            snapshot_receipt_path=snapshot_receipt_path,
            opportunity_count=len(opportunities),
        )
    for row in selected:
        if row["opportunity_id"] not in snapshot_rows:
            raise OllamaTrainingError(
                f"snapshot is missing opportunity {row['opportunity_id']}"
            )

    arms = arm_sequence(include_deliberation=include_deliberation)
    planned_calls = len(selected) * len(arms)
    sender = _resolve_transport(transport=transport, allow_live=allow_live, base_url=base_url)
    live_calls = allow_live and transport is None
    host_scope = transport_host_scope(base_url)
    status = IN_SAMPLE_STATUS if using_auth_flag else SMOKE_STATUS
    if volume:
        actor_status = VOLUME_IDENTITY_STATUS
        auth_flag = VOLUME_CLI_AUTHORIZATION_FLAG
    elif runpod:
        actor_status = RUNPOD_IDENTITY_STATUS
        auth_flag = RUNPOD_CLI_AUTHORIZATION_FLAG
    else:
        actor_status = IDENTITY_STATUS
        auth_flag = CLI_AUTHORIZATION_FLAG

    output = Path(output_dir)
    _forbid_holdout_path(output)
    ledger_path = output / "ledger.jsonl"
    checkpoint_path = output / "checkpoint.json"
    receipt_path = output / "receipt.json"
    if receipt_path.exists() and not resume:
        raise OllamaTrainingError("refusing to overwrite an existing TRAINING receipt")
    output.mkdir(parents=True, exist_ok=True)

    records = _load_ledger(ledger_path, actor_id=actor_id, resume=resume)
    completed = {(row["opportunity_id"], row["arm"], row["turn"]) for row in records}
    ledger_by_key = {
        (row["opportunity_id"], row["arm"], row["turn"]): row for row in records
    }
    total_input = sum(int(row["input_tokens"]) for row in records)
    total_output = sum(int(row["output_tokens"]) for row in records)
    attempted_calls = len(records)
    estimated_rows = sum(row.get("usage_source") == "BYTE_PROXY_ESTIMATE" for row in records)
    lock = threading.Lock()

    def _process_opportunity(index: int, opportunity: Mapping[str, Any]) -> None:
        nonlocal total_input, total_output, attempted_calls, estimated_rows
        prior_turns: list[dict[str, Any]] = []
        packet = _opportunity_packet(opportunity, snapshot_rows, actor_id)
        hashed = packet_hash(packet)
        for item in arms:
            key = (opportunity["opportunity_id"], item["arm"], item["turn"])
            if key in completed:
                existing = ledger_by_key.get(key)
                if (
                    item["arm"] == E_DELIBERATION
                    and existing
                    and existing.get("accepted")
                    and existing.get("decision")
                ):
                    prior_turns.append(existing["decision"])
                continue
            priors = tuple(prior_turns) if item["arm"] == E_DELIBERATION else ()
            max_output_tokens = (
                DELIBERATION_OUTPUT_TOKENS if item["arm"] == E_DELIBERATION
                else SINGLE_CALL_OUTPUT_TOKENS
            )
            payload = build_ollama_payload(
                packet,
                max_output_tokens=max_output_tokens,
                model_id=identity["model_id"],
                arm=item["arm"],
                turn=item["turn"],
                system_prompt=identity["prompt"],
                prior_turns=priors,
            )
            try:
                response = sender(payload)
            except OllamaTransportError as exc:
                with lock:
                    failed_attempts = len(records) + 1
                raise OllamaTrainingError(
                    str(exc),
                    live_calls=live_calls,
                    authorize_local_training=authorize_local_training,
                    completed_calls=len(records),
                    attempted_calls=failed_attempts,
                    status=INCOMPLETE_STATUS,
                ) from exc
            content_tokens_hint = assistant_content(response)
            input_tokens, output_tokens, usage_source = read_usage(
                response, payload=payload, content=content_tokens_hint,
            )
            decision, rejection = read_decision(
                response, model_id=identity["model_id"], turn=item["turn"],
            )
            with lock:
                attempted_calls += 1
                record = {
                    "sequence": attempted_calls,
                    "arm": item["arm"],
                    "turn": item["turn"],
                    "opportunity_id": opportunity["opportunity_id"],
                    "opportunity_index": index,
                    "symbol": opportunity["symbol"],
                    "request_hash": request_hash(payload),
                    "packet_hash": hashed,
                    "accepted": rejection is None,
                    "rejection_reason": rejection,
                    "decision": decision,
                    "raw_content_snippet": None if rejection is None else reject_snippet(response),
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "usage_source": usage_source,
                    "status": status,
                    "execution_authority": "ABSENT",
                    "actor_identity_hash": actor_id,
                    "prior_turn_count": len(priors),
                    "partition": "TRAINING",
                }
                records.append(record)
                total_input += input_tokens
                total_output += output_tokens
                if usage_source == "BYTE_PROXY_ESTIMATE":
                    estimated_rows += 1
                _append_ledger(ledger_path, record)
                _write_checkpoint(
                    checkpoint_path,
                    actor_id=actor_id,
                    plan_hash=plan["plan_hash"],
                    assignment_hash=assignment["assignment_hash"],
                    completed_calls=len(records),
                    last_opportunity_id=str(opportunity["opportunity_id"]),
                    last_arm=item["arm"],
                    last_turn=item["turn"],
                    status=INCOMPLETE_STATUS,
                    authorize_local_training=authorize_local_training,
                    authorize_runpod_training=authorize_runpod_training,
                    authorize_volume_training=authorize_volume_training,
                )
            if item["arm"] == E_DELIBERATION and rejection is None and decision:
                prior_turns.append(decision)

    try:
        if max_concurrent_calls == 1:
            for index, opportunity in enumerate(selected):
                _process_opportunity(index, opportunity)
        else:
            with ThreadPoolExecutor(max_workers=max_concurrent_calls) as pool:
                futures = [
                    pool.submit(_process_opportunity, index, opportunity)
                    for index, opportunity in enumerate(selected)
                ]
                for future in as_completed(futures):
                    future.result()
    except OllamaTrainingError:
        _write_receipt(
            receipt_path,
            _result_body(
                plan=plan, protocol=protocol, identity=identity, authorization=authorization,
                assignment=assignment, selected=selected, records=records, arms=arms,
                planned_calls=planned_calls, total_input=total_input, total_output=total_output,
                estimated_rows=estimated_rows, live_calls=live_calls, allow_live=allow_live,
                authorize_local_training=authorize_local_training,
                authorize_runpod_training=authorize_runpod_training,
                authorize_volume_training=authorize_volume_training,
                full_plan=full_plan, volume_plan=volume_plan,
                include_deliberation=include_deliberation,
                status=INCOMPLETE_STATUS, limit_opportunities=limit_opportunities,
                actor_id=actor_id, actor_status=actor_status, auth_flag=auth_flag,
                host_scope=host_scope, base_url=base_url,
                max_concurrent_calls=max_concurrent_calls, runpod=runpod,
                volume=volume, subsample_receipt=subsample_receipt,
            ),
            resume=True,
        )
        raise

    result_status = status if len(records) == planned_calls else INCOMPLETE_STATUS
    result = _result_body(
        plan=plan, protocol=protocol, identity=identity, authorization=authorization,
        assignment=assignment, selected=selected, records=records, arms=arms,
        planned_calls=planned_calls, total_input=total_input, total_output=total_output,
        estimated_rows=estimated_rows, live_calls=live_calls, allow_live=allow_live,
        authorize_local_training=authorize_local_training,
        authorize_runpod_training=authorize_runpod_training,
        authorize_volume_training=authorize_volume_training,
        full_plan=full_plan, volume_plan=volume_plan,
        include_deliberation=include_deliberation,
        status=result_status, limit_opportunities=limit_opportunities,
        actor_id=actor_id, actor_status=actor_status, auth_flag=auth_flag,
        host_scope=host_scope, base_url=base_url,
        max_concurrent_calls=max_concurrent_calls, runpod=runpod,
        volume=volume, subsample_receipt=subsample_receipt,
    )
    _write_receipt(receipt_path, result, resume=resume or receipt_path.exists())
    if result_status != INCOMPLETE_STATUS:
        _write_checkpoint(
            checkpoint_path,
            actor_id=actor_id,
            plan_hash=plan["plan_hash"],
            assignment_hash=assignment["assignment_hash"],
            completed_calls=len(records),
            last_opportunity_id=selected[-1]["opportunity_id"],
            last_arm=arms[-1]["arm"],
            last_turn=arms[-1]["turn"],
            status=result_status,
            authorize_local_training=authorize_local_training,
            authorize_runpod_training=authorize_runpod_training,
            authorize_volume_training=authorize_volume_training,
        )
    return result


def _training_partition(
    opportunities: Sequence[Mapping[str, Any]], assignment: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    try:
        for row in opportunities:
            partition = partition_for(assignment, str(row["symbol"]))
            if partition != "TRAINING":
                raise OllamaTrainingError(
                    f"refusing {partition} symbol {row['symbol']}; holdout must stay untouched"
                )
        filtered = filter_opportunities(assignment, list(opportunities), partition="TRAINING")
    except AssignmentError as exc:
        raise OllamaTrainingError(str(exc)) from exc
    if len(filtered) != len(opportunities):
        raise OllamaTrainingError("opportunity index is not TRAINING-only")
    return filtered


def _opportunity_packet(
    opportunity: Mapping[str, Any],
    snapshot_rows: Mapping[str, Mapping[str, Any]],
    actor_id: str,
) -> dict[str, Any]:
    return build_packet(
        arm=D_ATHENA,
        opportunity_id=str(opportunity["opportunity_id"]),
        features=dict(opportunity["features"]),
        actor_identity=actor_id,
        exogenous_features=dict(snapshot_rows[str(opportunity["opportunity_id"])]),
        memory=(),
    )


def _resolve_transport(
    *, transport: Transport | None, allow_live: bool, base_url: str,
) -> Transport:
    if transport is not None:
        if allow_live:
            raise OllamaTrainingError("live Ollama calls cannot be mixed with an injected transport")
        return transport
    if not allow_live:
        raise OllamaTrainingError(
            "live Ollama calls are not authorized by the default smoke path; "
            "pass --allow-live-ollama on Nick's desktop or RunPod, or inject a mock transport"
        )
    remote = not is_loopback_base_url(base_url)
    try:
        return live_ollama_transport(base_url=base_url, allow_remote=remote)
    except OllamaTransportError as exc:
        raise OllamaTrainingError(str(exc)) from exc


def _assert_base_url_matches_identity(identity: Mapping[str, Any], base_url: str) -> None:
    """Desktop 9b is loopback-only. Volume 7b and gold 14b may use a remote host."""
    if allows_remote_ollama(identity):
        inference = identity.get("inference")
        if not isinstance(inference, Mapping) or inference.get("base_url_policy") != "explicit_cli":
            raise OllamaTrainingError(
                "remote Ollama identity must declare an explicit CLI base-url policy"
            )
        try:
            ollama_chat_url(base_url, allow_remote=True)
        except OllamaTransportError as exc:
            raise OllamaTrainingError(str(exc)) from exc
        return
    try:
        ollama_chat_url(base_url, allow_remote=False)
    except OllamaTransportError as exc:
        raise OllamaTrainingError(
            "local qwen3.5:9b identity cannot target a non-loopback Ollama host; "
            "use the volume qwen2.5:7b identity or the gold qwen2.5:14b identity"
        ) from exc


def _assert_full_plan_receipts(
    plan: Mapping[str, Any],
    *,
    opportunity_receipt_path: str | Path | None,
    snapshot_receipt_path: str | Path | None,
    opportunity_count: int,
) -> None:
    if opportunity_receipt_path is None or snapshot_receipt_path is None:
        raise OllamaTrainingError(
            "full local TRAINING requires opportunity and snapshot receipts bound to the frozen plan"
        )
    opportunity_receipt = _load_json(opportunity_receipt_path)
    snapshot_receipt = _load_json(snapshot_receipt_path)
    if opportunity_receipt.get("index_hash") != plan.get("dataset_hash"):
        raise OllamaTrainingError("opportunity receipt does not match the frozen TRAINING dataset_hash")
    if snapshot_receipt.get("snapshot_hash") != plan.get("snapshot_hash"):
        raise OllamaTrainingError("snapshot receipt does not match the frozen TRAINING snapshot_hash")
    if opportunity_receipt.get("row_count") != opportunity_count:
        raise OllamaTrainingError("opportunity receipt row_count does not match the index")
    if snapshot_receipt.get("contains_outcomes") is not False:
        raise OllamaTrainingError("snapshot receipt must be outcome-free")
    if opportunity_receipt.get("contains_sealed_holdout") is not False:
        raise OllamaTrainingError("opportunity receipt must not contain sealed holdout")
    _assert_absent_authority(opportunity_receipt)
    _assert_absent_authority(snapshot_receipt)


def _load_training_fixture(
    path: str | Path, *, expected_model_id: str | None = None,
) -> dict[str, Any]:
    payload = _load_json(path)
    model_id = expected_model_id or DEFAULT_MODEL_ID
    if (
        payload.get("schema_version") != FIXTURE_SCHEMA
        or payload.get("model_id") != model_id
        or payload.get("execution_authority") != "ABSENT"
        or not isinstance(payload.get("response"), Mapping)
    ):
        raise OllamaTrainingError("Ollama TRAINING fixture is unusable")
    replies = payload.get("deliberation_responses")
    if replies is not None:
        if not isinstance(replies, Mapping) or set(replies) != set(DELIBERATION_TURN_ROLES):
            raise OllamaTrainingError("Ollama TRAINING fixture E-arm replies are unusable")
        if not all(isinstance(replies[role], Mapping) for role in DELIBERATION_TURN_ROLES):
            raise OllamaTrainingError("Ollama TRAINING fixture E-arm replies are unusable")
    return payload


def _load_ledger(path: Path, *, actor_id: str, resume: bool) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if not resume:
        raise OllamaTrainingError("existing ledger requires --resume")
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for index, record in enumerate(records, start=1):
        if record.get("sequence") != index:
            raise OllamaTrainingError("TRAINING ledger sequence is invalid")
        if record.get("execution_authority") != "ABSENT":
            raise OllamaTrainingError("TRAINING ledger authority must remain ABSENT")
        if record.get("actor_identity_hash") != actor_id:
            raise OllamaTrainingError("TRAINING ledger identity drifted")
        if record.get("partition") != "TRAINING":
            raise OllamaTrainingError("TRAINING ledger is not TRAINING-only")
    return records


def _append_ledger(path: Path, record: Mapping[str, Any]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")


def _write_checkpoint(
    path: Path,
    *,
    actor_id: str,
    plan_hash: str,
    assignment_hash: str,
    completed_calls: int,
    last_opportunity_id: str,
    last_arm: str,
    last_turn: str | None,
    status: str,
    authorize_local_training: bool,
    authorize_runpod_training: bool = False,
    authorize_volume_training: bool = False,
) -> None:
    payload = {
        "schema_version": CHECKPOINT_SCHEMA,
        "status": status,
        "execution_authority": "ABSENT",
        "actor_identity_hash": actor_id,
        "training_plan_hash": plan_hash,
        "assignment_hash": assignment_hash,
        "completed_calls": completed_calls,
        "last_opportunity_id": last_opportunity_id,
        "last_arm": last_arm,
        "last_turn": last_turn,
        "authorize_local_training": authorize_local_training,
        "authorize_runpod_training": authorize_runpod_training,
        "authorize_volume_training": authorize_volume_training,
        "partition": "TRAINING",
        "terra_protocol_not_reused": True,
    }
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _write_receipt(path: Path, result: Mapping[str, Any], *, resume: bool) -> None:
    if path.exists() and not resume:
        raise OllamaTrainingError("refusing to overwrite an existing TRAINING receipt")
    path.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _result_body(
    *,
    plan: Mapping[str, Any],
    protocol: Mapping[str, Any],
    identity: Mapping[str, Any],
    authorization: Mapping[str, Any],
    assignment: Mapping[str, Any],
    selected: Sequence[Mapping[str, Any]],
    records: Sequence[Mapping[str, Any]],
    arms: Sequence[Mapping[str, Any]],
    planned_calls: int,
    total_input: int,
    total_output: int,
    estimated_rows: int,
    live_calls: bool,
    allow_live: bool,
    authorize_local_training: bool,
    authorize_runpod_training: bool,
    authorize_volume_training: bool,
    full_plan: bool,
    volume_plan: bool,
    include_deliberation: bool,
    status: str,
    limit_opportunities: int | None,
    actor_id: str,
    actor_status: str,
    auth_flag: str,
    host_scope: str,
    base_url: str,
    max_concurrent_calls: int,
    runpod: bool,
    volume: bool,
    subsample_receipt: Mapping[str, Any] | None,
) -> dict[str, Any]:
    result = {
        "schema_version": RUN_SCHEMA,
        "status": status,
        "dry_run": not live_calls,
        "execution_authorized": False,
        "claim_authorized": False,
        "sealed_holdout_consumed": False,
        "execution_authority": "ABSENT",
        "registration_status": "REGISTERED_NOT_AUTHORIZED",
        "terra_protocol_not_reused": True,
        "deepseek_identity_not_reused": True,
        "local_9b_identity_not_reused": runpod or volume,
        "runpod_14b_identity_not_reused": volume,
        "runpod_training": runpod,
        "volume_training": volume,
        "volume_plan": volume_plan,
        "candidate_provider": identity["provider"],
        "candidate_model_id": identity["model_id"],
        "actor_identity_status": actor_status,
        "actor_identity_hash": actor_id,
        "authorization_status": AUTHORIZATION_STATUS,
        "authorization_hash": authorization["authorization_hash"],
        "authorization_cli_flag": auth_flag,
        "authorize_local_training": authorize_local_training,
        "authorize_runpod_training": authorize_runpod_training,
        "authorize_volume_training": authorize_volume_training,
        "full_plan": full_plan,
        "protocol_hash": protocol["protocol_hash"],
        "training_plan_hash": plan["plan_hash"],
        "assignment_hash": assignment["assignment_hash"],
        "subsample_hash": None if subsample_receipt is None else subsample_receipt.get("subsample_hash"),
        "subsample_kind": None if subsample_receipt is None else subsample_receipt.get("subsample_kind"),
        "source_document": "docs/AAT_V2_MODEL_EXECUTION_OPTIONS.md",
        "partition": "TRAINING",
        "opportunity_count": len(selected),
        "limit_opportunities": limit_opportunities,
        "planned_calls": planned_calls,
        "frozen_plan_calls": FROZEN_PLANNED_CALLS,
        "request_count": len(records),
        "accepted_count": sum(bool(record["accepted"]) for record in records),
        "rejected_count": sum(not record["accepted"] for record in records),
        "input_tokens": total_input,
        "output_tokens": total_output,
        "estimated_usage_rows": estimated_rows,
        "token_accounting": (
            "OLLAMA_REPORTED counts when prompt_eval_count/eval_count are present; "
            "otherwise utf-8 bytes/4 labeled BYTE_PROXY_ESTIMATE. Ollama tokens are "
            "unpriced. RunPod bills GPU time separately; this is not OpenAI-style "
            "billed usage."
        ),
        "live_calls": live_calls,
        "actor_called": bool(records),
        "allow_live": allow_live,
        "base_url": base_url,
        "transport_host_scope": host_scope,
        "max_concurrent_calls": max_concurrent_calls,
        "concurrency_note": (
            "Default is 1. Optional bounded opportunity-level concurrency is 2-4. "
            "Ollama on one GPU serializes inference; Semaphore-64-style blasts "
            "are refused. Arm E turns stay sequential inside each opportunity."
        ),
        "include_deliberation": include_deliberation,
        "arms": [item["arm"] for item in arms],
        "v2_lessons_bound": False,
        "memory_note": (
            "V2 has no promoted lesson inventory yet; C/D/E packets carry empty "
            "memory. The treatment remains the exogenous macro vector."
        ),
        "records": list(records),
    }
    result["result_hash"] = canonical_hash(
        {key: value for key, value in result.items() if key != "records"}
    )
    return result


def forbid_output_path(path: str | Path) -> Path:
    target = Path(path)
    _forbid_holdout_path(target)
    if target.name.lower() in _PROTECTED_ARTIFACTS:
        raise OllamaTrainingError("refusing to write a registered or consumed artifact")
    return target


def _require_bound_hash(payload: Mapping[str, Any], field: str) -> None:
    body = dict(payload)
    claimed = body.pop(field, None)
    if not isinstance(claimed, str) or claimed != canonical_hash(body):
        raise OllamaTrainingError(f"{field} does not match its contents")


def _assert_absent_authority(payload: Mapping[str, Any]) -> None:
    if payload.get("execution_authority") != "ABSENT":
        raise OllamaTrainingError("execution authority must remain ABSENT")


def _forbid_holdout_path(path: Path) -> None:
    text = str(path).lower()
    if any(token in text for token in _FORBIDDEN_PATH_TOKENS):
        raise OllamaTrainingError("holdout paths are forbidden")


def _load_json(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    _forbid_holdout_path(target)
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OllamaTrainingError("Ollama TRAINING input is unreadable") from exc
    if not isinstance(value, dict):
        raise OllamaTrainingError("Ollama TRAINING input is not an object")
    return value
