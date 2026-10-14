"""Compatibility import path.

Implementation: ``athena_trading.accounting.journal``.
Attribute access reaches that module. This file has no trading logic.
"""
import sys

from athena_trading.accounting import journal as _implementation

sys.modules[__name__] = _implementation
