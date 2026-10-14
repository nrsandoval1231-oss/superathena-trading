"""Run the offline fixture self-improve lab.

Mutates one management knob at a time, scores sealed synthetic bars, and
writes generation receipts. Execution authority stays ABSENT. This process
does not call a broker or model client and does not read the AAT-V1 holdout.

The default is 3 search generations on the builtin fixtures. Each generation
seeds from the best search survivor. The holdout opens once after the last
generation and is not fed back into search.

    python scripts/run_fixture_self_improve.py --out /tmp/fixture-self-improve
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from athena_trading.execution.authority import AuthorityError
from athena_trading.paper.self_improve import (
    DEFAULT_GENERATIONS, HoldoutSealError, run_fixture_lab,
)


def _mentions_live(argv: list[str]) -> bool:
    return any(token.strip().upper() == "LIVE" for token in argv)


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if _mentions_live(raw):
        print("LIVE execution authority is not available", file=sys.stderr)
        return 2
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--out", type=Path, required=True,
        help="directory for generation and holdout receipts",
    )
    parser.add_argument(
        "--generations", type=int, default=DEFAULT_GENERATIONS,
        help=(
            "search generations on the same sealed partition "
            f"(default {DEFAULT_GENERATIONS})"
        ),
    )
    parser.add_argument(
        "--authority", default=None, help=argparse.SUPPRESS,
    )
    args = parser.parse_args(raw)
    if args.authority is not None:
        print("this lab does not accept an execution authority", file=sys.stderr)
        return 2
    if args.generations < 1:
        print("generations must be positive", file=sys.stderr)
        return 2
    try:
        summary = run_fixture_lab(args.out, generations=args.generations)
    except (ValueError, AuthorityError, HoldoutSealError, FileExistsError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(summary["report_text"], end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
