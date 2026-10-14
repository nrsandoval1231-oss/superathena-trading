"""Safe, training-only AAT-V1 planning boundary."""

from .training import (
    AATValidationError,
    TrainingRow,
    load_registered_protocol,
    load_training_projection,
    plan_training_run,
)
from .opportunities import (
    OpportunityCompileError,
    compile_holdout_opportunities,
    compile_training_opportunities,
)
from .actor_canary import execute_transport_canary, load_local_key, load_pricing, price_requests, validate_actor_identity
from .holdout_gate import count_prior_probes, probe_holdout_sufficiency
from .providers import DEEPSEEK, OLLAMA, OPENAI, ProviderDescriptor, get_provider, provider_identity, register_provider, registered_providers

__all__ = ["DEEPSEEK", "OLLAMA", "OPENAI", "AATValidationError", "ProviderDescriptor", "count_prior_probes", "get_provider", "probe_holdout_sufficiency", "provider_identity", "register_provider", "registered_providers", "OpportunityCompileError", "TrainingRow", "compile_holdout_opportunities", "compile_training_opportunities", "execute_transport_canary", "load_local_key", "load_pricing", "load_registered_protocol", "load_training_projection", "plan_training_run", "price_requests", "validate_actor_identity"]
