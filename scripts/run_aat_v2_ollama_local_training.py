"""Fail-closed Ollama AAT-V2 TRAINING runner.

Defaults to a tiny dry-run smoke against the TRAINING-shaped fixture index.
Does not contact DeepSeek or RunPod. Does not start the 116,935-call run.
The recommended live plan is 7b volume (1,000 opportunities) plus 14b gold
(100 overlapping opportunities), not the full 16,705.

Desktop smoke (offline, default ``qwen3.5:9b``)::

    python scripts/run_aat_v2_ollama_local_training.py

Volume 7b smoke (offline mocked ``qwen2.5:7b``)::

    python scripts/run_aat_v2_ollama_local_training.py \\
      --identity configs/aat_v2_ollama_qwen_7b_volume_actor_identity_v1.json \\
      --authorization configs/aat_v2_ollama_volume_training_authorization_v1.json \\
      --base-url http://127.0.0.1:11434

Gold 14b smoke (offline mocked ``qwen2.5:14b``)::

    python scripts/run_aat_v2_ollama_local_training.py \\
      --identity configs/aat_v2_ollama_qwen_14b_runpod_actor_identity_v1.json \\
      --authorization configs/aat_v2_ollama_runpod_training_authorization_v1.json \\
      --base-url http://127.0.0.1:11434

Authorized volume subsample (1,000 opportunities, still ABSENT; not Terra)::

    python scripts/run_aat_v2_ollama_local_training.py \\
      --identity configs/aat_v2_ollama_qwen_7b_volume_actor_identity_v1.json \\
      --authorization configs/aat_v2_ollama_volume_training_authorization_v1.json \\
      --authorize-volume-training --allow-live-ollama \\
      --base-url http://<pod>:11434 \\
      --opportunity-index <TRAINING or volume JSONL> \\
      --snapshot <macro snapshot JSONL> \\
      --subsample-receipt <volume_1000.receipt.json> \\
      --output-dir artifacts/aat_v2_ollama_volume_7b

Authorized gold slice (100 opportunities, full arms including E)::

    python scripts/run_aat_v2_ollama_local_training.py \\
      --identity configs/aat_v2_ollama_qwen_14b_runpod_actor_identity_v1.json \\
      --authorization configs/aat_v2_ollama_runpod_training_authorization_v1.json \\
      --authorize-runpod-training --allow-live-ollama --limit-opportunities 100 \\
      --base-url http://<pod>:11434 \\
      --opportunity-index <TRAINING or gold JSONL> \\
      --snapshot <macro snapshot JSONL> \\
      --subsample-receipt <gold_100.receipt.json> \\
      --output-dir artifacts/aat_v2_ollama_gold_14b

Optional volume thin-E (BCD only): same volume command plus
``--no-include-deliberation``. Gold keeps E.

``--authorize-volume-training`` does not authorize Terra, desktop
``qwen3.5:9b``, or gold ``qwen2.5:14b``. ``execution_authority`` stays
``ABSENT``. Holdout stays unused.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from athena_trading.aat_v2.ollama_identity import (
    CLI_AUTHORIZATION_FLAG,
    DEFAULT_MODEL_ID,
    RUNPOD_CLI_AUTHORIZATION_FLAG,
    RUNPOD_MODEL_ID,
    VOLUME_CLI_AUTHORIZATION_FLAG,
    VOLUME_MODEL_ID,
    AuthorizationError,
    IdentityError,
)
from athena_trading.aat_v2.ollama_training import (
    DEFAULT_MAX_CONCURRENT_CALLS,
    DEFAULT_SMOKE_LIMIT,
    MAX_CONCURRENT_CALLS_CEILING,
    OllamaTrainingError,
    fixture_transport,
    forbid_output_path,
    run_ollama_local_training,
)
from athena_trading.aat_v2.ollama_transport import OllamaTransportError

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = ROOT / "configs" / "aat_v2_training_plan_v2.json"
DEFAULT_PROTOCOL = ROOT / "configs" / "aat_v2_registered_protocol_v1.json"
DEFAULT_ASSIGNMENT = ROOT / "configs" / "aat_v2_dataset_assignment_v1.json"
DEFAULT_AMENDMENT = ROOT / "configs" / "aat_v2_e_arm_compact_schema_amendment_v1.json"
DEFAULT_IDENTITY = ROOT / "configs" / "aat_v2_ollama_qwen_actor_identity_v1.json"
DEFAULT_FIXTURE = ROOT / "configs" / "fixtures" / "ollama_qwen_training_v1.json"
RUNPOD_FIXTURE = ROOT / "configs" / "fixtures" / "ollama_qwen_14b_runpod_training_v1.json"
VOLUME_FIXTURE = ROOT / "configs" / "fixtures" / "ollama_qwen_7b_volume_training_v1.json"
DEFAULT_INDEX = ROOT / "configs" / "fixtures" / "aat_v2_training_opportunities_smoke_v1.jsonl"
DEFAULT_SNAPSHOT = ROOT / "configs" / "fixtures" / "aat_v2_training_snapshot_smoke_v1.jsonl"
DEFAULT_OUTPUT = ROOT / "artifacts" / "aat_v2_ollama_local_training_smoke"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--training-plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--assignment", type=Path, default=DEFAULT_ASSIGNMENT)
    parser.add_argument("--amendment", type=Path, default=DEFAULT_AMENDMENT)
    parser.add_argument("--identity", type=Path, default=DEFAULT_IDENTITY)
    parser.add_argument(
        "--authorization",
        type=Path,
        default=None,
        help="defaults to the authorization artifact matching --identity",
    )
    parser.add_argument("--opportunity-index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--opportunity-receipt", type=Path)
    parser.add_argument("--snapshot-receipt", type=Path)
    parser.add_argument(
        "--subsample-receipt",
        type=Path,
        help="hashed volume (1,000) or gold (100) subsample receipt",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--fixture", type=Path, default=None)
    parser.add_argument(
        "--model-id",
        default=None,
        help="must match the hashed identity (desktop default qwen3.5:9b; "
        "volume identity default qwen2.5:7b; gold identity default qwen2.5:14b)",
    )
    parser.add_argument(
        "--limit-opportunities",
        type=int,
        default=None,
        help="smoke/warmup cap; omit with --authorize-volume-training for the "
        "1,000-opportunity volume subsample, or with --authorize-runpod-training "
        "for the frozen 16,705 (not recommended)",
    )
    parser.add_argument(
        "--authorize-local-training",
        action="store_true",
        help="Nick's explicit local qwen3.5:9b TRAINING flag; required for the full desktop plan",
    )
    parser.add_argument(
        "--authorize-runpod-training",
        action="store_true",
        help="Nick's explicit RunPod qwen2.5:14b gold flag; does not authorize Terra, 9b, or 8b",
    )
    parser.add_argument(
        "--authorize-volume-training",
        action="store_true",
        help="Nick's explicit qwen2.5:7b volume-subsample flag; does not authorize Terra, 9b, or 14b",
    )
    parser.add_argument(
        "--allow-live-ollama",
        action="store_true",
        help="POST to Ollama; default is mocked fixture transport",
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--include-deliberation",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="volume default is full arms; --no-include-deliberation is thin-E (BCD only). Gold keeps E.",
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:11434",
        help="Ollama native /api/chat origin. Loopback is the desktop/SSH-tunnel "
        "default. Direct pod Ollama is http://<pod>:11434. A RunPod HTTPS proxy "
        "is https://<id>-11434.proxy.runpod.net (do not append :11434).",
    )
    parser.add_argument(
        "--max-concurrent-calls",
        type=int,
        default=DEFAULT_MAX_CONCURRENT_CALLS,
        help=(
            f"opportunity-level concurrency (default {DEFAULT_MAX_CONCURRENT_CALLS}, "
            f"max {MAX_CONCURRENT_CALLS_CEILING}). Ollama on one GPU serializes "
            "inference; 64-wide blasts are refused. Arm E stays sequential per row."
        ),
    )
    args = parser.parse_args(argv)

    try:
        forbid_output_path(args.output_dir)
        authorized = (
            args.authorize_local_training
            or args.authorize_runpod_training
            or args.authorize_volume_training
        )
        if authorized and args.limit_opportunities is None:
            limit = None
        elif args.limit_opportunities is not None:
            limit = args.limit_opportunities
        else:
            limit = DEFAULT_SMOKE_LIMIT
        identity_model = _identity_model_id(args.identity)
        model_id = args.model_id
        if args.allow_live_ollama:
            transport = None
        else:
            fixture = args.fixture
            if fixture is None:
                if identity_model == VOLUME_MODEL_ID:
                    fixture = VOLUME_FIXTURE
                elif identity_model == RUNPOD_MODEL_ID:
                    fixture = RUNPOD_FIXTURE
                else:
                    fixture = DEFAULT_FIXTURE
            transport = fixture_transport(fixture, model_id=identity_model)
        result = run_ollama_local_training(
            training_plan_path=args.training_plan,
            protocol_path=args.protocol,
            assignment_path=args.assignment,
            opportunity_index_path=args.opportunity_index,
            snapshot_path=args.snapshot,
            amendment_path=args.amendment,
            identity_path=args.identity,
            authorization_path=args.authorization,
            opportunity_receipt_path=args.opportunity_receipt,
            snapshot_receipt_path=args.snapshot_receipt,
            subsample_receipt_path=args.subsample_receipt,
            output_dir=args.output_dir,
            limit_opportunities=limit,
            authorize_local_training=args.authorize_local_training,
            authorize_runpod_training=args.authorize_runpod_training,
            authorize_volume_training=args.authorize_volume_training,
            allow_live=args.allow_live_ollama,
            transport=transport,
            model_id=model_id,
            include_deliberation=args.include_deliberation,
            resume=args.resume,
            base_url=args.base_url,
            max_concurrent_calls=args.max_concurrent_calls,
        )
    except (OllamaTrainingError, OllamaTransportError, IdentityError, AuthorizationError) as exc:
        print(json.dumps(_error_payload(exc), indent=2, sort_keys=True))
        return 1

    payload = dict(result)
    payload.pop("records", None)
    payload["ok"] = True
    payload["ledger_path"] = str(args.output_dir / "ledger.jsonl")
    payload["receipt_path"] = str(args.output_dir / "receipt.json")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if result["status"] != "LOCAL_TRAINING_INCOMPLETE" else 2


def _identity_model_id(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DEFAULT_MODEL_ID
    model_id = payload.get("model_id")
    return model_id if isinstance(model_id, str) and model_id else DEFAULT_MODEL_ID


def _error_payload(exc: BaseException) -> dict[str, object]:
    return {
        "ok": False,
        "error": str(exc),
        "execution_authority": "ABSENT",
        "sealed_holdout_consumed": False,
        "live_calls": getattr(exc, "live_calls", False),
        "authorize_local_training": getattr(exc, "authorize_local_training", False),
        "completed_calls": getattr(exc, "completed_calls", 0),
        "attempted_calls": getattr(exc, "attempted_calls", 0),
        "status": getattr(exc, "status", "LOCAL_TRAINING_SMOKE"),
        "authorization_cli_flag": CLI_AUTHORIZATION_FLAG,
        "runpod_authorization_cli_flag": RUNPOD_CLI_AUTHORIZATION_FLAG,
        "volume_authorization_cli_flag": VOLUME_CLI_AUTHORIZATION_FLAG,
        "registration_status": "REGISTERED_NOT_AUTHORIZED",
    }


if __name__ == "__main__":
    raise SystemExit(main())
