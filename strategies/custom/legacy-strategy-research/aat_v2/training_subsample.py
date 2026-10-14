"""Stratified TRAINING subsample for the 7b volume + 14b gold plan.

The frozen macro-only TRAINING index is 16,705 opportunities. That full plan
is no longer the recommended next step. This module pins a reproducible
**symbol-stratified** volume sample (1,000 opportunities) and a gold slice
(100 opportunities) that is a subset of the volume sample.

Opportunity IDs are not committed here: the frozen TRAINING JSONL lives
outside git. ``scripts/draw_aat_v2_training_subsample.py`` draws against that
index, writes hashed receipts, and refuses holdout paths. The committed plan
pins seed, sizes, stratification, and parent hashes so a redraw is visible.

Draw-before-looking: the seed and the TRAINING index fully determine the
sample. Outcomes are not consulted. ``execution_authority`` stays ``ABSENT``.
"""
from __future__ import annotations

import json
import hashlib
import random
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from ..paths import config_file
from typing import Any

from ..athena_adapter.contracts import canonical_hash
from .assignment import AssignmentError, partition_for
from .identity import TERRA_PROTOCOL_HASH
from .ollama_identity import GOLD_SUBSAMPLE_OPPORTUNITIES, VOLUME_SUBSAMPLE_OPPORTUNITIES

SUBSAMPLE_PLAN_SCHEMA = "athena-aat-v2-training-subsample-plan-v1"
SUBSAMPLE_RECEIPT_SCHEMA = "athena-aat-v2-training-subsample-receipt-v1"
VOLUME_KIND = "VOLUME"
GOLD_KIND = "GOLD"
STRATIFICATION = "symbol"
DEFAULT_SEED = 20260916
FROZEN_DATASET_HASH = "179e6f21f583bd40a5afff9acc1bfc7690155def18a1375e5535b9a6ebbe7a9a"
FROZEN_ASSIGNMENT_HASH = "46f25ba0f64c5088add6d37a72752d6fbe156de6c33e8b8d7d4415e160f5e731"

COMMITTED_SUBSAMPLE_PLAN_PATH = config_file("aat_v2_training_subsample_plan_v1.json")

_FORBIDDEN_PATH_TOKENS = ("holdout", "sealed")


class SubsampleError(ValueError):
    """The TRAINING subsample cannot be drawn or verified safely."""


def declared_training_subsample_plan() -> dict[str, Any]:
    """Committed dual-Actor subsample sizes. Does not select opportunity IDs."""
    plan = {
        "schema_version": SUBSAMPLE_PLAN_SCHEMA,
        "seed": DEFAULT_SEED,
        "stratification": STRATIFICATION,
        "volume_count": VOLUME_SUBSAMPLE_OPPORTUNITIES,
        "gold_count": GOLD_SUBSAMPLE_OPPORTUNITIES,
        "gold_is_subset_of_volume": True,
        "parent_partition": "TRAINING",
        "parent_dataset_hash": FROZEN_DATASET_HASH,
        "assignment_hash": FROZEN_ASSIGNMENT_HASH,
        "consulted_terra_protocol_hash": TERRA_PROTOCOL_HASH,
        "drawn_from_outcomes": False,
        "drawn_from_exogenous_features": False,
        "authorizes_full_16705_plan": False,
        "execution_authorized": False,
        "claim_authorized": False,
        "execution_authority": "ABSENT",
        "sealed_holdout_consumed": False,
        "source_document": "docs/AAT_V2_MODEL_EXECUTION_OPTIONS.md",
        "notes": (
            "Pins the 8b volume / 14b gold TRAINING subsample. Volume default is "
            f"{VOLUME_SUBSAMPLE_OPPORTUNITIES} opportunities; gold is "
            f"{GOLD_SUBSAMPLE_OPPORTUNITIES} overlapping opportunities drawn from "
            "that volume sample. Opportunity IDs are produced by "
            "scripts/draw_aat_v2_training_subsample.py against the frozen "
            "TRAINING index. The full 16,705-opportunity plan is no longer the "
            "recommended next step."
        ),
    }
    plan["plan_hash"] = canonical_hash(plan)
    return plan


