"""Plan or execute the bounded AAT-V1 four-arm TRAINING comparison."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from athena_trading.aat_v1.actor_canary import load_local_key
from athena_trading.aat_v1.four_arm import (
    authorize_single_recovery,
    execute_four_arm_training,
    prepare_four_arm_training,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--protocol-amendment", type=Path, required=True)
    parser.add_argument("--transport-ledger", type=Path, required=True)
    parser.add_argument("--opportunity-receipt", type=Path, required=True)
    parser.add_argument("--outcome-receipt", type=Path, required=True)
    parser.add_argument("--lesson-inventory", type=Path, required=True)
    parser.add_argument("--promotion-rule", type=Path, required=True)
    parser.add_argument("--scoring-config", type=Path, required=True)
    parser.add_argument("--pricing", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--execute-live", action="store_true")
    parser.add_argument("--recovery-config", type=Path)
    parser.add_argument("--blocked-result", type=Path)
    args = parser.parse_args()
    config, inventory, plan = prepare_four_arm_training(
        config_path=args.config, protocol_path=args.protocol,
        amendment_path=args.protocol_amendment,
        transport_ledger_path=args.transport_ledger,
        opportunity_receipt_path=args.opportunity_receipt,
        outcome_receipt_path=args.outcome_receipt,
        inventory_path=args.lesson_inventory,
        promotion_rule_path=args.promotion_rule,
        scoring_config_path=args.scoring_config,
        pricing_path=args.pricing,
    )
    summary = {key: value for key, value in plan.items() if key not in {"requests", "pricing"}}
    if not args.execute_live:
        print(json.dumps(summary, sort_keys=True, indent=2))
        return 0
    if args.env_file is None or args.ledger is None or args.output is None:
        parser.error("live execution requires --env-file, --ledger, and --output")
    if args.recovery_config is not None:
        if args.blocked_result is None:
            parser.error("recovery requires --blocked-result")
        config = authorize_single_recovery(
            base_config=config, recovery_config_path=args.recovery_config,
            blocked_result_path=args.blocked_result, ledger_path=args.ledger,
        )
    result = execute_four_arm_training(
        plan=plan, config=config, pricing=plan["pricing"],
        outcome_receipt_path=args.outcome_receipt, inventory=inventory,
        ledger_path=args.ledger, output_path=args.output,
        api_key=load_local_key(args.env_file),
    )
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result["status"] == "COMPLETE_TRAINING_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
