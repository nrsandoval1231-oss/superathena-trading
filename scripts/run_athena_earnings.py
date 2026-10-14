"""Run the Earnings Adaptive paper book. LIVE is rejected. This process does not flatten on SIGTERM."""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path

from athena_trading.athena_adapter.jev import JEV_MODEL, JevDecisionEngine, request_json
from athena_trading.execution.authority import parse_authority, require_paper
from athena_trading.paper.earnings import (
    EarningsBook, EarningsPolicy, load_universe, policy_from_environment, resolve_restart_policy,
)
from athena_trading.paper.journal import PaperJournal
from athena_trading.paper.live import LivePaperAPI, transient_broker_failure


TRANSIENT_TICK_LIMIT = 3
TRANSIENT_TICK_BUDGET_SECONDS = 60.0


def _continue_after_transient(exc: BaseException, state: dict[str, float | int | None]) -> bool:
    """A short read outage retries without bypassing owned-exposure recovery."""
    if not transient_broker_failure(exc):
        return False
    count = int(state.get("count") or 0) + 1
    now = time.monotonic()
    started = state.get("started")
    if started is None:
        started = now
    state["count"] = count
    state["started"] = started
    return count < TRANSIENT_TICK_LIMIT and (now - float(started)) < TRANSIENT_TICK_BUDGET_SECONDS


def probe_models(api_key: str) -> None:
    models = request_json("GET", "https://api.typesafe.ai/v1/models", {
        "Authorization": "Bearer " + api_key,
    }, timeout=5)
    if not isinstance(models, dict) or not isinstance(models.get("models"), list):
        raise ValueError("TypeSafe model-list response is invalid")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authority", required=True, choices=["PAPER"])
    parser.add_argument("--feed", choices=["iex", "sip"], default=None)
    parser.add_argument("--journal", type=Path, required=True,
                        help="persistent earnings book; reuse it across sessions and restarts")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight", action="store_true", help="check connections without placing orders")
    mode.add_argument("--run", action="store_true", help="manage the paper book and adjudicate new entries")
    mode.add_argument("--flatten-owned", action="store_true",
                      help="close earnings-owned symbols only; does not touch athp- orders")
    args = parser.parse_args(argv)
    require_paper(parse_authority(args.authority))
    missing = [name for name in ("ALPACA_API_KEY", "ALPACA_API_SECRET", "ATHENA_EARNINGS_UNIVERSE")
               if not os.environ.get(name, "").strip()]
    if args.preflight and not os.environ.get("TYPESAFE_API_KEY", "").strip():
        missing.append("TYPESAFE_API_KEY")
    if missing:
        print(json.dumps({"ok": False, "arm": "earnings", "missing_environment": missing, "orders_submitted": 0}))
        return 2
    universe_path = os.environ["ATHENA_EARNINGS_UNIVERSE"]
    feed = args.feed or os.environ.get("ATHENA_FEED", "iex")
    journal = None
    book = None
    stopped = False

    def stop_requested(signum, frame):
        nonlocal stopped
        stopped = True

    try:
        names = load_universe(Path(universe_path))
        policy = policy_from_environment(universe_path, feed)
        broker = LivePaperAPI.from_env()
        journal = PaperJournal(args.journal)
        stored = journal.last("binding")
        if stored:
            applied = EarningsPolicy(**stored["binding"]["policy"])
            tightened = journal.last("policy_tightened")
            if isinstance(tightened, dict) and isinstance(tightened.get("policy"), dict):
                applied = EarningsPolicy(**tightened["policy"])
            policy = resolve_restart_policy(applied, policy)
        jev = None
        model_probe = None
        if args.preflight:
            api_key = os.environ["TYPESAFE_API_KEY"]
            jev = JevDecisionEngine(
                api_key, support_min=policy.support_min, confidence_min=policy.confidence_min,
            )
            probe_models(api_key)
        elif args.run:
            def model_probe() -> JevDecisionEngine:
                # Called only when the book is about to seek a new entry.
                api_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
                engine = JevDecisionEngine(
                    api_key, support_min=policy.support_min, confidence_min=policy.confidence_min,
                )
                probe_models(api_key)
                return engine
        book = EarningsBook(broker, jev, journal, policy, model_probe=model_probe)
        snapshot = broker.snapshot()
        if args.preflight:
            print(json.dumps({
                "ok": True, "mode": "PAPER", "arm": "EARNINGS_ADAPTIVE",
                "market_open": snapshot["clock"]["is_open"],
                "positions": len(snapshot["positions"]), "open_orders": len(snapshot["orders"]),
                "decision_model": JEV_MODEL, "universe": len(names), "feed": policy.feed,
                "per_trade_risk": policy.per_trade_risk, "total_risk": policy.total_risk,
                "max_notional_per_trade": policy.max_notional_per_trade,
                "max_notional_total": policy.max_notional_total,
                "orders_submitted": 0,
            }))
            return 0
        signal.signal(signal.SIGTERM, stop_requested)
        signal.signal(signal.SIGINT, stop_requested)
        if args.flatten_owned:
            book.request_flatten_owned()
        previous = None
        transient_ticks: dict[str, float | int | None] = {"count": 0, "started": None}
        while not stopped:
            try:
                status = book.tick()
            except Exception as exc:
                if _continue_after_transient(exc, transient_ticks):
                    print(json.dumps({
                        "mode": "PAPER", "arm": "earnings", "status": "TRANSIENT_TICK",
                        "error_type": type(exc).__name__, "error": str(exc)[:250],
                        "attempt": transient_ticks["count"],
                    }), file=sys.stderr, flush=True)
                    time.sleep(5)
                    continue
                raise
            transient_ticks["count"] = 0
            transient_ticks["started"] = None
            if status != previous:
                print(json.dumps({"mode": "PAPER", "arm": "earnings", "status": status}), flush=True)
                previous = status
            if args.flatten_owned and status == "POSITION_MISMATCH":
                return 2
            if args.flatten_owned and not book.open_trades():
                return 0
            time.sleep(5)
        # SIGTERM is not flat confirmation. The next start recovers any unfinished exposure.
        return 0
    except Exception as exc:
        print(json.dumps({
            "ok": False, "arm": "earnings", "error_type": type(exc).__name__, "error": str(exc)[:250],
        }), file=sys.stderr, flush=True)
        return 2
    finally:
        if journal is not None:
            journal.close()


if __name__ == "__main__":
    sys.exit(main())
