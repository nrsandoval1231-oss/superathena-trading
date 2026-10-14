"""Compatibility import path.

Implementation: ``athena_trading.portfolio.shared_risk``.
Attribute access reaches that module. This file has no trading logic.
"""
import sys

from athena_trading.portfolio import shared_risk as _implementation

sys.modules[__name__] = _implementation
