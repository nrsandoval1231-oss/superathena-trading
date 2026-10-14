"""Offline fresh-evidence comparison. Performance results are unverified."""
from .evaluation import (
    Opportunity,
    adverse_excursion,
    chronological_drawdown,
    compare_policies,
    fill_from_next_bar,
    session_uncertainty,
)

__all__ = [
    "Opportunity",
    "adverse_excursion",
    "chronological_drawdown",
    "compare_policies",
    "fill_from_next_bar",
    "session_uncertainty",
]
