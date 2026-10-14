"""Compile outcome-free AAT opportunities from Athena's raw TRAINING projection."""
from __future__ import annotations

import argparse
from pathlib import Path

from athena_trading.aat_v1 import compile_training_opportunities


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--rows", type=Path, required=True)
    parser.add_argument("--maximum-opportunities", type=int, required=True)
    parser.add_argument("--output-rows", type=Path, required=True)
    parser.add_argument("--output-receipt", type=Path, required=True)
    parser.add_argument("--require-atr14", action="store_true")
    parser.add_argument("--require-resolved-session", action="store_true")
    args = parser.parse_args()
    compile_training_opportunities(
        args.receipt, args.rows, args.output_rows, args.output_receipt,
        maximum_opportunities=args.maximum_opportunities,
        require_atr14=args.require_atr14,
        require_resolved_session=args.require_resolved_session,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
