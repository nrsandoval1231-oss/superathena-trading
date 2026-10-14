"""Draw the AAT-V2 TRAINING / sealed-holdout assignment.

Run this *before* any exogenous evidence is ingested. The split is determined
entirely by the seed and the frozen universe manifest, so drawing it early is
what makes "we did not pick a split that flattered the result" a checkable
claim rather than an assurance.

The output is a candidate assignment. It becomes the registered one only when a
V2 protocol names its hash. Redrawing with a different seed is legitimate while
nothing downstream references it and dishonest afterwards.

Writes once and refuses to overwrite. Calls no model and spends nothing.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from athena_trading.aat_v2 import draw_assignment, write_assignment


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe-manifest", type=Path, default=Path("data/universe/manifest.json"))
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--holdout-fraction", type=float, default=0.3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    assignment = draw_assignment(
        args.universe_manifest, seed=args.seed, holdout_fraction=args.holdout_fraction,
    )
    write_assignment(assignment, args.output)
    print(json.dumps({
        "assignment_hash": assignment["assignment_hash"],
        "seed": assignment["seed"],
        "training_symbol_count": len(assignment["training_symbols"]),
        "holdout_symbol_count": len(assignment["holdout_symbols"]),
        "execution_authority": assignment["execution_authority"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
