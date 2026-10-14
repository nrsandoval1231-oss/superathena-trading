"""Compatibility import path.

Implementation: ``athena_trading.intraday.live``.
Attribute access reaches that module. This file has no trading logic.
"""
import sys

from athena_trading.intraday import live as _implementation

sys.modules[__name__] = _implementation
