"""Offline intraday replay. Authority stays ABSENT. No broker client.

A fixture result is not market evidence. The report says that no edge is claimed.
"""
from .harness import run_replay, run_replay_order
from .pass_line import evaluate_pass_line

__all__ = ["evaluate_pass_line", "run_replay", "run_replay_order"]
