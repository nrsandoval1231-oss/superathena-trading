"""Ask whether a candidate holdout is large enough, before authorizing anything.

Run this at dataset-construction time. If it reports INSUFFICIENT, redraw the
assignment and probe again; only once it clears should a single-use
authorization be issued. The probe accepts no authorization and cannot consume
one.

Reads only. Calls no model, spends nothing, and writes no claim evidence.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from athena_trading.aat_v1.holdout_gate import count_prior_probes, probe_holdout_sufficiency


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--opportunity-receipt", type=Path, required=True)
    parser.add_argument("--assignment-hash", required=True)
    parser.add_argument("--probe-log", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    prior = (
        count_prior_probes(args.probe_log, assignment_hash=args.assignment_hash)
        if args.probe_log else 0
    )
    result = probe_holdout_sufficiency(
        args.contract, args.opportunity_receipt,
        assignment_hash=args.assignment_hash, probe_log_path=args.probe_log,
    )
    if args.output:
        if args.output.exists():
            raise SystemExit("refusing to overwrite an existing probe result")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True, indent=2))
    if prior:
        # Redrawing until the count clears is tuning the split against the
        # contract, and whoever authorizes the run should see it.
        print(f"note: this assignment has been probed {prior} time(s) before")
    return 0 if result["status"] == "SUFFICIENT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
