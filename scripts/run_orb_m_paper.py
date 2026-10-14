"""Start an ORB-M paper session (or a deterministic dry-run of one).

Default authority is ABSENT: nothing is sent. ``--dry-run`` grants PAPER
against an in-memory broker and synthetic bars — no network, no API keys,
no Massive pull.

Alpaca paper is optional and fail-closed:

    python scripts/run_orb_m_paper.py --broker alpaca --authority PAPER

requires ``ALPACA_API_KEY`` and ``ALPACA_API_SECRET``. Missing keys exit
nonzero without sending. LIVE is not a value.

This historical runner supports fixtures and broker preflight only. Actual paper
orders use run_athena_paper.py, which owns reconciliation, exits and learning.

Walk fixture bars through ORB-M and the paper path (no network, no keys):

    python scripts/run_orb_m_paper.py --walk-bars
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from athena_trading.execution import ExecutionAuthority, parse_authority
from athena_trading.paper.alpaca import AlpacaPaperBroker, MissingCredentialsError
from athena_trading.paper.bars import load_bar_session
from athena_trading.paper.fixture import FixtureBroker
from athena_trading.paper.session import (
    load_paper_config, result_as_dict, run_dry_run,
)
from athena_trading.paper.walk import run_walk_fixture

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs" / "orb_m_paper_session_v1.json"
SHIPPED_BARS = ROOT / "configs" / "fixtures" / "orb_m_paper_bars_v1.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="PAPER authority against the fixture broker and synthetic bars",
    )
    parser.add_argument(
        "--halt-demo", action="store_true",
        help="preload max daily loss so the halt gate refuses before send",
    )
    parser.add_argument(
        "--authority", default=None,
        help="ABSENT (default) or PAPER. LIVE is rejected",
    )
    parser.add_argument(
        "--broker", choices=("fixture", "alpaca"), default=None,
        help="fixture is the no-network path; alpaca requires paper keys",
    )
    parser.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG,
        help="paper session config (authority stays ABSENT unless overridden)",
    )
    parser.add_argument(
        "--submit-demo", action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--walk-bars", action="store_true",
        help="walk the shipped fixture bars through ORB-M and submit as each signal completes",
    )
    parser.add_argument(
        "--bars", type=Path, default=None,
        help="recorded bar session JSON (athena-orb-m-paper-bars-v1)",
    )
    args = parser.parse_args(argv)

    config = load_paper_config(args.config)
    walking = bool(args.walk_bars or args.bars)
    if args.dry_run or args.walk_bars:
        authority = (
            parse_authority(args.authority) if args.authority
            else ExecutionAuthority.PAPER
        )
        broker_name = "fixture"
    else:
        authority = parse_authority(
            args.authority or str(config.get("execution_authority", "ABSENT"))
        )
        broker_name = args.broker or str(config.get("broker", "fixture"))

    if broker_name == "alpaca":
        if args.submit_demo:
            parser.error("legacy broker submission is retired; use run_athena_paper.py")
        try:
            broker = AlpacaPaperBroker.from_env()
        except MissingCredentialsError as exc:
            print(json.dumps({
                "ok": False,
                "error": str(exc),
                "execution_authority": authority.value,
                "broker": "alpaca",
                "live_trading": False,
            }, indent=2))
            return 2
        if not args.submit_demo:
            broker.preflight()
            print(json.dumps({
                "ok": True,
                "broker": "alpaca",
                "preflight": True,
                "submitted": 0,
                "execution_authority": authority.value,
                "live_trading": False,
            }, indent=2))
            return 0
    else:
        broker = FixtureBroker()

    if walking:
        recorded = load_bar_session(args.bars or SHIPPED_BARS)
        result = run_walk_fixture(
            authority=authority, halt_demo=args.halt_demo, broker=broker,
            session=recorded,
        )
    else:
        result = run_dry_run(
            authority=authority, halt_demo=args.halt_demo, broker=broker,
        )
    payload = result_as_dict(result)
    payload["ok"] = True
    payload["broker"] = broker_name
    payload["dry_run"] = bool(args.dry_run)
    payload["walk_bars"] = walking
    payload["config"] = str(args.config)
    if walking:
        payload["bars"] = str(args.bars or SHIPPED_BARS)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
