"""Compatibility import path.

Implementation: ``athena_trading.earnings.earnings``.
Attribute access reaches that module. This file has no trading logic.
"""
import sys

from athena_trading.earnings import earnings as _implementation

sys.modules[__name__] = _implementation
