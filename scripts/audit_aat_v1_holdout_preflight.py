"""Audit frozen sealed-holdout sufficiency before any Actor call."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from athena_trading.aat_v1.holdout_gate import audit_holdout_preflight


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--opportunity-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("refusing to overwrite holdout preflight")
    result = audit_holdout_preflight(args.contract, args.authorization, args.opportunity_receipt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
