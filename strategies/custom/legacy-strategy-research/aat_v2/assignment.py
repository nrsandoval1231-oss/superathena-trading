"""Draw the AAT-V2 TRAINING / sealed-holdout assignment.

Two rules make this defensible, and both are enforced rather than documented.

**Split by symbol, not by opportunity.** Sessions of one name are correlated
with each other far more than with anything else in the universe. Splitting at
the opportunity level would put February's AAPL in TRAINING and March's AAPL in
the holdout, and the holdout would be measuring memorization.

**Draw before looking.** The seed and the universe manifest fully determine the
split, and neither depends on any exogenous feature, outcome, or score. A draw
is reproducible from its receipt alone, so "we redrew until it looked right" is
visible rather than deniable.
"""
from __future__ import annotations

import json
import random
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ..athena_adapter.contracts import canonical_hash

ASSIGNMENT_SCHEMA = "athena-aat-v2-dataset-assignment-v1"

#: Symbols that are effectively one asset and must share a partition.
#:
#: Dual-class shares of one issuer move together, so GOOG in TRAINING and GOOGL
#: in the holdout would let the holdout measure memorization of the same
#: underlying tape.  This list is curated rather than inferred: a rule like
#: "one ticker is a prefix of another" fires on V/VZ, BA/BAC and C/CVX, which
#: are unrelated issuers, and would quietly bind them together instead.
#:
#: Extending the universe means revisiting this list.
LINKED_SYMBOL_GROUPS: tuple[tuple[str, ...], ...] = (
    ("GOOG", "GOOGL"),
)


class AssignmentError(ValueError):
    """The assignment cannot be drawn or is internally inconsistent."""


