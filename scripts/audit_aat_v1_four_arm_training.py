"""Verify a completed four-arm TRAINING result and write a non-claim audit."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from athena_trading.aat_v1.four_arm import audit_four_arm_result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("refusing to overwrite four-arm audit")
    audit = audit_four_arm_result(args.result, args.ledger)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(audit, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
