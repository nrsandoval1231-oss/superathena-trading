"""Always-on supervisor for the earnings paper book. Separate from athena-paper.

One process, one SQLite book, one Alpaca paper account that the intraday service
may also use. SIGTERM stops this process without confirming a flat account.
DAY orders (and legacy GTC orders) remain broker-managed until terminal. This
does not flatten or signal the intraday service; recover unfinished exposure.
"""
from __future__ import annotations

import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from ..intraday.live import NY


def heartbeat(state_dir: Path, status: str, **details) -> None:
    value = {"updated_at": datetime.now(UTC).isoformat(), "status": status, "arm": "earnings", **details}
    temporary = state_dir / "health.json.tmp"
    temporary.write_text(json.dumps(value) + "\n")
    temporary.replace(state_dir / "health.json")


def session_command(journal: Path, runner: Path) -> list[str]:
    return [
        sys.executable, str(runner), "--authority", "PAPER",
        "--journal", str(journal), "--run",
    ]


def main() -> int:
    state_dir = Path(os.environ.get("ATHENA_EARNINGS_STATE_DIR", "/var/lib/athena-earnings"))
    state_dir.mkdir(parents=True, exist_ok=True)
    runner = Path("scripts/run_athena_earnings.py").resolve()
    if not runner.is_file():
        raise ValueError("run the earnings supervisor from the repository root")
    journal = state_dir / "book.sqlite"
    stopping = False
    child = None

    def stop(signum, frame):
        nonlocal stopping
        stopping = True
        if child is not None and child.poll() is None:
            child.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with (state_dir / "supervisor.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError("another earnings supervisor holds this state directory") from exc
        while not stopping:
            try:
                required = ("TYPESAFE_API_KEY", "ALPACA_API_KEY", "ALPACA_API_SECRET")
                if any(not os.environ.get(key, "").strip() for key in required):
                    raise ValueError("earnings paper credentials are not configured")
                if not os.environ.get("ATHENA_EARNINGS_UNIVERSE", "").strip():
                    raise ValueError("ATHENA_EARNINGS_UNIVERSE is not configured")
                if stopping:
                    break
                child = subprocess.Popen(session_command(journal, runner))
                while child.poll() is None:
                    if stopping:
                        child.terminate()
                    heartbeat(
                        state_dir, "BOOK_RUNNING", journal=journal.name, pid=child.pid,
                        local_day=datetime.now(UTC).astimezone(NY).date().isoformat(),
                    )
                    time.sleep(5)
                heartbeat(state_dir, "BOOK_RETURNED", exit_code=child.returncode, journal=journal.name)
                child = None
            except Exception as exc:
                heartbeat(state_dir, "ERROR", error_type=type(exc).__name__, error=str(exc)[:200])
                print(json.dumps({"status": "ERROR", "arm": "earnings", "error": str(exc)[:200]}), flush=True)
            for _ in range(12):
                if stopping:
                    break
                time.sleep(5)
    heartbeat(state_dir, "STOPPED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
