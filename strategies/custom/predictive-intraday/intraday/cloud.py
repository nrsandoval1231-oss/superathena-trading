"""Always-on supervisor for the existing active paper runner; one process/account."""
from __future__ import annotations

import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from ..paper.journal import PaperJournal
from ..paper.learning import maintain
from .live import LivePaperAPI, PilotPolicy, policy_from_environment, timestamp, NY


@dataclass(frozen=True)
class SessionTask:
    path: Path
    recovery: bool = False
    saved_policy: dict | None = None


def _reservation_closed(journal: PaperJournal) -> bool:
    """A flat close, or a reserved id Alpaca never created. Neither is resubmitted."""
    return bool(journal.last("flat_confirmed") or journal.last("entry_not_created"))


def next_session(state_dir: Path, today: date) -> SessionTask | None:
    """Never roll past an unresolved entry or a corrupt journal."""
    unresolved = []
    current_finished = False
    current = state_dir / f"{today.isoformat()}.sqlite"
    for path in sorted(state_dir.glob("*.sqlite")):
        journal = PaperJournal(path)
        try:
            entry = journal.last("entry_intent")
            closed = _reservation_closed(journal)
            if entry and not closed:
                binding = journal.last("binding")
                if binding is None:
                    raise ValueError("unresolved entry has no account/policy binding")
                unresolved.append(SessionTask(path, True, binding["binding"]["policy"]))
            if path == current and (
                journal.last("session_complete") or closed
                or (journal.last("halt") and not entry)
            ):
                current_finished = True
        finally:
            journal.close()
    if len(unresolved) > 1:
        raise ValueError("multiple unresolved sessions need reconciliation; new entries blocked")
    if unresolved:
        return unresolved[0]
    return None if current_finished else SessionTask(current)


def session_command(task: SessionTask, policy: PilotPolicy, runner: Path) -> list[str]:
    saved = task.saved_policy or {}
    symbol, feed = saved.get("symbol", policy.symbol), saved.get("feed", policy.feed)
    command = [sys.executable, str(runner), "--authority", "PAPER", "--symbol", symbol,
               "--feed", feed, "--journal", str(task.path), "--run"]
    if not task.recovery:
        command.extend(["--session-date", task.path.stem])
    return command


def heartbeat(state_dir: Path, status: str, **details) -> None:
    value = {"updated_at": datetime.now(UTC).isoformat(), "status": status, **details}
    temporary = state_dir / "health.json.tmp"
    temporary.write_text(json.dumps(value) + "\n")
    temporary.replace(state_dir / "health.json")


def main() -> int:
    state_dir = Path(os.environ.get("ATHENA_STATE_DIR", "/var/lib/athena"))
    state_dir.mkdir(parents=True, exist_ok=True)
    runner = Path("scripts/run_athena_paper.py").resolve()
    if not runner.is_file():
        raise ValueError("run the cloud supervisor from the repository root")
    policy = policy_from_environment(os.environ.get("ATHENA_SYMBOL", ""),
                                     os.environ.get("ATHENA_FEED", "iex"))
    stopping = False
    child = None

    def stop(signum, frame):
        nonlocal stopping
        stopping = True
        if child is not None and child.poll() is None:
            child.terminate()  # child latches halt and performs broker cleanup

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with (state_dir / "supervisor.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        while not stopping:
            try:
                # Inspect recovery first. Hosted-model credentials are unnecessary for exits.
                local_day = datetime.now(UTC).astimezone(NY).date()
                task = next_session(state_dir, local_day)
                broker = LivePaperAPI.from_env()
                clock = broker.call("GET", "/v2/clock")
                broker_day = timestamp(clock["timestamp"]).astimezone(NY).date()
                if broker_day != local_day:
                    task = next_session(state_dir, broker_day)
                if task is None or not task.recovery:
                    maintain(state_dir, timestamp(clock["timestamp"]))
                if task is None:
                    heartbeat(state_dir, "SESSION_FINISHED_OR_HALTED", session=str(broker_day))
                elif not task.recovery and not clock["is_open"]:
                    heartbeat(state_dir, "WAITING_FOR_MARKET", next_open=clock.get("next_open"))
                else:
                    if not task.recovery and any(not os.environ.get(k, "").strip()
                                                for k in ("TYPESAFE_API_KEY",)):
                        raise ValueError("hosted model credentials are not configured")
                    if stopping:
                        break
                    child = subprocess.Popen(session_command(task, policy, runner))
                    while child.poll() is None:
                        if stopping:
                            child.terminate()
                        heartbeat(state_dir, "RECOVERING" if task.recovery else "SESSION_RUNNING",
                                  journal=task.path.name, pid=child.pid)
                        time.sleep(5)
                    heartbeat(state_dir, "SESSION_RETURNED", exit_code=child.returncode,
                              journal=task.path.name)
                    child = None
            except Exception as exc:
                heartbeat(state_dir, "ERROR", error_type=type(exc).__name__, error=str(exc)[:200])
                print(json.dumps({"status": "ERROR", "error": str(exc)[:200]}), flush=True)
            for _ in range(12):
                if stopping:
                    break
                time.sleep(5)
    heartbeat(state_dir, "STOPPED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
