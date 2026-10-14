"""The universe script must load .env before it checks for credentials.

Regression: the credential guard originally ran before anything read .env, so
a correctly populated file still aborted the pull. The Massive adapter does its
own dotenv load, but only once a download is already in flight.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "freeze_orb_m_universe.py"


def _module():
    spec = importlib.util.spec_from_file_location("freeze_universe", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def clean_env(monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    return monkeypatch


def test_loads_the_key_from_a_dotenv_file(tmp_path, clean_env):
    env = tmp_path / ".env"
    env.write_text("# comment\nMASSIVE_API_KEY=abc123\nOTHER=x\n", encoding="utf-8")
    assert _module().load_env_file(env) is True
    assert os.environ["MASSIVE_API_KEY"] == "abc123"


def test_a_real_export_is_not_clobbered_by_the_file(tmp_path, clean_env):
    clean_env.setenv("MASSIVE_API_KEY", "from-shell")
    env = tmp_path / ".env"
    env.write_text("MASSIVE_API_KEY=from-file\n", encoding="utf-8")
    _module().load_env_file(env)
    assert os.environ["MASSIVE_API_KEY"] == "from-shell"


def test_surrounding_quotes_are_stripped(tmp_path, clean_env):
    env = tmp_path / ".env"
    env.write_text('MASSIVE_API_KEY="quoted"\n', encoding="utf-8")
    _module().load_env_file(env)
    assert os.environ["MASSIVE_API_KEY"] == "quoted"


def test_missing_file_reports_absence_without_raising(tmp_path, clean_env):
    assert _module().load_env_file(tmp_path / "absent.env") is False


def test_comment_lines_are_ignored(tmp_path, clean_env):
    env = tmp_path / ".env"
    env.write_text("#MASSIVE_API_KEY=commented\n", encoding="utf-8")
    _module().load_env_file(env)
    assert "MASSIVE_API_KEY" not in os.environ


# --- session statistics ----------------------------------------------------

def _bar(iso_utc: str, close: float, volume: float) -> str:
    import json
    return json.dumps({"event_at": iso_utc, "close": close, "volume": volume})


def _one_session(day: str, *, opening_volume: float, later_volume: float) -> list[str]:
    """A regular session plus premarket and after-hours bars, all stamped UTC.

    09:30 ET is 14:30 UTC in winter. After-hours bars past 19:00 ET land on the
    following UTC date, which is what previously split one session into two.
    """
    rows = [_bar(f"{day}T09:00:00+00:00", 100.0, 500.0)]          # 04:00 ET premarket
    rows += [_bar(f"{day}T14:3{m}:00+00:00", 100.0, opening_volume / 5) for m in range(5)]
    rows += [_bar(f"{day}T18:00:00+00:00", 100.0, later_volume)]   # 13:00 ET midday
    rows.append(_bar(f"{day}T23:30:00+00:00", 100.0, 700.0))       # 18:30 ET after hours
    return rows


def test_after_hours_bars_do_not_create_a_phantom_session():
    module = _module()
    rows = _one_session("2023-12-05", opening_volume=1000.0, later_volume=2000.0)
    # A bar at 01:00 UTC the next day is still the 5 December session locally,
    # and being outside regular hours must not register as 6 December either.
    rows.append(_bar("2023-12-06T01:00:00+00:00", 100.0, 300.0))
    *_, sessions = module._session_statistics(rows)
    assert sessions == 1


def test_opening_volume_uses_the_regular_open_not_the_first_bars_of_the_day():
    module = _module()
    rows = _one_session("2023-12-05", opening_volume=1000.0, later_volume=2000.0)
    *_, opening, _ = module._session_statistics(rows)
    # 1000 across the 09:30-09:45 ET window; the 04:00 premarket bar contributes
    # nothing, and midday volume is excluded.
    assert opening == 1000.0


def test_extended_hours_volume_is_excluded_from_dollar_volume():
    module = _module()
    rows = _one_session("2023-12-05", opening_volume=1000.0, later_volume=2000.0)
    _, dollars, _, _ = module._session_statistics(rows)
    assert dollars == 100.0 * 3000.0  # opening 1000 + midday 2000, no 500 or 700


def test_sessions_are_counted_per_local_trading_day():
    module = _module()
    rows = (_one_session("2023-12-05", opening_volume=1000.0, later_volume=2000.0)
            + _one_session("2023-12-06", opening_volume=1500.0, later_volume=2500.0))
    *_, sessions = module._session_statistics(rows)
    assert sessions == 2


def test_no_regular_hours_bars_yields_zeroes_rather_than_raising():
    premarket_only = [_bar("2023-12-05T09:00:00+00:00", 1.0, 1.0)]
    assert _module()._session_statistics(premarket_only) == (0.0, 0.0, 0.0, 0)


def test_the_opening_window_comes_from_the_constitution():
    """Restating 15 here would let this drift from the window actually traded."""
    from athena_trading.orb_m.constitution import Constitution
    assert _module().OPENING_MINUTES == Constitution().opening_minutes


def test_the_opening_range_excludes_the_bar_that_closes_it():
    """09:45 ET is the freeze point, so the 09:45 bar belongs to what follows."""
    rows = [_bar("2023-12-05T14:30:00+00:00", 100.0, 7.0),   # 09:30 ET
            _bar("2023-12-05T14:44:00+00:00", 100.0, 3.0),   # 09:44 ET, inside
            _bar("2023-12-05T14:45:00+00:00", 100.0, 99.0)]  # 09:45 ET, outside
    *_, opening, _ = _module()._session_statistics(rows)
    assert opening == 10.0


def test_daylight_saving_is_honoured_on_both_sides_of_the_change():
    """09:30 ET is 13:30 UTC under EDT but 14:30 UTC under EST.

    Each day carries a premarket block, so a fixed-offset reading would pick
    premarket volume for one of the two sessions rather than the opening range.
    """
    rows = [_bar(f"2023-10-27T08:{m:02d}:00+00:00", 100.0, 100.0) for m in range(15)]
    rows += [_bar("2023-10-27T13:30:00+00:00", 100.0, 4.0)]   # 09:30 EDT
    rows += [_bar(f"2023-12-05T09:{m:02d}:00+00:00", 100.0, 100.0) for m in range(15)]
    rows += [_bar("2023-12-05T14:30:00+00:00", 100.0, 6.0)]   # 09:30 EST
    *_, opening, sessions = _module()._session_statistics(rows)
    assert sessions == 2
    assert opening == 5.0


def test_a_session_that_traded_nothing_at_the_open_contributes_zero():
    """A dead open is signal for a liquidity ranking, not a missing value."""
    rows = [_bar("2023-12-05T16:00:00+00:00", 100.0, 42.0)]  # 11:00 ET only
    *_, opening, sessions = _module()._session_statistics(rows)
    assert sessions == 1
    assert opening == 0.0
