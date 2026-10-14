"""Compatibility import path.

Implementation: ``athena_trading.broker_adapters.alpaca``.
Attribute access reaches that module. This file has no trading logic.
"""
import sys

from athena_trading.broker_adapters import alpaca as _implementation

sys.modules[__name__] = _implementation
