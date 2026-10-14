"""Draw the AAT-V2 7b-volume / 14b-gold TRAINING subsample.

Reads the frozen TRAINING opportunity index (not holdout) and the committed
subsample plan. Writes a hashed 1,000-opportunity volume receipt plus JSONL
and a 100-opportunity gold slice that is a subset of volume.

Does not call a model, does not start a pod, and does not authorize Terra.
``execution_authority`` stays ``ABSENT``. Refuses to overwrite existing
outputs. The full 16,705-opportunity plan is not the recommended next step.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from athena_trading.aat_v2.ollama_training import (
    load_macro_only_training_plan,
    load_training_assignment,
    load_training_opportunities,
)
from athena_trading.aat_v2.training_subsample import (
    COMMITTED_SUBSAMPLE_PLAN_PATH,
    SubsampleError,
    draw_training_subsample,
    load_training_subsample_plan,
    verify_opportunity_index_receipt,
    write_subsample_index,
    write_subsample_receipt,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = ROOT / "configs" / "aat_v2_training_plan_v2.json"
DEFAULT_ASSIGNMENT = ROOT / "configs" / "aat_v2_dataset_assignment_v1.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--training-plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--assignment", type=Path, default=DEFAULT_ASSIGNMENT)
    parser.add_argument("--subsample-plan", type=Path, default=COMMITTED_SUBSAMPLE_PLAN_PATH)
    parser.add_argument("--opportunity-index", type=Path, required=True)
    parser.add_argument("--opportunity-receipt", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        training_plan = load_macro_only_training_plan(args.training_plan)
        assignment = load_training_assignment(args.assignment)
        plan = load_training_subsample_plan(args.subsample_plan)
        opportunities = load_training_opportunities(args.opportunity_index)
        receipt = verify_opportunity_index_receipt(
            args.opportunity_index, args.opportunity_receipt,
            expected_hash=training_plan["dataset_hash"],
        )
        parent_hash = receipt["index_hash"]
        drawn = draw_training_subsample(
            opportunities,
            plan=plan,
            assignment=assignment,
            parent_dataset_hash=parent_hash,
        )
        output = args.output_dir
        volume_index = write_subsample_index(
            drawn["volume_rows"], output / "volume_1000.jsonl",
        )
        gold_index = write_subsample_index(
            drawn["gold_rows"], output / "gold_100.jsonl",
        )
        volume_receipt = write_subsample_receipt(
            drawn["volume_receipt"], output / "volume_1000.receipt.json",
        )
        gold_receipt = write_subsample_receipt(
            drawn["gold_receipt"], output / "gold_100.receipt.json",
        )
    except (SubsampleError, OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({
            "ok": False,
            "error": str(exc),
            "execution_authority": "ABSENT",
            "sealed_holdout_consumed": False,
        }, indent=2, sort_keys=True))
        return 1

    print(json.dumps({
        "ok": True,
        "execution_authority": "ABSENT",
        "volume_count": volume_receipt["selected_count"],
        "gold_count": gold_receipt["selected_count"],
        "volume_subsample_hash": volume_receipt["subsample_hash"],
        "gold_subsample_hash": gold_receipt["subsample_hash"],
        "volume_index": str(volume_index),
        "gold_index": str(gold_index),
        "volume_receipt": str(output / "volume_1000.receipt.json"),
        "gold_receipt": str(output / "gold_100.receipt.json"),
        "authorizes_full_16705_plan": False,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
