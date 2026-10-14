"""Execute the explicitly authorized, cost-bounded Terra transport canary."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from athena_trading.aat_v1 import (
    AATValidationError,
    execute_transport_canary,
    load_local_key,
    load_pricing,
    load_registered_protocol,
    load_training_projection,
    price_requests,
    validate_actor_identity,
)
from athena_trading.athena_adapter.contracts import canonical_hash


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--pricing", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute-live", action="store_true")
    parser.add_argument("--prior-call-count", type=int, default=0)
    args = parser.parse_args()
    if not args.execute_live:
        parser.error("live execution requires --execute-live")
    if args.output.exists():
        parser.error("refusing to overwrite output")

    config = json.loads(args.config.read_text(encoding="utf-8"))
    required = {
        "model_id": "gpt-5.6-terra", "maximum_opportunities": 10,
        "call_ceiling": 30, "token_ceiling": 38400,
        "retries_per_call_ceiling": 0, "partition": "TRAINING",
        "sealed_holdout_access": False, "execution_authority": "ABSENT",
    }
    if any(config.get(key) != value for key, value in required.items()):
        raise AATValidationError("canary configuration drift")
    spend_ceiling = float(config.get("spend_ceiling_usd", 0))
    if spend_ceiling != 20.0:
        raise AATValidationError("canary spend ceiling must equal the authorized $20")

    registered = load_registered_protocol(args.protocol)
    actor = registered["protocol"]["actor"]
    validate_actor_identity(actor, model_id=config["model_id"])
    receipt, rows = load_training_projection(args.receipt, args.protocol)
    if len(rows) != config["maximum_opportunities"]:
        raise AATValidationError("opportunity count does not match canary registration")
    pricing = load_pricing(args.pricing, model_id=config["model_id"])
    actor_identity = canonical_hash(actor)
    priced = price_requests(rows, model_id=config["model_id"], actor_identity=actor_identity, pricing=pricing)
    if priced["request_count"] > config["call_ceiling"]:
        raise AATValidationError("priced request exceeds call ceiling")
    if not 0 <= args.prior_call_count < priced["request_count"]:
        raise AATValidationError("prior call count is invalid")
    result = execute_transport_canary(
        rows, model_id=config["model_id"], actor_identity=actor_identity,
        pricing=pricing, spend_ceiling_usd=spend_ceiling,
        token_ceiling=config["token_ceiling"], ledger_path=args.ledger,
        api_key=load_local_key(args.env_file),
        request_offset=args.prior_call_count,
    )
    per_prior_call_upper_bound = priced["per_request_cost_upper_bound_usd"]
    prior_cost_upper_bound = args.prior_call_count * per_prior_call_upper_bound
    result = {
        **result, "protocol_hash": receipt["protocol_hash"],
        "opportunity_projection_hash": receipt["projection_hash"],
        "pricing_hash": canonical_hash(pricing),
        "worst_case_cost_usd": priced["worst_case_cost_usd"],
        "spend_ceiling_usd": spend_ceiling,
        "prior_unrecorded_call_count": args.prior_call_count,
        "prior_call_cost_upper_bound_usd": prior_cost_upper_bound,
        "total_call_count": args.prior_call_count + result["request_count"],
        "total_cost_upper_bound_usd": prior_cost_upper_bound + result["recorded_actual_cost_usd"],
    }
    result["result_hash"] = canonical_hash(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
