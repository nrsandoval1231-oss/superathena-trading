"""Massive HTTP retry — transient only; permanent 4xx fail fast."""
from __future__ import annotations

from urllib.error import HTTPError
from io import BytesIO

import pytest

from athena_trading.market_data import massive


class _FakeHTTPError(HTTPError):
    def __init__(self, code: int):
        super().__init__(url="https://example.test", code=code, msg="err",
                         hdrs=None, fp=BytesIO())


def test_permanent_http_status_fails_without_retry(monkeypatch):
    calls = {"n": 0}

    def boom(url, timeout=60):  # noqa: ARG001
        calls["n"] += 1
        raise _FakeHTTPError(404)

    monkeypatch.setattr(massive, "urlopen", boom)
    with pytest.raises(RuntimeError, match="HTTP 404"):
        massive._request_with_retry("https://example.test/x", max_retries=3,
                                   retry_backoff_seconds=0)
    assert calls["n"] == 1


def test_transient_http_status_is_retried(monkeypatch):
    calls = {"n": 0}

    def boom(url, timeout=60):  # noqa: ARG001
        calls["n"] += 1
        raise _FakeHTTPError(503)

    monkeypatch.setattr(massive, "urlopen", boom)
    monkeypatch.setattr(massive.time, "sleep", lambda _s: None)
    with pytest.raises(RuntimeError, match="after retries"):
        massive._request_with_retry("https://example.test/x", max_retries=2,
                                   retry_backoff_seconds=0)
    assert calls["n"] == 3
