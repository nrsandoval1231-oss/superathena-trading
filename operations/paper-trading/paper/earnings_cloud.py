"""Compatibility import path.

Implementation: ``athena_trading.earnings.earnings_cloud``.
Attribute access reaches that module. This file has no trading logic.
"""
import sys

from athena_trading.earnings import earnings_cloud as _implementation

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
sys.modules[__name__] = _implementation
