"""AAT-V2: the exogenous-evidence adaptation experiment.

Proposed in ``docs/AAT_V2_VISION.md``, sequenced in ``docs/AAT_V2_PLAN.md``.
This package holds the experiment's machinery and non-authorizing registration
artifacts. The V2 protocol may be registered, but claims remain unauthorized,
holdout access remains separately gated, and ``execution_authority`` is
``ABSENT`` throughout.

AAT-V1 is untouched. V2 is a separate experiment with its own dataset
assignment and its own, separately authorized holdout.
"""

from .arms import (
    ACTOR_ARMS,
    ARMS,
    DELIBERATION_ARMS,
    EXOGENOUS_ARMS,
    MEMORY_ARMS,
    ArmError,
    arm_definitions,
    assert_equal_token_budget,
    assert_treatment_asymmetry,
    calls_actor,
    deliberates,
    receives_exogenous,
    receives_memory,
)
from .assignment import (
    AssignmentError,
    assert_linked_symbols_share_a_partition,
    assert_partitions_disjoint,
    draw_assignment,
    filter_opportunities,
    load_universe,
    partition_for,
    write_assignment,
)
from .contract import ContractError, freeze_claim_contract, load_contract, write_contract
from .packet import (
    assert_control_arm_never_saw_treatment,
    build_packet,
    ledger_projection,
    packet_hash,
)
from .opportunities import OpportunityIndexError, build_opportunity_index
from .protocol import ProtocolError, register_protocol
from .deepseek_preflight import (
    DeepSeekPreflightError,
    MissingDeepSeekCredentialsError,
    api_key_from_env,
    plan_deepseek_flash_dry_run,
    run_deepseek_flash_preflight,
)
from .deepseek_pilot import DeepSeekPilotError, run_deepseek_flash_pilot
from .identity import (
    IdentityError,
    declared_deepseek_flash_identity,
    load_deepseek_flash_identity,
)
from .ollama_identity import (
    AuthorizationError,
    declared_local_training_authorization,
    declared_ollama_qwen_identity,
    declared_ollama_runpod_identity,
    declared_ollama_volume_identity,
    declared_runpod_training_authorization,
    declared_volume_training_authorization,
    load_local_training_authorization,
    load_ollama_qwen_identity,
    load_ollama_runpod_identity,
    load_ollama_volume_identity,
    load_runpod_training_authorization,
    load_volume_training_authorization,
)
from .ollama_training import OllamaTrainingError, run_ollama_local_training
from .ollama_transport import OllamaTransportError
from .deliberation import (
    DeliberationError,
    assert_compact_payloads_fit_budget,
    deliberation_plan,
    load_e_arm_amendment,
    parse_deliberation_turn,
    raw_content_snippet,
    scored_action_from_turns,
    turn_system_prompt,
)

__all__ = [
    "ACTOR_ARMS", "ARMS", "DELIBERATION_ARMS", "EXOGENOUS_ARMS", "MEMORY_ARMS",
    "ArmError", "AssignmentError", "AuthorizationError", "ContractError",
    "DeepSeekPilotError",
    "DeepSeekPreflightError",
    "DeliberationError", "IdentityError",
    "MissingDeepSeekCredentialsError", "OllamaTrainingError",
    "OllamaTransportError", "arm_definitions",
    "api_key_from_env",
    "assert_compact_payloads_fit_budget",
    "assert_control_arm_never_saw_treatment", "assert_equal_token_budget",
    "assert_linked_symbols_share_a_partition", "assert_partitions_disjoint",
    "assert_treatment_asymmetry", "build_packet",
    "calls_actor", "declared_deepseek_flash_identity",
    "declared_local_training_authorization", "declared_ollama_qwen_identity",
    "declared_ollama_runpod_identity", "declared_ollama_volume_identity",
    "declared_runpod_training_authorization",
    "declared_volume_training_authorization",
    "deliberates",
    "deliberation_plan", "draw_assignment",
    "filter_opportunities",
    "freeze_claim_contract", "ledger_projection", "load_contract",
    "load_deepseek_flash_identity",
    "load_e_arm_amendment", "load_local_training_authorization",
    "load_ollama_qwen_identity", "load_ollama_runpod_identity",
    "load_ollama_volume_identity",
    "load_runpod_training_authorization",
    "load_volume_training_authorization", "load_universe",
    "packet_hash", "parse_deliberation_turn", "partition_for",
    "plan_deepseek_flash_dry_run",
    "raw_content_snippet",
    "receives_exogenous", "receives_memory",
    "OpportunityIndexError", "build_opportunity_index",
    "ProtocolError", "register_protocol", "run_deepseek_flash_pilot",
    "run_deepseek_flash_preflight", "run_ollama_local_training",
    "scored_action_from_turns",
    "turn_system_prompt",
    "write_assignment", "write_contract",
]
