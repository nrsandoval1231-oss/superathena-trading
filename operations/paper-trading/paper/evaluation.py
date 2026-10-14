"""Compatibility import path.

Implementation: ``athena_trading.backtesting.evaluation``.
Attribute access reaches that module. This file has no trading logic.
"""
import sys

from athena_trading.backtesting import evaluation as _implementation

sys.modules[__name__] = _implementation