def load_training_subsample_plan(path: str | Path) -> dict[str, Any]:
    """Load the committed subsample plan. Tamper and holdout paths fail closed."""
    payload = _load_json(path)
    expected = declared_training_subsample_plan()
    body = dict(payload)
    claimed = body.pop("plan_hash", None)
    if payload.get("schema_version") != SUBSAMPLE_PLAN_SCHEMA:
        raise SubsampleError("TRAINING subsample plan schema is unusable")
    if not isinstance(claimed, str) or claimed != canonical_hash(body):
        raise SubsampleError("TRAINING subsample plan_hash does not match its contents")
    if payload.get("plan_hash") != expected["plan_hash"]:
        raise SubsampleError("TRAINING subsample plan drifted from the declared artifact")
    if (
        payload.get("seed") != DEFAULT_SEED
        or payload.get("stratification") != STRATIFICATION
        or payload.get("volume_count") != VOLUME_SUBSAMPLE_OPPORTUNITIES
        or payload.get("gold_count") != GOLD_SUBSAMPLE_OPPORTUNITIES
        or payload.get("gold_is_subset_of_volume") is not True
        or payload.get("parent_partition") != "TRAINING"
        or payload.get("parent_dataset_hash") != FROZEN_DATASET_HASH
        or payload.get("assignment_hash") != FROZEN_ASSIGNMENT_HASH
        or payload.get("consulted_terra_protocol_hash") != TERRA_PROTOCOL_HASH
        or payload.get("drawn_from_outcomes") is not False
        or payload.get("authorizes_full_16705_plan") is not False
        or payload.get("execution_authority") != "ABSENT"
        or payload.get("sealed_holdout_consumed") is not False
    ):
        raise SubsampleError("TRAINING subsample plan must stay fail-closed")
    return payload


