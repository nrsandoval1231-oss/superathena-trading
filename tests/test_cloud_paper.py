from __future__ import annotations

import json
import signal
import sqlite3
from dataclasses import asdict
from datetime import date
from pathlib import Path

import pytest

from athena_trading.athena_adapter.jev import JEV_MODEL
from athena_trading.paper import cloud
from athena_trading.paper.journal import PaperJournal
from athena_trading.paper.live import PilotPolicy


def journal_at(directory, day, *, entry=False, finish=None, model=JEV_MODEL):
    path = directory / f"{day}.sqlite"
    journal = PaperJournal(path)
    journal.append("binding", binding={"account_id": "fixture-account", "policy": asdict(
        PilotPolicy("AAPL", feed="sip", actor_model=model))})
    if entry:
        journal.append("entry_intent", session=day, order={"client_order_id": "fixture-entry"})
    if finish:
        journal.append(finish, reason="fixture")
    journal.close()
    return path


@pytest.mark.parametrize("finish", ["session_complete", "halt", "flat_confirmed"])
def test_completed_or_halted_session_does_not_restart_that_day(tmp_path, finish):
    journal_at(tmp_path, "2026-09-24", finish=finish)
    assert cloud.next_session(tmp_path, date(2026, 9, 24)) is None
    tomorrow = cloud.next_session(tmp_path, date(2026, 9, 25))
    assert tomorrow == cloud.SessionTask(tmp_path / "2026-09-25.sqlite")


def test_never_created_order_is_terminal_and_a_single_miss_is_not(tmp_path):
    missed = journal_at(tmp_path, "2026-09-23", entry=True)
    journal = PaperJournal(missed)
    journal.append("order_lookup_miss", reason="BROKER_ORDER_NOT_FOUND")
    journal.close()
    task = cloud.next_session(tmp_path, date(2026, 9, 24))
    assert task.recovery and task.path == missed
    journal = PaperJournal(missed)
    journal.append("entry_not_created", reason="BROKER_ORDER_NOT_FOUND")
    journal.close()
    assert cloud.next_session(tmp_path, date(2026, 9, 24)) == cloud.SessionTask(
        tmp_path / "2026-09-24.sqlite",
    )


def test_unfinished_entry_blocks_new_day_even_if_completion_was_recorded(tmp_path):
    old = journal_at(tmp_path, "2026-09-23", entry=True, finish="session_complete")
    journal_at(tmp_path, "2026-09-24", finish="halt")
    task = cloud.next_session(tmp_path, date(2026, 9, 24))
    assert task.recovery and task.path == old
    assert task.saved_policy["symbol"] == "AAPL"
    journal = PaperJournal(old)
    journal.append("flat_confirmed")
    journal.close()
    assert cloud.next_session(tmp_path, date(2026, 9, 24)) is None


def test_multiple_unfinished_entries_block_all_new_entries(tmp_path):
    journal_at(tmp_path, "2026-09-23", entry=True)
    journal_at(tmp_path, "2026-09-24", entry=True)
    with pytest.raises(ValueError, match="multiple unresolved"):
        cloud.next_session(tmp_path, date(2026, 9, 25))


def test_corrupt_old_journal_blocks_rollover(tmp_path):
    path = journal_at(tmp_path, "2026-09-23", finish="flat_confirmed")
    with sqlite3.connect(path) as db:
        db.execute("UPDATE events SET digest = 'changed' WHERE seq = 1")
    with pytest.raises(ValueError, match="integrity"):
        cloud.next_session(tmp_path, date(2026, 9, 24))


def test_recovery_preserves_old_symbol_feed_and_actor_without_model_access(tmp_path):
    path = journal_at(tmp_path, "2026-09-23", entry=True, model="qwen2.5:7b")
    task = cloud.next_session(tmp_path, date(2026, 9, 24))
    command = cloud.session_command(task, PilotPolicy("MSFT"), Path("runner.py"))
    assert command[2:] == ["--authority", "PAPER", "--symbol", "AAPL", "--feed", "sip",
                           "--journal", str(path), "--run"]


def test_cloud_starts_new_session_without_actor_dependency(tmp_path):
    task = cloud.next_session(tmp_path, date(2026, 9, 24))
    command = cloud.session_command(task, PilotPolicy("AAPL"), Path("runner.py"))
    assert command[-2:] == ["--session-date", "2026-09-24"]
    assert "--actor" not in command


def test_cloud_shutdown_between_clock_and_spawn_never_starts_session(tmp_path, monkeypatch):
    handlers, started = {}, []
    monkeypatch.setenv("ATHENA_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("ATHENA_SYMBOL", "AAPL")
    monkeypatch.setenv("OPENAI_API_KEY", "fixture")
    monkeypatch.setenv("TYPESAFE_API_KEY", "fixture")
    monkeypatch.setattr(cloud.signal, "signal", lambda sig, handler: handlers.update({sig: handler}))
    monkeypatch.setattr(cloud.subprocess, "Popen", lambda *a: started.append(a))

    class Broker:
        def call(self, *args):
            handlers[signal.SIGTERM](signal.SIGTERM, None)
            return {"timestamp": "2026-09-24T14:00:00Z", "is_open": True}

    monkeypatch.setattr(cloud.LivePaperAPI, "from_env", lambda: Broker())
    assert cloud.main() == 0
    assert not started
    assert json.loads((tmp_path / "health.json").read_text())["status"] == "STOPPED"


def test_cloud_recovers_outside_market_hours_without_model_keys(tmp_path, monkeypatch):
    journal_at(tmp_path, "2026-09-23", entry=True)
    handlers, started = {}, []
    monkeypatch.setenv("ATHENA_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("ATHENA_SYMBOL", "AAPL")
    for key in ("OPENAI_API_KEY", "TYPESAFE_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(cloud.signal, "signal", lambda sig, handler: handlers.update({sig: handler}))

    class Broker:
        def call(self, *args):
            return {"timestamp": "2026-09-24T00:00:00Z", "is_open": False}

    class Child:
        returncode = 0
        pid = 123

        def poll(self):
            return 0

    def spawn(command):
        started.append(command)
        handlers[signal.SIGTERM](signal.SIGTERM, None)
        return Child()

    monkeypatch.setattr(cloud.LivePaperAPI, "from_env", lambda: Broker())
    monkeypatch.setattr(cloud.subprocess, "Popen", spawn)
    assert cloud.main() == 0
    assert len(started) == 1
    assert "2026-09-23.sqlite" in started[0][-2]


def test_heartbeat_replaces_complete_json(tmp_path):
    cloud.heartbeat(tmp_path, "WAITING_FOR_MARKET", next_open="fixture")
    cloud.heartbeat(tmp_path, "RECOVERING", journal="previous.sqlite")
    result = json.loads((tmp_path / "health.json").read_text())
    assert result["status"] == "RECOVERING" and result["journal"] == "previous.sqlite"
    assert "next_open" not in result and result["updated_at"].endswith("+00:00")
    assert not (tmp_path / "health.json.tmp").exists()
