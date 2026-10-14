"""Plan a cost-bounded DeepSeek Flash dry-run; optional fixture preflight.

This is not TRAINING authorization and does not spend against the registered
protocol. See ``docs/AAT_V2_MODEL_EXECUTION_OPTIONS.md``.

Default is plan-only: no model call, no credential required.

    python scripts/plan_aat_v2_deepseek_flash.py --output /tmp/deepseek-plan.json

``--preflight`` dry-runs a tiny N-call against the shipped fixture. Missing
``DEEPSEEK_API_KEY`` fails closed. Live spend is not implied; the planner
refuses a live transport unless library callers pass ``allow_live=True``.
Thinking is disabled. B/C/D require the Actor JSON schema; arm E uses the
compact closed-enum turn schema. Live spend is not implied; the planner
refuses a live transport unless library callers pass ``allow_live=True``.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from athena_trading.aat_v2.deepseek_preflight import (
    DeepSeekPreflightError,
    MissingDeepSeekCredentialsError,
    fixture_transport,
    forbid_output_path,
    plan_deepseek_flash_dry_run,
    run_deepseek_flash_preflight,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = ROOT / "configs" / "aat_v2_training_plan_v2.json"
DEFAULT_PRICING = ROOT / "configs" / "deepseek_flash_pricing_2026-09-14.json"
DEFAULT_PROTOCOL = ROOT / "configs" / "aat_v2_registered_protocol_v1.json"
DEFAULT_FIXTURE = ROOT / "configs" / "fixtures" / "deepseek_flash_preflight_v1.json"
DEFAULT_AMENDMENT = ROOT / "configs" / "aat_v2_e_arm_compact_schema_amendment_v1.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--pricing", type=Path, default=DEFAULT_PRICING)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--preflight", action="store_true",
        help="tiny fixture preflight; requires DEEPSEEK_API_KEY and spends nothing live",
    )
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--call-ceiling", type=int, default=3)
    parser.add_argument(
        "--spend-ceiling-usd",
        type=float,
        default=0.05,
        help=(
            "invocation spend cap; hard PREFLIGHT ceiling is $1.00 and is not "
            "TRAINING authorization"
        ),
    )
    parser.add_argument(
        "--include-deliberation", action="store_true",
        help="add four compact E-arm turns to the fixture preflight (still capped at 7)",
    )
    parser.add_argument(
        "--amendment",
        type=Path,
        default=DEFAULT_AMENDMENT,
        help="non-authorizing E-arm compact-schema amendment; required with --include-deliberation",
    )
    args = parser.parse_args(argv)

    try:
        if args.preflight:
            result = run_deepseek_flash_preflight(
                fixture_path=args.fixture,
                pricing_path=args.pricing,
                protocol_path=args.protocol,
                call_ceiling=args.call_ceiling,
                spend_ceiling_usd=args.spend_ceiling_usd,
                include_deliberation=args.include_deliberation,
                amendment_path=args.amendment if args.include_deliberation else None,
                transport=fixture_transport(args.fixture),
            )
        else:
            result = plan_deepseek_flash_dry_run(
                training_plan_path=args.plan,
                pricing_path=args.pricing,
                protocol_path=args.protocol,
            )
        if args.output:
            target = forbid_output_path(args.output)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8",
            )
    except MissingDeepSeekCredentialsError as exc:
        print(json.dumps({
            "ok": False,
            "error": str(exc),
            "execution_authority": "ABSENT",
            "sealed_holdout_consumed": False,
            "live_calls": False,
        }, indent=2, sort_keys=True))
        return 2
    except DeepSeekPreflightError as exc:
        print(json.dumps({
            "ok": False,
            "error": str(exc),
            "execution_authority": "ABSENT",
            "sealed_holdout_consumed": False,
            "live_calls": False,
        }, indent=2, sort_keys=True))
        return 1

    payload = dict(result)
    payload["ok"] = True
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