def load_universe(manifest_path: str | Path) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Read the frozen universe manifest and its members."""
    try:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AssignmentError("universe manifest is unreadable") from exc
    members = manifest.get("members")
    if not isinstance(members, list) or not members:
        raise AssignmentError("universe manifest has no members")
    if len(set(members)) != len(members):
        raise AssignmentError("universe manifest has duplicate members")
    return manifest, tuple(str(symbol) for symbol in members)


def draw_assignment(
    manifest_path: str | Path, *, seed: int, holdout_fraction: float = 0.3,
) -> dict[str, Any]:
    """Return a reproducible symbol-level split of the frozen universe.

    Members are sorted before shuffling so the draw depends on the seed and the
    membership set, never on the order the manifest happens to list them in.
    """
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise AssignmentError("seed must be an integer")
    if not 0.0 < holdout_fraction < 1.0:
        raise AssignmentError("holdout_fraction must lie strictly between 0 and 1")
    manifest, members = load_universe(manifest_path)
    holdout_size = round(len(members) * holdout_fraction)
    if holdout_size < 1 or holdout_size >= len(members):
        raise AssignmentError("holdout_fraction leaves one partition empty")

    # Draw over units rather than symbols so a linked group cannot be split.
    units = _draw_units(members)
    rng = random.Random(seed)
    rng.shuffle(units)
    holdout_members: list[str] = []
    training_members: list[str] = []
    for unit in units:
        # Fill the holdout until adding the next whole unit would overshoot, so
        # a multi-symbol group never lands half in and half out.
        if len(holdout_members) + len(unit) <= holdout_size:
            holdout_members.extend(unit)
        else:
            training_members.extend(unit)
    if not holdout_members or not training_members:
        raise AssignmentError("holdout_fraction leaves one partition empty")
    holdout = tuple(sorted(holdout_members))
    training = tuple(sorted(training_members))
    assignment = {
        "schema_version": ASSIGNMENT_SCHEMA,
        "universe_manifest_hash": manifest.get("manifest_hash"),
        "universe_member_count": len(members),
        "seed": seed,
        "holdout_fraction": holdout_fraction,
        "linked_symbol_groups": [list(group) for group in LINKED_SYMBOL_GROUPS],
        "training_symbols": list(training),
        "holdout_symbols": list(holdout),
        "drawn_from_outcomes": False,
        "drawn_from_exogenous_features": False,
        "execution_authority": "ABSENT",
    }
    assignment["assignment_hash"] = canonical_hash(assignment)
    assert_partitions_disjoint(assignment)
    return assignment


def _draw_units(members: tuple[str, ...]) -> list[tuple[str, ...]]:
    """Group linked symbols into single draw units, leaving the rest singletons.

    Members are sorted first so the unit list depends on the membership set and
    not on the order the manifest happens to list them in.
    """
    present = set(members)
    grouped: set[str] = set()
    units: list[tuple[str, ...]] = []
    for group in LINKED_SYMBOL_GROUPS:
        members_present = tuple(sorted(symbol for symbol in group if symbol in present))
        if len(members_present) > 1:
            units.append(members_present)
            grouped.update(members_present)
    units.extend((symbol,) for symbol in sorted(present - grouped))
    units.sort()
    return units


def assert_partitions_disjoint(assignment: dict[str, Any]) -> None:
    """No symbol may appear in both partitions, and none may be dropped."""
    training = set(assignment.get("training_symbols", ()))
    holdout = set(assignment.get("holdout_symbols", ()))
    overlap = training & holdout
    if overlap:
        raise AssignmentError(f"symbols straddle both partitions: {sorted(overlap)}")
    if not training or not holdout:
        raise AssignmentError("a partition is empty")
    if len(training) + len(holdout) != assignment.get("universe_member_count"):
        raise AssignmentError("assignment does not account for every universe member")
    assert_linked_symbols_share_a_partition(assignment)


def assert_linked_symbols_share_a_partition(assignment: dict[str, Any]) -> None:
    """A dual-class pair split across partitions would contaminate the holdout."""
    training = set(assignment.get("training_symbols", ()))
    holdout = set(assignment.get("holdout_symbols", ()))
    for group in LINKED_SYMBOL_GROUPS:
        in_training = sorted(symbol for symbol in group if symbol in training)
        in_holdout = sorted(symbol for symbol in group if symbol in holdout)
        if in_training and in_holdout:
            raise AssignmentError(
                f"linked symbols split across partitions: "
                f"{in_training} in TRAINING, {in_holdout} in the holdout"
            )


def partition_for(assignment: dict[str, Any], symbol: str) -> str:
    """Which partition a symbol belongs to, refusing anything unassigned."""
    if symbol in set(assignment.get("training_symbols", ())):
        return "TRAINING"
    if symbol in set(assignment.get("holdout_symbols", ())):
        return "SEALED_HOLDOUT"
    raise AssignmentError(f"symbol {symbol!r} is not in the assignment")


def filter_opportunities(
    assignment: dict[str, Any], opportunities: Sequence[dict[str, Any]], *, partition: str,
) -> tuple[dict[str, Any], ...]:
    """Keep only the opportunities belonging to one partition.

    An opportunity naming a symbol outside the assignment is an error, not
    something to drop quietly: it means the index and the universe disagree.
    """
    if partition not in {"TRAINING", "SEALED_HOLDOUT"}:
        raise AssignmentError(f"unknown partition {partition!r}")
    return tuple(
        row for row in opportunities
        if partition_for(assignment, str(row["symbol"])) == partition
    )


def write_assignment(assignment: dict[str, Any], path: str | Path) -> dict[str, Any]:
    """Write a drawn assignment, refusing to overwrite an existing one."""
    target = Path(path)
    if target.exists():
        raise AssignmentError("refusing to overwrite an existing assignment")
    assert_partitions_disjoint(assignment)
    payload = dict(assignment)
    claimed = payload.pop("assignment_hash", None)
    if claimed != canonical_hash(payload):
        raise AssignmentError("assignment hash does not match its contents")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(assignment, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return assignment
