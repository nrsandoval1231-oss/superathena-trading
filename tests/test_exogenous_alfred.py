import json
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from athena_trading.exogenous import (
    ExogenousContractError,
    IngestError,
    assert_stable_availability,
    normalize,
    visible_records,
)
from athena_trading.exogenous.alfred import (
    API_ROOT,
    OBSERVATIONS_PATH,
    AlfredError,
    MissingAlfredCredentialsError,
    alfred_adapter,
    annotate_alfred_revisions,
    api_key_from_env,
    fetch_alfred_observations,
    fetch_alfred_vintage_dates,
    stamp_scheduled_availability,
)

EASTERN = ZoneInfo("America/New_York")
FIXTURE = Path("configs/fixtures/alfred_vintage_observations_v1.json")
# 09:45 ET on the January CPI print day, and on the later revision day.
PRINT_DECISION = datetime(2026, 2, 12, 9, 45, tzinfo=EASTERN)
REVISION_DECISION = datetime(2026, 3, 12, 9, 45, tzinfo=EASTERN)


def _fixture_payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _raw_rows(payload=None):
    envelope = payload if payload is not None else _fixture_payload()
    return [
        {**observation, "series_id": envelope["series_id"], "category": envelope["category"]}
        for observation in envelope["observations"]
    ]


def _prepared_rows(payload=None):
    return stamp_scheduled_availability(annotate_alfred_revisions(_raw_rows(payload)))


def _records():
    return [alfred_adapter(row) for row in _prepared_rows()]


def test_fixture_is_synthetic_and_not_a_dump():
    payload = _fixture_payload()
    assert payload["schema_version"] == "athena-alfred-vintage-observations-v1"
    assert "not a fred dump" in payload["note"].lower()
    assert len(payload["observations"]) == 3


def test_original_vintage_maps_to_an_exogenous_record():
    original = _records()[0]
    assert original.source == "macro"
    assert original.symbol is None
    assert original.revision_of is None
    assert original.payload["kind"] == "scheduled_print"
    assert original.payload["value"] == "319.086"
    assert original.payload["external_id"] == "alfred:CPIAUCSL:2026-01-01:2026-02-12"
    assert original.event_at == datetime(2026, 1, 1, 0, 0, tzinfo=EASTERN)
    assert original.available_at == datetime(2026, 2, 12, 8, 30, tzinfo=EASTERN)
    assert original.available_at <= PRINT_DECISION


def test_later_revision_is_not_substituted_for_the_original():
    original, revision, new_print = _records()
    assert revision.revision_of == original.payload["external_id"]
    assert revision.payload["kind"] == "revision"
    assert revision.payload["value"] == "319.214"
    assert revision.payload["external_id"] == "alfred:CPIAUCSL:2026-01-01:2026-03-12"
    assert new_print.revision_of is None
    assert new_print.payload["kind"] == "scheduled_print"

    at_print = visible_records([original, revision, new_print], as_of=PRINT_DECISION)
    assert at_print == (original,)
    assert at_print[0].payload["value"] == "319.086"

    after_revision = visible_records([original, revision, new_print], as_of=REVISION_DECISION)
    assert original in after_revision
    assert new_print in after_revision
    assert revision not in after_revision
    january = [item for item in after_revision if item.payload["observation_date"] == "2026-01-01"]
    assert january == [original]
    assert january[0].payload["value"] != revision.payload["value"]


def test_naive_available_at_fails_closed():
    row = dict(_prepared_rows()[0])
    row["available_at"] = "2026-02-12T08:30:00"
    with pytest.raises(ExogenousContractError, match="timezone-aware"):
        alfred_adapter(row)


def test_missing_available_at_fails_closed():
    row = dict(annotate_alfred_revisions(_raw_rows())[0])
    assert "available_at" not in row
    with pytest.raises(ExogenousContractError, match="available_at"):
        alfred_adapter(row)


def test_naive_event_at_override_fails_closed():
    row = dict(_prepared_rows()[0])
    row["event_at"] = "2026-01-01T00:00:00"
    with pytest.raises(ExogenousContractError, match="timezone-aware"):
        alfred_adapter(row)


def test_missing_timestamps_fail_closed():
    row = dict(_prepared_rows()[0])
    del row["realtime_start"]
    with pytest.raises(ExogenousContractError, match="realtime_start"):
        alfred_adapter(row)


def test_missing_value_and_dot_missing_fail_closed():
    row = dict(_prepared_rows()[0])
    row["value"] = "."
    with pytest.raises(ExogenousContractError, match="missing"):
        alfred_adapter(row)
    row["value"] = ""
    with pytest.raises(ExogenousContractError, match="missing"):
        alfred_adapter(row)


def test_unannotated_row_fails_closed_so_revisions_cannot_pass_as_originals():
    row = dict(_prepared_rows()[1])
    del row["original_realtime_start"]
    with pytest.raises(ExogenousContractError, match="original_realtime_start"):
        alfred_adapter(row)


