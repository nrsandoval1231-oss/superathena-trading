from datetime import UTC, datetime

import pytest

from athena_trading.exogenous.gdelt import GdeltError, parse_gkg_row


def _row() -> str:
    fields = [""] * 27
    fields[0] = "20250101000000-0"
    fields[1] = "20250101000000"
    fields[3] = "example.com"
    fields[4] = "https://example.com/story"
    fields[7] = "ECON_STOCKMARKET;WB_123"
    fields[11] = "Jane Doe"
    fields[13] = "Example Corporation"
    fields[15] = "1.5,2.0,0.5,1.0"
    return "\t".join(fields)


def test_parse_gkg_row_maps_stable_news_record():
    record = parse_gkg_row(_row(), symbol="AAPL")

    expected = datetime(2025, 1, 1, tzinfo=UTC)
    assert record.source == "news"
    assert record.symbol == "AAPL"
    assert record.event_at == expected
    assert record.available_at == expected
    assert record.payload["external_id"] == "gdelt:20250101000000-0:AAPL"
    assert record.payload["url"] == "https://example.com/story"
    assert record.payload["domain"] == "example.com"
    assert record.payload["themes"] == ["ECON_STOCKMARKET", "WB_123"]
    assert record.payload["organizations"] == ["Example Corporation"]


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda fields: fields[:-1], "27 fields"),
        (lambda fields: fields[:1] + ["bad-date"] + fields[2:], "timestamp"),
        (lambda fields: fields[:4] + [""] + fields[5:], "URL"),
    ],
)
def test_parse_gkg_row_fails_closed_on_malformed_input(mutate, message):
    fields = _row().split("\t")
    with pytest.raises(GdeltError, match=message):
        parse_gkg_row("\t".join(mutate(fields)), symbol="AAPL")


def test_parse_gkg_row_requires_symbol():
    with pytest.raises(GdeltError, match="symbol"):
        parse_gkg_row(_row(), symbol="")
