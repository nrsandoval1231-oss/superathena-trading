"""Compile fixed opportunities from the consumed AAT sealed holdout."""
from __future__ import annotations

import argparse
from pathlib import Path

from athena_trading.aat_v1 import compile_holdout_opportunities


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--rows", type=Path, required=True)
    parser.add_argument("--maximum-opportunities", type=int, required=True)
    parser.add_argument("--output-rows", type=Path, required=True)
    parser.add_argument("--output-receipt", type=Path, required=True)
    parser.add_argument("--require-atr14", action="store_true")
    parser.add_argument("--require-resolved-session", action="store_true")
    parser.add_argument("--training-context-receipt", type=Path)
    parser.add_argument("--training-context-rows", type=Path)
    args = parser.parse_args()
    compile_holdout_opportunities(
        args.receipt, args.rows, args.output_rows, args.output_receipt,
        maximum_opportunities=args.maximum_opportunities,
        require_atr14=args.require_atr14,
        require_resolved_session=args.require_resolved_session,
        context_receipt_path=args.training_context_receipt,
        context_rows_path=args.training_context_rows,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
