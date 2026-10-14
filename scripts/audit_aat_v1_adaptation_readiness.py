"""Write a fail-closed AAT adaptation readiness report."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from athena_trading.aat_v1.readiness import audit_adaptation_readiness


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--opportunity-receipt", type=Path, required=True)
    parser.add_argument("--outcome-receipt", type=Path, required=True)
    parser.add_argument("--protocol-amendment", type=Path)
    parser.add_argument("--transport-ledger", type=Path)
    parser.add_argument("--lesson-inventory", type=Path)
    parser.add_argument("--promotion-rule", type=Path)
    parser.add_argument("--scoring-config", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("refusing to overwrite readiness report")
    report = audit_adaptation_readiness(
        args.protocol, args.opportunity_receipt, args.outcome_receipt,
        protocol_amendment_path=args.protocol_amendment,
        transport_ledger_path=args.transport_ledger,
        lesson_inventory_path=args.lesson_inventory,
        promotion_rule_path=args.promotion_rule,
        scoring_config_path=args.scoring_config,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    return 0 if report["status"].startswith("READY_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
