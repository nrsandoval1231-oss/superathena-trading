"""Evaluate ATR-qualified AAT opportunities on TRAINING future bars."""
from __future__ import annotations

import argparse
from pathlib import Path

from athena_trading.aat_v1.outcomes import evaluate_training_outcomes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-receipt", type=Path, required=True)
    parser.add_argument("--source-rows", type=Path, required=True)
    parser.add_argument("--opportunity-receipt", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output-rows", type=Path, required=True)
    parser.add_argument("--output-receipt", type=Path, required=True)
    parser.add_argument("--full-session", action="store_true")
    args = parser.parse_args()
    evaluate_training_outcomes(
        args.source_receipt, args.source_rows, args.opportunity_receipt,
        args.protocol, args.output_rows, args.output_receipt,
        full_session=args.full_session,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
