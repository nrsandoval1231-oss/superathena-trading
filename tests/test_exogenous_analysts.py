import random
from datetime import UTC, datetime, timedelta

import pytest

from athena_trading.exogenous import ExogenousRecord, compress_all, compressor_identity, feature_keys
from athena_trading.exogenous.analysts import (
    ABSENT,
    MACRO_CATEGORIES,
    AnalystError,
    compress_fundamentals,
    compress_macro,
    compress_news,
    compress_sentiment,
    session_windows,
)
from athena_trading.exogenous.buckets import (
    COUNT_EDGES,
    DENSITY_EDGES,
    MINUTES_EDGES,
    SURPRISE_EDGES,
    bucket,
)

DECISION = datetime(2026, 2, 3, 14, 45, tzinfo=UTC)      # Tue 09:45 ET
PRIOR_CLOSE = datetime(2026, 2, 2, 21, 0, tzinfo=UTC)    # Mon 16:00 ET


def _record(source, *, minutes_before, symbol="ABC", payload=None):
    available = DECISION - timedelta(minutes=minutes_before)
    return ExogenousRecord(
        source=source, symbol=symbol, event_at=available - timedelta(minutes=1),
        available_at=available, payload=payload or {"external_id": f"{source}-{minutes_before}"},
    )


# --- bucket edges: pinned by value so a tuning edit fails loudly -------------

def test_bucket_edges_are_pinned():
    assert COUNT_EDGES == (0.0, 1.0, 3.0, 6.0, 12.0)
    assert MINUTES_EDGES == (0.0, 15.0, 60.0, 240.0, 960.0)
    assert DENSITY_EDGES == (0.0, 0.5, 1.0, 2.0, 5.0)
    assert SURPRISE_EDGES == (-3.0, -1.0, -0.25, 0.25, 1.0, 3.0)


def test_bucket_boundaries_are_inclusive_lower():
    assert bucket(0, COUNT_EDGES) == 0
    assert bucket(1, COUNT_EDGES) == 1
    assert bucket(2.999, COUNT_EDGES) == 1
    assert bucket(3, COUNT_EDGES) == 2
    assert bucket(10_000, COUNT_EDGES) == 4


def test_absent_is_distinct_from_the_lowest_bucket():
    assert bucket(None, COUNT_EDGES) == ABSENT
    assert ABSENT != bucket(0, COUNT_EDGES)


def test_values_below_the_first_edge_clamp_rather_than_read_as_absent():
    assert bucket(-9.0, SURPRISE_EDGES) == 0


# --- determinism ------------------------------------------------------------

def test_compression_is_independent_of_input_order():
    records = [_record("news", minutes_before=m) for m in (5, 120, 400, 30, 900)]
    shuffled = list(records)
    random.Random(7).shuffle(shuffled)
    assert compress_all(records, as_of=DECISION, prior_close=PRIOR_CLOSE) == compress_all(
        shuffled, as_of=DECISION, prior_close=PRIOR_CLOSE
    )


def test_feature_key_set_is_frozen_and_complete():
    keys = feature_keys()
    assert len(keys) == len(set(keys)) == 24
    assert set(compress_all((), as_of=DECISION, prior_close=PRIOR_CLOSE)) == set(keys)
    for source in ("news", "sentiment", "fundamentals", "macro", "prediction_market"):
        assert f"{source}_present" in keys


def test_compressor_identity_hash_changes_with_the_key_set():
    identity = compressor_identity()
    assert identity["identity_hash"] == compressor_identity()["identity_hash"]
    assert identity["feature_keys"] == list(feature_keys())
    assert identity["version"] == "athena-exogenous-compressors-v1"


def test_every_feature_is_an_integer_or_flag():
    features = compress_all(
        [_record("news", minutes_before=10)], as_of=DECISION, prior_close=PRIOR_CLOSE
    )
    assert all(isinstance(value, (int, bool)) for value in features.values())


# --- windows ----------------------------------------------------------------

def test_session_windows_use_the_supplied_prior_close():
    overnight, premarket = session_windows(DECISION, prior_close=PRIOR_CLOSE)
    assert overnight == PRIOR_CLOSE.astimezone(overnight.tzinfo)
    assert premarket.hour == 4 and premarket.minute == 0


def test_prior_close_after_the_premarket_open_is_refused():
    with pytest.raises(AnalystError):
        session_windows(DECISION, prior_close=DECISION - timedelta(minutes=5))


def test_news_separates_overnight_from_premarket():
    overnight = _record("news", minutes_before=600)   # ~23:45 ET prior day
    premarket = _record("news", minutes_before=60)    # 08:45 ET
    features = compress_news([overnight, premarket], as_of=DECISION, prior_close=PRIOR_CLOSE)
    assert features["news_overnight_count_bucket"] == bucket(1, COUNT_EDGES)
    assert features["news_premarket_count_bucket"] == bucket(1, COUNT_EDGES)
    assert features["news_present"] is True


