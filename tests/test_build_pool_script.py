"""The candidate pool builder must stay point-in-time and outcome-blind.

The failure modes worth guarding are all silent ones: a holiday placeholder
counted as a session relaxes the coverage floor, an ETF left in the ranking
displaces real candidates, and a lookback that reaches into the campaign
produces a pool that has seen its own outcomes.  None of those raise.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_orb_m_pool.py"


def _module():
    spec = importlib.util.spec_from_file_location("build_pool", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _session(path: Path, rows: list[tuple[str, float, float]]) -> None:
    """Write one grouped daily file; an empty row list is a holiday placeholder."""
    table = pa.table({
        "ticker": pa.array([r[0] for r in rows], pa.string()),
        "c": pa.array([r[1] for r in rows], pa.float64()),
        "v": pa.array([r[2] for r in rows], pa.float64()),
    })
    pq.write_table(table, path)


@pytest.fixture
def grouped(tmp_path):
    root = tmp_path / "grouped"
    root.mkdir()
    return root


# --- session selection --------------------------------------------------------

def test_holiday_placeholders_are_not_counted_as_sessions(grouped):
    _session(grouped / "2023-12-21.parquet", [("AAA", 10.0, 2_000_000.0)])
    _session(grouped / "2023-12-22.parquet", [("AAA", 10.0, 2_000_000.0)])
    _session(grouped / "2023-12-25.parquet", [])  # Christmas
    module = _module()
    chosen = module.session_files(grouped, module._iso("2023-12-01"), module._iso("2023-12-31"))
    assert [p.stem for p in chosen] == ["2023-12-21", "2023-12-22"]


def test_files_outside_the_window_are_ignored(grouped):
    for day in ("2023-11-30", "2023-12-01", "2024-01-02"):
        _session(grouped / f"{day}.parquet", [("AAA", 10.0, 2_000_000.0)])
    module = _module()
    chosen = module.session_files(grouped, module._iso("2023-12-01"), module._iso("2023-12-31"))
    assert [p.stem for p in chosen] == ["2023-12-01"]


def test_non_date_filenames_are_skipped(grouped):
    _session(grouped / "2023-12-01.parquet", [("AAA", 10.0, 2_000_000.0)])
    _session(grouped / "notes.parquet", [("AAA", 10.0, 2_000_000.0)])
    module = _module()
    chosen = module.session_files(grouped, module._iso("2023-12-01"), module._iso("2023-12-31"))
    assert [p.stem for p in chosen] == ["2023-12-01"]


def test_observations_accumulate_per_symbol(grouped):
    _session(grouped / "2023-12-01.parquet", [("AAA", 10.0, 1.0), ("BBB", 20.0, 2.0)])
    _session(grouped / "2023-12-04.parquet", [("AAA", 11.0, 3.0)])
    module = _module()
    paths = module.session_files(grouped, module._iso("2023-12-01"), module._iso("2023-12-31"))
    observed = module.daily_observations(paths)
    assert observed["AAA"] == [(10.0, 1.0), (11.0, 3.0)]
    assert observed["BBB"] == [(20.0, 2.0)]


# --- the funnel ---------------------------------------------------------------

def _args(grouped, tmp_path, **overrides):
    defaults = dict(
        grouped_root=str(grouped), lookback_end="2023-12-29",
        lookback_calendar_days=120, campaign_start="2024-01-02",
        pool_size=10, min_session_coverage=0.95,
        output=str(tmp_path / "pool.txt"), manifest=str(tmp_path / "pool.json"),
        env_file=str(tmp_path / "absent.env"),
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _run(module, grouped, tmp_path, monkeypatch, *, reference, **overrides):
    monkeypatch.setenv("POLYGON_API_KEY", "test-key")
    monkeypatch.setattr(module, "common_stock_symbols", lambda **_: set(reference))
    module.build(_args(grouped, tmp_path, **overrides))
    pool = [line for line in Path(tmp_path / "pool.txt").read_text().splitlines()
            if line and not line.startswith("#")]
    manifest = json.loads(Path(tmp_path / "pool.json").read_text())
    return pool, manifest


def _populate(grouped, rows_by_symbol, sessions=20):
    days = [f"2023-12-{day:02d}" for day in range(1, sessions + 1)]
    for day in days:
        _session(grouped / f"{day}.parquet",
                 [(s, c, v) for s, (c, v) in rows_by_symbol.items()])


def test_symbols_absent_from_the_reference_are_dropped(grouped, tmp_path, monkeypatch):
    """An ETF outranks most common stock on dollar volume; the type filter is
    the only thing keeping it out."""
    _populate(grouped, {"SPY": (450.0, 80_000_000.0), "AAA": (10.0, 2_000_000.0)})
    module = _module()
    pool, manifest = _run(module, grouped, tmp_path, monkeypatch, reference={"AAA"})
    assert pool == ["AAA"]
    assert manifest["funnel"]["with_session_coverage"] == 2
    assert manifest["funnel"]["typed_common_stock"] == 1


def test_the_price_floor_is_applied(grouped, tmp_path, monkeypatch):
    _populate(grouped, {"PENNY": (2.0, 90_000_000.0), "AAA": (10.0, 2_000_000.0)})
    module = _module()
    pool, _ = _run(module, grouped, tmp_path, monkeypatch, reference={"PENNY", "AAA"})
    assert pool == ["AAA"]


def test_the_volume_floor_is_applied(grouped, tmp_path, monkeypatch):
    _populate(grouped, {"THIN": (900.0, 900_000.0), "AAA": (10.0, 2_000_000.0)})
    module = _module()
    pool, _ = _run(module, grouped, tmp_path, monkeypatch, reference={"THIN", "AAA"})
    assert pool == ["AAA"]


def test_a_symbol_that_stopped_trading_mid_window_fails_coverage(grouped, tmp_path,
                                                                 monkeypatch):
    _populate(grouped, {"AAA": (10.0, 2_000_000.0)}, sessions=20)
    for day in range(1, 6):
        _session(grouped / f"2023-12-{day:02d}.parquet",
                 [("AAA", 10.0, 2_000_000.0), ("GONE", 10.0, 9_000_000.0)])
    module = _module()
    pool, manifest = _run(module, grouped, tmp_path, monkeypatch, reference={"AAA", "GONE"})
    assert pool == ["AAA"]
    assert manifest["funnel"]["tickers_seen"] == 2


def test_ranking_is_by_dollar_volume_and_ties_break_on_symbol(grouped, tmp_path,
                                                              monkeypatch):
    _populate(grouped, {"LOW": (10.0, 2_000_000.0), "HIGH": (50.0, 5_000_000.0),
                        "TIEB": (20.0, 5_000_000.0), "TIEA": (20.0, 5_000_000.0)})
    module = _module()
    pool, _ = _run(module, grouped, tmp_path, monkeypatch,
                   reference={"LOW", "HIGH", "TIEA", "TIEB"})
    assert pool == ["HIGH", "TIEA", "TIEB", "LOW"]


def test_pool_size_truncates_and_is_recorded(grouped, tmp_path, monkeypatch):
    _populate(grouped, {"AAA": (10.0, 9_000_000.0), "BBB": (10.0, 8_000_000.0),
                        "CCC": (10.0, 7_000_000.0)})
    module = _module()
    pool, manifest = _run(module, grouped, tmp_path, monkeypatch,
                          reference={"AAA", "BBB", "CCC"}, pool_size=2)
    assert pool == ["AAA", "BBB"]
    assert manifest["funnel"]["passing_price_and_adv_floors"] == 3
    assert manifest["funnel"]["written_to_pool"] == 2


# --- provenance and immutability ----------------------------------------------

def test_the_manifest_declares_point_in_time_without_survivorship_bias(
        grouped, tmp_path, monkeypatch):
    _populate(grouped, {"AAA": (10.0, 2_000_000.0)})
    module = _module()
    _, manifest = _run(module, grouped, tmp_path, monkeypatch, reference={"AAA"})
    assert manifest["provenance"] == "POINT_IN_TIME"
    assert manifest["carries_survivorship_bias"] is False
    assert manifest["reference"]["as_of"] == "2023-12-29"
    assert manifest["sessions_observed"] == 20


def test_every_consumed_file_is_hashed_into_the_manifest(grouped, tmp_path, monkeypatch):
    _populate(grouped, {"AAA": (10.0, 2_000_000.0)}, sessions=3)
    module = _module()
    _, manifest = _run(module, grouped, tmp_path, monkeypatch, reference={"AAA"})
    assert len(manifest["grouped_sources"]) == 3
    assert all(len(s["sha256"]) == 64 for s in manifest["grouped_sources"])
    assert len(manifest["grouped_corpus_sha256"]) == 64


def test_the_corpus_hash_changes_when_a_source_byte_changes(grouped, tmp_path,
                                                            monkeypatch):
    _populate(grouped, {"AAA": (10.0, 2_000_000.0)}, sessions=3)
    module = _module()
    _, first = _run(module, grouped, tmp_path, monkeypatch, reference={"AAA"})
    _session(grouped / "2023-12-02.parquet", [("AAA", 10.0, 2_000_001.0)])
    second_dir = tmp_path / "again"
    second_dir.mkdir()
    _, second = _run(module, grouped, second_dir, monkeypatch, reference={"AAA"},
                     output=str(second_dir / "pool.txt"),
                     manifest=str(second_dir / "pool.json"))
    assert first["grouped_corpus_sha256"] != second["grouped_corpus_sha256"]


def test_a_lookback_reaching_into_the_campaign_is_refused(grouped, tmp_path,
                                                          monkeypatch):
    _populate(grouped, {"AAA": (10.0, 2_000_000.0)})
    module = _module()
    monkeypatch.setenv("POLYGON_API_KEY", "test-key")
    monkeypatch.setattr(module, "common_stock_symbols", lambda **_: {"AAA"})
    with pytest.raises(SystemExit, match="not strictly before campaign start"):
        module.build(_args(grouped, tmp_path, lookback_end="2024-01-05"))


def test_a_lookback_ending_on_the_campaign_open_is_refused(grouped, tmp_path,
                                                           monkeypatch):
    _populate(grouped, {"AAA": (10.0, 2_000_000.0)})
    module = _module()
    monkeypatch.setenv("POLYGON_API_KEY", "test-key")
    monkeypatch.setattr(module, "common_stock_symbols", lambda **_: {"AAA"})
    with pytest.raises(SystemExit, match="not strictly before campaign start"):
        module.build(_args(grouped, tmp_path, lookback_end="2024-01-02"))


def test_an_existing_pool_file_is_never_clobbered(grouped, tmp_path, monkeypatch):
    _populate(grouped, {"AAA": (10.0, 2_000_000.0)})
    (tmp_path / "pool.txt").write_text("PRIOR\n", encoding="utf-8")
    module = _module()
    monkeypatch.setenv("POLYGON_API_KEY", "test-key")
    monkeypatch.setattr(module, "common_stock_symbols", lambda **_: {"AAA"})
    with pytest.raises(SystemExit, match="frozen artifacts are immutable"):
        module.build(_args(grouped, tmp_path))
    assert (tmp_path / "pool.txt").read_text() == "PRIOR\n"


def test_a_missing_credential_is_reported_before_any_work(grouped, tmp_path, monkeypatch):
    _populate(grouped, {"AAA": (10.0, 2_000_000.0)})
    module = _module()
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="POLYGON_API_KEY"):
        module.build(_args(grouped, tmp_path))


def test_a_window_with_no_sessions_is_reported(grouped, tmp_path, monkeypatch):
    _session(grouped / "2023-12-25.parquet", [])
    module = _module()
    monkeypatch.setenv("POLYGON_API_KEY", "test-key")
    with pytest.raises(SystemExit, match="no non-empty grouped sessions"):
        module.build(_args(grouped, tmp_path))