def draw_training_subsample(
    opportunities: Sequence[Mapping[str, Any]],
    *,
    plan: Mapping[str, Any],
    assignment: Mapping[str, Any],
    parent_dataset_hash: str,
    volume_count: int | None = None,
    gold_count: int | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    """Return hashed volume and gold receipts plus selected rows.

    ``volume_count`` / ``gold_count`` / ``seed`` override the plan only for
    tests. The committed draw uses the plan values unchanged.
    """
    _assert_plan_axes(plan)
    if assignment.get("assignment_hash") != plan.get("assignment_hash"):
        raise SubsampleError("assignment does not match the subsample plan")
    if parent_dataset_hash != plan.get("parent_dataset_hash"):
        raise SubsampleError("opportunity receipt does not match the frozen TRAINING dataset_hash")
    volume_n = VOLUME_SUBSAMPLE_OPPORTUNITIES if volume_count is None else volume_count
    gold_n = GOLD_SUBSAMPLE_OPPORTUNITIES if gold_count is None else gold_count
    draw_seed = DEFAULT_SEED if seed is None else seed
    if not isinstance(volume_n, int) or isinstance(volume_n, bool) or volume_n < 1:
        raise SubsampleError("volume_count must be a positive integer")
    if not isinstance(gold_n, int) or isinstance(gold_n, bool) or gold_n < 1:
        raise SubsampleError("gold_count must be a positive integer")
    if gold_n > volume_n:
        raise SubsampleError("gold slice cannot be larger than the volume sample")
    if not isinstance(draw_seed, int) or isinstance(draw_seed, bool):
        raise SubsampleError("seed must be an integer")
    training = _training_only(opportunities, assignment)
    volume_rows = _stratified_sample(training, count=volume_n, seed=draw_seed)
    gold_rows = _stratified_sample(volume_rows, count=gold_n, seed=draw_seed + 1)
    gold_ids = {row["opportunity_id"] for row in gold_rows}
    if not gold_ids.issubset({row["opportunity_id"] for row in volume_rows}):
        raise SubsampleError("gold slice is not a subset of the volume sample")
    volume_receipt = _receipt(
        kind=VOLUME_KIND,
        plan=plan,
        seed=draw_seed,
        target_count=volume_n,
        rows=volume_rows,
        parent_kind="TRAINING",
        parent_hash=parent_dataset_hash,
    )
    gold_receipt = _receipt(
        kind=GOLD_KIND,
        plan=plan,
        seed=draw_seed + 1,
        target_count=gold_n,
        rows=gold_rows,
        parent_kind=VOLUME_KIND,
        parent_hash=volume_receipt["subsample_hash"],
    )
    return {
        "volume_receipt": volume_receipt,
        "gold_receipt": gold_receipt,
        "volume_rows": volume_rows,
        "gold_rows": gold_rows,
        "execution_authority": "ABSENT",
    }


def load_subsample_receipt(path: str | Path) -> dict[str, Any]:
    """Load a hashed volume or gold subsample receipt."""
    payload = _load_json(path)
    body = dict(payload)
    claimed = body.pop("subsample_hash", None)
    if payload.get("schema_version") != SUBSAMPLE_RECEIPT_SCHEMA:
        raise SubsampleError("TRAINING subsample receipt schema is unusable")
    if not isinstance(claimed, str) or claimed != canonical_hash(body):
        raise SubsampleError("TRAINING subsample_hash does not match its contents")
    if (
        payload.get("execution_authority") != "ABSENT"
        or payload.get("sealed_holdout_consumed") is not False
        or payload.get("drawn_from_outcomes") is not False
        or payload.get("parent_partition") != "TRAINING"
        or payload.get("stratification") != STRATIFICATION
    ):
        raise SubsampleError("TRAINING subsample receipt must stay fail-closed")
    kind = payload.get("subsample_kind")
    if kind not in {VOLUME_KIND, GOLD_KIND}:
        raise SubsampleError("TRAINING subsample kind is unusable")
    ids = payload.get("opportunity_ids")
    if not isinstance(ids, list) or not ids or not all(isinstance(item, str) and item for item in ids):
        raise SubsampleError("TRAINING subsample opportunity_ids are unusable")
    if len(set(ids)) != len(ids):
        raise SubsampleError("TRAINING subsample opportunity_ids are not unique")
    if payload.get("selected_count") != len(ids):
        raise SubsampleError("TRAINING subsample selected_count does not match opportunity_ids")
    target = payload.get("target_count")
    if not isinstance(target, int) or isinstance(target, bool) or target < 1:
        raise SubsampleError("TRAINING subsample target_count is unusable")
    if payload.get("selected_count") != target:
        raise SubsampleError("TRAINING subsample selected_count must equal target_count")
    if kind == GOLD_KIND and payload.get("parent_kind") != VOLUME_KIND:
        raise SubsampleError("gold subsample must name the volume sample as parent")
    if kind == VOLUME_KIND and payload.get("parent_kind") != "TRAINING":
        raise SubsampleError("volume subsample must name TRAINING as parent")
    return payload


def verify_opportunity_index_receipt(
    index_path: str | Path, receipt_path: str | Path, *, expected_hash: str,
) -> dict[str, Any]:
    """Bind the frozen receipt to the exact bytes consumed by the draw or runner."""
    _forbid_holdout_path(Path(index_path))
    receipt = _load_json(receipt_path)
    body = dict(receipt)
    claimed = body.pop("index_hash", None)
    if claimed != canonical_hash(body) or claimed != expected_hash:
        raise SubsampleError("opportunity receipt hash does not match the frozen TRAINING plan")
    try:
        raw = Path(index_path).read_bytes()
        rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    except (OSError, ValueError, UnicodeError) as exc:
        raise SubsampleError("opportunity index is unreadable") from exc
    if (receipt.get("row_count") != len(rows)
            or receipt.get("rows_sha256") != hashlib.sha256(raw).hexdigest()
            or receipt.get("contains_outcomes") is not False
            or receipt.get("contains_sealed_holdout") is not False
            or receipt.get("execution_authority") != "ABSENT"):
        raise SubsampleError("opportunity index does not match its frozen receipt")
    return receipt


def verify_committed_subsample(
    receipt: Mapping[str, Any], opportunities: Sequence[Mapping[str, Any]],
    assignment: Mapping[str, Any], *, plan: Mapping[str, Any],
) -> None:
    """Check the complete deterministic draw, not just self-hashed metadata."""
    kind = receipt["subsample_kind"]
    expected = draw_training_subsample(
        opportunities, plan=plan, assignment=assignment,
        parent_dataset_hash=plan["parent_dataset_hash"],
    )["volume_receipt" if kind == VOLUME_KIND else "gold_receipt"]
    if dict(receipt) != expected:
        raise SubsampleError("subsample receipt does not match the frozen draw plan")


def select_opportunities_for_receipt(
    opportunities: Sequence[Mapping[str, Any]],
    receipt: Mapping[str, Any],
    *,
    limit: int | None = None,
) -> tuple[dict[str, Any], ...]:
    """Return receipt IDs from ``opportunities``, optionally capped by ``limit``."""
    ids = list(receipt.get("opportunity_ids") or ())
    if limit is not None:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise SubsampleError("limit-opportunities must be a positive integer")
        ids = ids[:limit]
    by_id = {}
    for row in opportunities:
        identifier = row.get("opportunity_id")
        if isinstance(identifier, str):
            by_id[identifier] = dict(row)
    missing = [identifier for identifier in ids if identifier not in by_id]
    if missing:
        raise SubsampleError(
            f"subsample receipt names {len(missing)} opportunities missing from the index"
        )
    return tuple(by_id[identifier] for identifier in ids)


def write_subsample_receipt(receipt: Mapping[str, Any], path: str | Path) -> dict[str, Any]:
    target = Path(path)
    _forbid_holdout_path(target)
    if target.exists():
        raise SubsampleError("refusing to overwrite an existing subsample receipt")
    body = dict(receipt)
    claimed = body.pop("subsample_hash", None)
    if claimed != canonical_hash(body):
        raise SubsampleError("subsample hash does not match its contents")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return dict(receipt)


def write_subsample_index(rows: Sequence[Mapping[str, Any]], path: str | Path) -> Path:
    target = Path(path)
    _forbid_holdout_path(target)
    if target.exists():
        raise SubsampleError("refusing to overwrite an existing subsample index")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), sort_keys=True, separators=(",", ":")) + "\n")
    return target


