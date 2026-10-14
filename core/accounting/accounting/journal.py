"""Single-writer, durable paper-session events. Recover by replaying verified rows."""
from __future__ import annotations

import fcntl
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from ..athena_adapter.contracts import canonical_hash, canonical_json


class PaperJournal:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = path.with_suffix(path.suffix + ".lock").open("a")
        try:
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._lock.close()
            raise ValueError("another paper runner holds this journal") from None
        self.db = sqlite3.connect(path)
        os.chmod(path, 0o600)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS events "
            "(seq INTEGER PRIMARY KEY, payload TEXT NOT NULL, previous TEXT NOT NULL, "
            "digest TEXT NOT NULL)"
        )
        self.db.commit()
        self.events: list[dict[str, Any]] = []
        self.head = "0" * 64
        self.checkpoint = path.with_suffix(path.suffix + ".checkpoint")
        try:
            for seq, payload, previous, digest in self.db.execute(
                "SELECT seq, payload, previous, digest FROM events ORDER BY seq"
            ):
                event = json.loads(payload)
                expected = canonical_hash({"seq": seq, "event": event, "previous": previous})
                if seq != len(self.events) + 1 or previous != self.head or digest != expected:
                    raise ValueError("paper journal integrity check failed")
                self.events.append(event)
                self.head = digest
            self.db.execute("CREATE TABLE IF NOT EXISTS journal_meta (checkpointed INTEGER)")
            checkpointed = self.db.execute("SELECT checkpointed FROM journal_meta").fetchone()
            if self.checkpoint.exists():
                anchor = json.loads(self.checkpoint.read_text())
                seq = anchor["seq"]
                if type(seq) is not int or not 0 <= seq <= len(self.events):
                    raise ValueError("paper journal was truncated past its checkpoint")
                row = self.db.execute("SELECT digest FROM events WHERE seq=?", (seq,)).fetchone()
                digest = row[0] if row else "0" * 64
                if anchor["digest"] != digest or len(self.events) - seq > 1:
                    raise ValueError("paper journal checkpoint mismatch")
            elif checkpointed:
                raise ValueError("paper journal checkpoint is missing")
            # A one-row gap is the recoverable DB-commit / checkpoint-write crash window.
            # Old journals establish an anchor at their first verified migration read.
            self._checkpoint()
            if not checkpointed:
                with self.db:
                    self.db.execute("INSERT INTO journal_meta VALUES (1)")
        except Exception:
            self.close()
            raise

    def append(self, kind: str, **data: Any) -> None:
        event = json.loads(canonical_json({"kind": kind, **data}))
        seq = len(self.events) + 1
        digest = canonical_hash({"seq": seq, "event": event, "previous": self.head})
        with self.db:
            self.db.execute(
                "INSERT INTO events VALUES (?, ?, ?, ?)",
                (seq, canonical_json(event), self.head, digest),
            )
        self.events.append(event)
        self.head = digest
        self._checkpoint()

    def _checkpoint(self) -> None:
        temporary = self.checkpoint.with_suffix(self.checkpoint.suffix + ".tmp")
        with temporary.open("w") as stream:
            os.chmod(temporary, 0o600)
            json.dump({"seq": len(self.events), "digest": self.head}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.checkpoint)
        descriptor = os.open(self.checkpoint.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def last(self, kind: str) -> dict[str, Any] | None:
        return next((event for event in reversed(self.events) if event["kind"] == kind), None)

    def close(self) -> None:
        self.db.close()
        self._lock.close()
