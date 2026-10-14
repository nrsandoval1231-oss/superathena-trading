"""Arm definitions for the AAT-V2 comparison.

V1's four arms all reasoned over the same price-derived features, so the
adaptive arm held no informational advantage and the largest honest effect
available was a re-weighting of sizing under identical evidence.  V2 fixes that
by making exogenous evidence the treatment: arms B through E see it, arm A
cannot.

Arm A is not "the Actor with exogenous features withheld".  It is the frozen
deterministic strategy, which makes no model call at all.  That is why
``build_packet`` refuses to construct one for it -- the asymmetry is structural,
not a flag someone could flip.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..athena_adapter.contracts import canonical_hash

A_DETERMINISTIC = "A_DETERMINISTIC"
B_MEMORYLESS = "B_MEMORYLESS"
C_NAIVE_MEMORY = "C_NAIVE_MEMORY"
D_ATHENA = "D_ATHENA"
E_DELIBERATION = "E_DELIBERATION"

#: Every arm in the V2 comparison, in reporting order.
ARMS = (A_DETERMINISTIC, B_MEMORYLESS, C_NAIVE_MEMORY, D_ATHENA, E_DELIBERATION)

#: Arms that call an Actor at all.  Arm A is the frozen strategy.
ACTOR_ARMS = (B_MEMORYLESS, C_NAIVE_MEMORY, D_ATHENA, E_DELIBERATION)

#: Arms that receive the exogenous feature vector.  This tuple *is* the
#: treatment definition; arm A's absence from it is the experiment.
EXOGENOUS_ARMS = (B_MEMORYLESS, C_NAIVE_MEMORY, D_ATHENA, E_DELIBERATION)

#: Arms that receive promoted lesson memory.
MEMORY_ARMS = (C_NAIVE_MEMORY, D_ATHENA, E_DELIBERATION)

#: Arm E runs a bounded bull/bear deliberation instead of one call.
DELIBERATION_ARMS = (E_DELIBERATION,)


class ArmError(ValueError):
    """An arm was asked to do something its definition forbids."""


def receives_exogenous(arm: str) -> bool:
    _validate(arm)
    return arm in EXOGENOUS_ARMS


def receives_memory(arm: str) -> bool:
    _validate(arm)
    return arm in MEMORY_ARMS


def calls_actor(arm: str) -> bool:
    _validate(arm)
    return arm in ACTOR_ARMS


def deliberates(arm: str) -> bool:
    _validate(arm)
    return arm in DELIBERATION_ARMS


def _validate(arm: str) -> None:
    if arm not in ARMS:
        raise ArmError(f"unknown arm {arm!r}")


def assert_equal_token_budget(
    *, deliberation_turns: int, per_turn_output_tokens: int, single_call_output_tokens: int,
) -> None:
    """Hold arm E to the same total output budget as one arm-D call.

    Deliberation is the most interesting thing TradingAgents does and the least
    likely to survive an equal-budget comparison.  Without this guard a win for
    arm E is unattributable: it could be the debate, or it could be that the
    debate was simply allowed to spend more tokens thinking.  Splitting one
    call's budget across the turns is what makes the contrast mean something.
    """
    if deliberation_turns < 2:
        raise ArmError("deliberation needs at least a bull and a bear turn")
    if per_turn_output_tokens < 1 or single_call_output_tokens < 1:
        raise ArmError("token budgets must be positive")
    total = deliberation_turns * per_turn_output_tokens
    if total > single_call_output_tokens:
        raise ArmError(
            f"deliberation budget {total} exceeds the single-call budget "
            f"{single_call_output_tokens}; a win would be unattributable"
        )


def arm_definitions(*, deliberation_turns: int, per_turn_output_tokens: int,
                    single_call_output_tokens: int) -> dict[str, Any]:
    """Hashable arm definitions for a registered protocol."""
    assert_equal_token_budget(
        deliberation_turns=deliberation_turns,
        per_turn_output_tokens=per_turn_output_tokens,
        single_call_output_tokens=single_call_output_tokens,
    )
    definitions = {
        "arms": list(ARMS),
        "actor_arms": list(ACTOR_ARMS),
        "exogenous_arms": list(EXOGENOUS_ARMS),
        "memory_arms": list(MEMORY_ARMS),
        "deliberation": {
            "arms": list(DELIBERATION_ARMS),
            "turns": deliberation_turns,
            "per_turn_output_tokens": per_turn_output_tokens,
            "single_call_output_tokens": single_call_output_tokens,
        },
    }
    definitions["arms_hash"] = canonical_hash(definitions)
    return definitions


def assert_treatment_asymmetry(definitions: Mapping[str, Any]) -> None:
    """The control arm must never appear among the treated arms."""
    treated = set(definitions.get("exogenous_arms", ()))
    if A_DETERMINISTIC in treated:
        raise ArmError("the deterministic control arm cannot receive exogenous evidence")
    if not treated:
        raise ArmError("no arm receives the treatment; the comparison has no mechanism")
    if A_DETERMINISTIC in set(definitions.get("actor_arms", ())):
        raise ArmError("the deterministic control arm cannot call an Actor")