def test_same_vintage_with_moved_available_at_is_rejected_by_anti_backfill():
    original = alfred_adapter(_prepared_rows()[0])
    moved = dict(_prepared_rows()[0])
    moved["available_at"] = datetime(2026, 2, 12, 16, 0, tzinfo=EASTERN).isoformat()
    retimestamped = alfred_adapter(moved)
    assert original.payload["external_id"] == retimestamped.payload["external_id"]
    with pytest.raises(IngestError):
        assert_stable_availability([original, retimestamped])


def test_normalize_accepts_alfred_rows_as_macro():
    records = normalize(_prepared_rows(), source="macro", adapter=alfred_adapter)
    assert len(records) == 3
    assert {item.payload["kind"] for item in records} == {"scheduled_print", "revision"}


def test_missing_key_does_not_attempt_a_live_call_from_the_fixture_path(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)

    def boom(*_args, **_kwargs):
        raise AssertionError("fixture path must not touch the network")

    monkeypatch.setattr("athena_trading.exogenous.alfred.urlopen", boom)
    monkeypatch.setattr("athena_trading.exogenous.alfred._default_transport", boom)

    original = alfred_adapter(_prepared_rows()[0])
    assert original.source == "macro"
    assert original.payload["value"] == "319.086"

    with pytest.raises(MissingAlfredCredentialsError, match="FRED_API_KEY"):
        api_key_from_env()
    with pytest.raises(MissingAlfredCredentialsError):
        fetch_alfred_observations(
            "CPIAUCSL", realtime_start="1776-07-04", realtime_end="9999-12-31",
        )
    with pytest.raises(MissingAlfredCredentialsError):
        fetch_alfred_vintage_dates(
            "CPIAUCSL", realtime_start="1776-07-04", realtime_end="9999-12-31",
        )


def test_fetch_refuses_current_view_parameters():
    with pytest.raises(AlfredError, match="vintage_dates or a realtime"):
        fetch_alfred_observations("CPIAUCSL", api_key="not-a-live-key")
    with pytest.raises(AlfredError, match="together"):
        fetch_alfred_observations(
            "CPIAUCSL", api_key="not-a-live-key", realtime_start="2026-02-12",
        )


def test_fetch_parses_a_fixture_payload_through_injected_transport():
    envelope = _fixture_payload()
    calls: list[str] = []

    def transport(method, url, headers):
        calls.append(url)
        assert method == "GET"
        assert url.startswith(API_ROOT + OBSERVATIONS_PATH)
        assert "realtime_start=1776-07-04" in url
        assert "realtime_end=9999-12-31" in url
        assert "observation_start=2024-01-01" in url
        assert "observation_end=2025-12-31" in url
        assert "output_type=1" in url
        assert "units=lin" in url
        assert "file_type=json" in url
        assert "api_key=fixture-key" in url
        body = {
            "realtime_start": "1776-07-04",
            "realtime_end": "9999-12-31",
            "units": "lin",
            "output_type": 1,
            "file_type": "json",
            "count": len(envelope["observations"]),
            "observations": envelope["observations"],
        }
        return 200, json.dumps(body).encode("utf-8")

    rows = fetch_alfred_observations(
        envelope["series_id"],
        realtime_start="1776-07-04",
        realtime_end="9999-12-31",
        observation_start="2024-01-01",
        observation_end="2025-12-31",
        api_key="fixture-key",
        transport=transport,
    )
    assert len(calls) == 1
    prepared = stamp_scheduled_availability(
        [{**row, "category": envelope["category"]} for row in rows]
    )
    records = [alfred_adapter(row) for row in prepared]
    assert records[0].revision_of is None
    assert records[1].revision_of == records[0].payload["external_id"]


def test_fetch_vintage_dates_uses_the_vintagedates_endpoint():
    def transport(method, url, headers):
        assert url.startswith(API_ROOT + "/fred/series/vintagedates")
        assert "realtime_start=2026-01-01" in url
        body = {
            "realtime_start": "2026-01-01",
            "realtime_end": "2026-03-31",
            "count": 2,
            "vintage_dates": ["2026-02-12", "2026-03-12"],
        }
        return 200, json.dumps(body).encode("utf-8")

    dates = fetch_alfred_vintage_dates(
        "CPIAUCSL",
        realtime_start="2026-01-01",
        realtime_end="2026-03-31",
        api_key="fixture-key",
        transport=transport,
    )
    assert dates == ("2026-02-12", "2026-03-12")


def test_stamp_does_not_overwrite_an_explicit_aware_timestamp():
    row = dict(annotate_alfred_revisions(_raw_rows())[0])
    explicit = datetime(2026, 2, 12, 8, 30, tzinfo=EASTERN).isoformat()
    row["available_at"] = explicit
    stamped = stamp_scheduled_availability([row], clock=time(10, 0))[0]
    assert stamped["available_at"] == explicit
