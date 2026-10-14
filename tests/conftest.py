"""Keep cross-process paper coordination inside each disposable test directory."""
import pytest


@pytest.fixture(autouse=True)
def isolated_shared_risk_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("ATHENA_SHARED_RISK_DIR", str(tmp_path / "shared-risk"))
    monkeypatch.setenv("ATHENA_STATE_DIR", str(tmp_path / "intraday"))
    monkeypatch.setenv("ATHENA_EARNINGS_STATE_DIR", str(tmp_path / "earnings"))
