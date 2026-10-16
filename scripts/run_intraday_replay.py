"""Replay local intraday bars through the Stage 0 harness.

Authority stays ABSENT. The process reads a local JSON file and writes a
report. It does not submit an order, call a broker, or claim an edge.

    PYTHONPATH=src python3 scripts/run_intraday_replay.py \
        --bars evaluation/backtesting/fixtures/intraday_replay_sample.json \
        --family frozen_orb_reentry \
        --out /tmp/orb-replay.json

    PYTHONPATH=src python3 scripts/run_intraday_replay.py \
        --bars evaluation/backtesting/fixtures/intraday_replay_sample.json \
        --order \
        --out-dir /tmp/intraday-replay
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from athena_trading.backtesting.intraday_replay.constants import NO_EDGE, REPLAY_ORDER
from athena_trading.backtesting.intraday_replay.harness import run_replay, run_replay_order
from athena_trading.backtesting.intraday_replay.types import ReplayRefusal


def _mentions_live(argv: list[str]) -> bool:
    return any(token.strip().upper() == "LIVE" for token in argv)


def _summary(report: dict) -> None:
    metrics = report["metrics"]
    print(
        f"{report['family']}: trades={metrics['oos_trades']} "
        f"expectancy={metrics['cost_adjusted_expectancy_per_trade']} "
        f"gate_passed={report['gate_passed']} "
        f"provenance={report['provenance']}"
    )
    print(NO_EDGE)


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if _mentions_live(raw):
        print("LIVE execution authority is not available", file=sys.stderr)
        return 2
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--bars", type=Path, required=True, help="local JSON bars or a directory")
    parser.add_argument("--family", choices=REPLAY_ORDER, help="one family from the replay order")
    parser.add_argument("--order", action="store_true", help="run all four families in order")
    parser.add_argument("--out", type=Path, help="report path for a single family")
    parser.add_argument("--out-dir", type=Path, help="directory for --order reports")
    args = parser.parse_args(raw)
    if args.order == (args.family is not None):
        parser.error("pass either --family or --order")
    if args.order and args.out_dir is None:
        parser.error("--order requires --out-dir")
    try:
        if args.order:
            reports = run_replay_order(args.bars, out_dir=args.out_dir)
            for report in reports:
                _summary(report)
        else:
            report = run_replay(args.bars, family=args.family, out=args.out)
            _summary(report)
    except (ReplayRefusal, OSError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
