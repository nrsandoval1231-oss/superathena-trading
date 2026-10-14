"""Report exogenous coverage across an opportunity index.

Coverage is the number that decides whether an AAT-V2 comparison has any power.
If most opportunities carry no exogenous evidence, the adaptive arms are the
deterministic arm with extra steps, and a null result says nothing about
adaptation.  Measure it before a protocol is registered, not afterwards.

Reads only.  Calls no model, spends nothing, writes no evidence.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from athena_trading.exogenous import (
    compress_opportunity,
    coverage_rates,
    load_opportunity_index,
    load_record_store,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--opportunity-index", type=Path, required=True)
    parser.add_argument("--store-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--floor", type=float, default=None,
        help="Fail if any source falls below this coverage rate.",
    )
    args = parser.parse_args()

    opportunities = load_opportunity_index(args.opportunity_index)
    store_receipt, records = load_record_store(args.store_receipt)
    rows = [compress_opportunity(records, opportunity) for opportunity in opportunities]
    rates = coverage_rates(rows)
    report = {
        "schema_version": "athena-exogenous-coverage-report-v1",
        "opportunity_count": len(rows),
        "record_store_hash": store_receipt["store_hash"],
        "coverage_rates": rates,
        "mean_visible_records": round(
            sum(row["visible_record_count"] for row in rows) / len(rows), 4
        ),
        "execution_authority": "ABSENT",
    }
    if args.output:
        if args.output.exists():
            raise SystemExit("refusing to overwrite an existing coverage report")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True, indent=2))

    if args.floor is not None:
        thin = sorted(source for source, rate in rates.items() if rate < args.floor)
        if thin:
            print(f"coverage below {args.floor} for: {', '.join(thin)}")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
