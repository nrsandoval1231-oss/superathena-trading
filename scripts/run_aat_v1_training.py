"""CLI for validating and planning an AAT-V1 TRAINING-only run."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from athena_trading.aat_v1 import load_training_projection, plan_training_run


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--call-ceiling", type=int, required=True)
    parser.add_argument("--token-ceiling", type=int, required=True)
    parser.add_argument("--spend-ceiling-usd", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("refusing to overwrite existing output")
    receipt, rows = load_training_projection(args.receipt, args.protocol)
    plan = plan_training_run(receipt, rows, call_ceiling=args.call_ceiling, token_ceiling=args.token_ceiling, spend_ceiling_usd=args.spend_ceiling_usd)
    args.output.write_text(json.dumps(plan, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