def _assert_plan_axes(plan: Mapping[str, Any]) -> None:
    if (
        plan.get("schema_version") != SUBSAMPLE_PLAN_SCHEMA
        or plan.get("execution_authority") != "ABSENT"
        or plan.get("authorizes_full_16705_plan") is not False
        or plan.get("gold_is_subset_of_volume") is not True
        or plan.get("stratification") != STRATIFICATION
        or plan.get("parent_partition") != "TRAINING"
    ):
        raise SubsampleError("TRAINING subsample plan is not the fail-closed dual-Actor plan")


def _training_only(
    opportunities: Sequence[Mapping[str, Any]], assignment: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in opportunities:
        identifier = row.get("opportunity_id")
        symbol = row.get("symbol")
        if not isinstance(identifier, str) or not identifier.strip():
            raise SubsampleError("opportunity is missing opportunity_id")
        if not isinstance(symbol, str) or not symbol.strip():
            raise SubsampleError(f"opportunity {identifier} is missing symbol")
        if identifier in seen:
            raise SubsampleError(f"duplicate opportunity {identifier}")
        try:
            partition = partition_for(assignment, symbol)
        except AssignmentError as exc:
            raise SubsampleError(str(exc)) from exc
        if partition != "TRAINING":
            raise SubsampleError(
                f"refusing {partition} symbol {symbol}; holdout must stay untouched"
            )
        seen.add(identifier)
        rows.append(dict(row))
    if not rows:
        raise SubsampleError("opportunity index is empty")
    return tuple(rows)


def _stratified_sample(
    rows: Sequence[Mapping[str, Any]], *, count: int, seed: int,
) -> tuple[dict[str, Any], ...]:
    if count > len(rows):
        raise SubsampleError(
            f"subsample target {count} exceeds available TRAINING opportunities {len(rows)}"
        )
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_symbol[str(row["symbol"])].append(dict(row))
    for symbol, group in by_symbol.items():
        group.sort(key=lambda item: str(item["opportunity_id"]))
        by_symbol[symbol] = group
    sizes = {symbol: len(group) for symbol, group in by_symbol.items()}
    allocated = _largest_remainder_counts(sizes, count)
    rng = random.Random(seed)
    selected: list[dict[str, Any]] = []
    for symbol in sorted(by_symbol):
        pool = by_symbol[symbol]
        take = allocated[symbol]
        if take == 0:
            continue
        if take == len(pool):
            chosen = list(pool)
        else:
            chosen = rng.sample(pool, take)
            chosen.sort(key=lambda item: str(item["opportunity_id"]))
        selected.extend(chosen)
    selected.sort(key=lambda item: (str(item["symbol"]), str(item["opportunity_id"])))
    if len(selected) != count:
        raise SubsampleError("stratified subsample did not land on the target count")
    return tuple(selected)


def _largest_remainder_counts(sizes: Mapping[str, int], target: int) -> dict[str, int]:
    total = sum(sizes.values())
    if target > total:
        raise SubsampleError("subsample target exceeds available TRAINING opportunities")
    raw = {symbol: target * size / total for symbol, size in sizes.items()}
    floors = {symbol: min(sizes[symbol], int(raw[symbol])) for symbol in sizes}
    assigned = sum(floors.values())
    remainders = sorted(
        (
            (raw[symbol] - int(raw[symbol]), symbol)
            for symbol in sizes
            if floors[symbol] < sizes[symbol]
        ),
        key=lambda item: (-item[0], item[1]),
    )
    leftover = target - assigned
    for _, symbol in remainders:
        if leftover <= 0:
            break
        floors[symbol] += 1
        leftover -= 1
    if leftover != 0 or sum(floors.values()) != target:
        raise SubsampleError("stratified allocation could not fill the target count")
    return floors


def _receipt(
    *,
    kind: str,
    plan: Mapping[str, Any],
    seed: int,
    target_count: int,
    rows: Sequence[Mapping[str, Any]],
    parent_kind: str,
    parent_hash: str,
) -> dict[str, Any]:
    ids = [str(row["opportunity_id"]) for row in rows]
    receipt = {
        "schema_version": SUBSAMPLE_RECEIPT_SCHEMA,
        "subsample_kind": kind,
        "parent_kind": parent_kind,
        "parent_hash": parent_hash,
        "parent_partition": "TRAINING",
        "plan_hash": plan.get("plan_hash"),
        "seed": seed,
        "stratification": STRATIFICATION,
        "target_count": target_count,
        "selected_count": len(ids),
        "opportunity_ids": ids,
        "assignment_hash": plan.get("assignment_hash"),
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
    receipt["subsample_hash"] = canonical_hash(receipt)
    return receipt


def _forbid_holdout_path(path: Path) -> None:
    text = str(path).lower()
    if any(token in text for token in _FORBIDDEN_PATH_TOKENS):
        raise SubsampleError("holdout paths are forbidden")


def _load_json(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    _forbid_holdout_path(target)
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SubsampleError("TRAINING subsample input is unreadable") from exc
    if not isinstance(value, dict):
        raise SubsampleError("TRAINING subsample input is not an object")
    return value