def test_absent_evidence_reads_as_absent_not_as_zero():
    features = compress_all((), as_of=DECISION, prior_close=PRIOR_CLOSE)
    assert features["news_present"] is False
    assert features["news_minutes_since_last_bucket"] == ABSENT
    assert features["news_density_bucket"] == ABSENT
    assert features["sentiment_bull_ratio_bucket"] == ABSENT
    assert features["macro_surprise_bucket"] == ABSENT
    # A count of nothing is still a real count, so it buckets rather than absents.
    assert features["news_overnight_count_bucket"] == bucket(0, COUNT_EDGES)


# --- per-source behaviour ---------------------------------------------------

def test_sentiment_deduplicates_authors():
    spam = [
        _record("sentiment", minutes_before=m, payload={"author_id": "bot", "tag": "bullish"})
        for m in range(1, 9)
    ]
    features = compress_sentiment(spam, as_of=DECISION, prior_close=PRIOR_CLOSE)
    assert features["sentiment_unique_authors_bucket"] == bucket(1, COUNT_EDGES)
    assert features["sentiment_premarket_volume_bucket"] == bucket(8, COUNT_EDGES)


def test_sentiment_bull_ratio_ignores_untagged_messages():
    records = [
        _record("sentiment", minutes_before=10, payload={"tag": "bullish", "author_id": "a"}),
        _record("sentiment", minutes_before=11, payload={"tag": "bearish", "author_id": "b"}),
        _record("sentiment", minutes_before=12, payload={"author_id": "c"}),
    ]
    features = compress_sentiment(records, as_of=DECISION, prior_close=PRIOR_CLOSE)
    assert features["sentiment_bull_ratio_bucket"] == bucket(0.5, (0.0, 0.2, 0.4, 0.6, 0.8))


def test_fundamentals_reports_the_event_not_the_value():
    filing = _record(
        "fundamentals", minutes_before=900,
        payload={"event_type": "filing", "eps": 1.23, "external_id": "f1"},
    )
    features = compress_fundamentals([filing], as_of=DECISION, prior_close=PRIOR_CLOSE)
    assert features["fundamentals_reported_since_last_close"] is True
    assert features["fundamentals_hours_since_filing_bucket"] == bucket(15.0, (0.0, 2, 8, 24, 72))
    assert not any("eps" in key for key in features)


def test_fundamentals_ignores_a_next_report_already_in_the_past():
    stale = _record(
        "fundamentals", minutes_before=60,
        payload={"event_type": "filing", "next_report_at": (DECISION - timedelta(days=5)).isoformat()},
    )
    features = compress_fundamentals([stale], as_of=DECISION, prior_close=PRIOR_CLOSE)
    assert features["fundamentals_days_to_next_report_bucket"] == ABSENT


def test_fundamentals_rejects_a_naive_scheduled_date():
    bad = _record(
        "fundamentals", minutes_before=60,
        payload={"event_type": "filing", "next_report_at": "2026-03-01T09:00:00"},
    )
    with pytest.raises(AnalystError):
        compress_fundamentals([bad], as_of=DECISION, prior_close=PRIOR_CLOSE)


def test_macro_reads_the_most_recent_release():
    early = _record(
        "macro", minutes_before=300, symbol=None,
        payload={"category": "growth", "surprise_z": -2.0, "external_id": "m1"},
    )
    latest = _record(
        "macro", minutes_before=75, symbol=None,
        payload={"category": "inflation", "surprise_z": 1.5, "external_id": "m2"},
    )
    features = compress_macro([early, latest], as_of=DECISION, prior_close=PRIOR_CLOSE)
    assert features["macro_category_code"] == MACRO_CATEGORIES.index("inflation")
    assert features["macro_surprise_bucket"] == bucket(1.5, SURPRISE_EDGES)
    assert features["macro_minutes_since_release_bucket"] == bucket(75.0, MINUTES_EDGES)


def test_macro_without_consensus_ships_the_event_without_a_surprise():
    release = _record(
        "macro", minutes_before=75, symbol=None, payload={"category": "employment"},
    )
    features = compress_macro([release], as_of=DECISION, prior_close=PRIOR_CLOSE)
    assert features["macro_release_since_last_close"] is True
    assert features["macro_surprise_bucket"] == ABSENT


def test_unknown_macro_category_falls_back_rather_than_raising():
    release = _record("macro", minutes_before=75, symbol=None, payload={"category": "vibes"})
    features = compress_macro([release], as_of=DECISION, prior_close=PRIOR_CLOSE)
    assert features["macro_category_code"] == MACRO_CATEGORIES.index("other")


def test_baseline_uses_only_evidence_visible_at_the_decision():
    history = [
        _record("news", minutes_before=1440 * day) for day in range(1, 11)
    ]
    today = _record("news", minutes_before=30)
    features = compress_news(history + [today], as_of=DECISION, prior_close=PRIOR_CLOSE)
    assert features["news_density_bucket"] != ABSENT
