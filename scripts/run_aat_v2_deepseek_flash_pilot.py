"""Bounded DeepSeek Flash pilot against the declared candidate identity.

Not TRAINING authorization. Does not rewrite the Terra protocol, freeze a
claim contract, or consume a holdout. ``execution_authority`` stays ``ABSENT``.

Default is fixture / dry:

    python scripts/run_aat_v2_deepseek_flash_pilot.py

Live spend is fail-closed. It requires ``--allow-live``, ``DEEPSEEK_API_KEY``,
and explicit ``--call-ceiling`` plus ``--spend-ceiling-usd``. Nick-authorized
bigger live pilot (not TRAINING): about 500 calls and $50.00, typically 71
synthetic opportunities with B/C/D plus four compact E turns (71 × 7 = 497
calls). Dry default stays 1 opportunity / 7 calls / $1.00. See
``docs/AAT_V2_MODEL_EXECUTION_OPTIONS.md``.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from athena_trading.aat_v2.deepseek_pilot import (
    DEFAULT_PILOT_CALL_CEILING,
    DEFAULT_PILOT_OPPORTUNITIES,
    DEFAULT_PILOT_SPEND_CEILING_USD,
    DeepSeekPilotError,
    run_deepseek_flash_pilot,
)
from athena_trading.aat_v2.deepseek_preflight import (
    MissingDeepSeekCredentialsError,
    fixture_transport,
    forbid_output_path,
)
from athena_trading.aat_v2.identity import IdentityError

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PRICING = ROOT / "configs" / "deepseek_flash_pricing_2026-09-14.json"
DEFAULT_PROTOCOL = ROOT / "configs" / "aat_v2_registered_protocol_v1.json"
DEFAULT_FIXTURE = ROOT / "configs" / "fixtures" / "deepseek_flash_preflight_v1.json"
DEFAULT_AMENDMENT = ROOT / "configs" / "aat_v2_e_arm_compact_schema_amendment_v1.json"
DEFAULT_IDENTITY = ROOT / "configs" / "aat_v2_deepseek_flash_actor_identity_v1.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pricing", type=Path, default=DEFAULT_PRICING)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--identity", type=Path, default=DEFAULT_IDENTITY)
    parser.add_argument("--amendment", type=Path, default=DEFAULT_AMENDMENT)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--opportunities",
        type=int,
        default=DEFAULT_PILOT_OPPORTUNITIES,
        help="synthetic fixture opportunities (dry default 1; Nick-authorized bigger live sample 71; hard cap 80)",
    )
    parser.add_argument(
        "--call-ceiling",
        type=int,
        default=None,
        help="required with --allow-live; dry default is 7; Nick-authorized bigger live limit is 500",
    )
    parser.add_argument(
        "--spend-ceiling-usd",
        type=float,
        default=None,
        help="required with --allow-live; dry default is 1.00; Nick-authorized bigger live limit is 50.00",
    )
    parser.add_argument(
        "--include-deliberation",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="four compact E-arm turns per opportunity (default: true)",
    )
    parser.add_argument(
        "--allow-live",
        action="store_true",
        help="opt into live HTTP; still requires DEEPSEEK_API_KEY and ceilings",
    )
    args = parser.parse_args(argv)

    try:
        if args.allow_live:
            if args.call_ceiling is None or args.spend_ceiling_usd is None:
                raise DeepSeekPilotError(
                    "live pilot requires explicit --call-ceiling and --spend-ceiling-usd"
                )
            transport = None
            call_ceiling = args.call_ceiling
            spend_ceiling_usd = args.spend_ceiling_usd
        else:
            transport = fixture_transport(args.fixture)
            call_ceiling = (
                DEFAULT_PILOT_CALL_CEILING if args.call_ceiling is None else args.call_ceiling
            )
            spend_ceiling_usd = (
                DEFAULT_PILOT_SPEND_CEILING_USD
                if args.spend_ceiling_usd is None
                else args.spend_ceiling_usd
            )
        result = run_deepseek_flash_pilot(
            fixture_path=args.fixture,
            pricing_path=args.pricing,
            protocol_path=args.protocol,
            identity_path=args.identity,
            amendment_path=args.amendment if args.include_deliberation else None,
            opportunity_count=args.opportunities,
            call_ceiling=call_ceiling,
            spend_ceiling_usd=spend_ceiling_usd,
            transport=transport,
            allow_live=args.allow_live,
            include_deliberation=args.include_deliberation,
        )
        if args.output:
            target = forbid_output_path(args.output)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8",
            )
    except MissingDeepSeekCredentialsError as exc:
        print(json.dumps(_error_payload(exc, live_calls=False), indent=2, sort_keys=True))
        return 2
    except (DeepSeekPilotError, IdentityError) as exc:
        print(json.dumps(_error_payload(exc), indent=2, sort_keys=True))
        return 1

    payload = dict(result)
    payload["ok"] = True
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _error_payload(exc: BaseException, *, live_calls: bool | None = None) -> dict[str, object]:
    """Fail-closed CLI receipt. Preserve live-attempt evidence from the exception."""
    payload: dict[str, object] = {
        "ok": False,
        "error": str(exc),
        "execution_authority": "ABSENT",
        "sealed_holdout_consumed": False,
        "live_calls": getattr(exc, "live_calls", False) if live_calls is None else live_calls,
        "allow_live": getattr(exc, "allow_live", False),
        "completed_calls": getattr(exc, "completed_calls", 0),
        "attempted_calls": getattr(exc, "attempted_calls", 0),
        "status": "PILOT_NOT_TRAINING",
    }
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
