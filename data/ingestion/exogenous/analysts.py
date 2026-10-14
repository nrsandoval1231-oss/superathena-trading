"""Deterministic analyst compressors.

TradingAgents splits its input space across specialist analyst agents and then
lets those agents *decide*.  The decomposition is useful; the authority is not,
because an LLM panel with no control arm cannot be evaluated.  We keep the
split and throw away the authority: each compressor here is a pure function
from visible records to a fixed, versioned, bucketed key set.  No model call,
no network, no outcome access.  Given the same snapshot hash, the output is
byte-identical forever.

**These scoring semantics are unvalidated.**  The windows, the baselines and
the bucket edges are frozen so results are reproducible, not because any of
them is known to be predictive.  Nobody should later mistake a frozen constant
for a validated one.

Every compressor emits a ``*_present`` flag.  Exogenous coverage is denser for
large caps and for names that subsequently moved, so coverage itself is a
feature whose effect must stay measurable rather than hidden inside an absent
bucket.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..athena_adapter.contracts import canonical_hash
from .buckets import (
    ABSENT,
    COUNT_EDGES,
    DAYS_EDGES,
    DENSITY_EDGES,
    HOURS_EDGES,
    MINUTES_EDGES,
    RATIO_EDGES,
    SURPRISE_EDGES,
    bucket,
    ratio_bucket,
)
from .contracts import ExogenousRecord

EASTERN = ZoneInfo("America/New_York")

#: Pre-market session opens at 04:00 ET.  Anything earlier is "overnight".
PREMARKET_OPEN = time(4, 0)
#: Regular session closes at 16:00 ET; the overnight window starts there.
REGULAR_CLOSE = time(16, 0)
#: Velocity window: the final stretch before the decision.
VELOCITY_MINUTES = 15
#: Calendar days of trailing history used to build a per-symbol baseline.
BASELINE_DAYS = 20

#: Frozen macro category vocabulary.  Index is the emitted code.
MACRO_CATEGORIES = ("none", "employment", "inflation", "growth", "rates", "other")


class AnalystError(ValueError):
    """A compressor was given inputs it cannot honestly reduce."""


def session_windows(
    as_of: datetime, *, prior_close: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Return ``(overnight_start, premarket_start)`` for a decision at ``as_of``.

    ``premarket_start`` is 04:00 ET on the decision day.  ``overnight_start`` is
    the prior session close.

    Pass ``prior_close`` whenever the caller knows it -- the snapshot builder
    does, from the bar data.  The fallback is 16:00 ET on the previous
    *calendar* day, which is wrong across weekends and holidays: a Monday
    decision would miss Friday afternoon entirely.  The fallback exists so the
    compressors are testable in isolation, not because it is good enough for a
    registered run.
    """
    local = as_of.astimezone(EASTERN)
    premarket_start = datetime.combine(local.date(), PREMARKET_OPEN, tzinfo=EASTERN)
    if premarket_start > local:
        raise AnalystError("as_of precedes the pre-market open on its own session day")
    if prior_close is not None:
        overnight_start = prior_close.astimezone(EASTERN)
        if overnight_start >= premarket_start:
            raise AnalystError("prior_close does not precede the pre-market open")
    else:
        overnight_start = datetime.combine(
            local.date() - timedelta(days=1), REGULAR_CLOSE, tzinfo=EASTERN
        )
    return overnight_start, premarket_start


def _in_window(record: ExogenousRecord, start: datetime, end: datetime) -> bool:
    """Half-open ``[start, end)`` on observability, never on event time."""
    return start <= record.available_at < end


def trailing_baseline(
    records: Sequence[ExogenousRecord], *, as_of: datetime, days: int = BASELINE_DAYS,
) -> float | None:
    """Mean records per calendar day over the trailing window, or None if empty.

    Computed only from records already visible at ``as_of``, so a baseline can
    never carry information from after the decision.  Returns ``None`` rather
    than zero when there is no history at all: a name with no trailing coverage
    has no baseline to be a multiple of.
    """
    if days < 1:
        raise AnalystError("baseline window must be at least one day")
    local = as_of.astimezone(EASTERN)
    window_start = datetime.combine(
        local.date() - timedelta(days=days), PREMARKET_OPEN, tzinfo=EASTERN
    )
    day_start = datetime.combine(local.date(), PREMARKET_OPEN, tzinfo=EASTERN)
    counted = sum(1 for item in records if _in_window(item, window_start, day_start))
    if counted == 0:
        return None
    return counted / days


def _minutes_since(latest: datetime | None, as_of: datetime) -> float | None:
    if latest is None:
        return None
    return (as_of - latest).total_seconds() / 60.0


def compress_news(
    records: Sequence[ExogenousRecord], *, as_of: datetime,
    prior_close: datetime | None = None,
) -> dict[str, int | bool]:
    """News flow around the opening range.

    The overnight and pre-market windows are separated because they are
    different phenomena for a breakout: an overnight story is priced into the
    gap, a 09:20 story is still being absorbed when the range freezes.
    """
    overnight_start, premarket_start = session_windows(as_of, prior_close=prior_close)
    items = [item for item in records if item.source == "news"]
    overnight = [item for item in items if _in_window(item, overnight_start, premarket_start)]
    premarket = [item for item in items if _in_window(item, premarket_start, as_of)]
    session = overnight + premarket
    latest = max((item.available_at for item in session), default=None)
    baseline = trailing_baseline(items, as_of=as_of)
    return {
        "news_present": bool(session),
        "news_overnight_count_bucket": bucket(len(overnight), COUNT_EDGES),
        "news_premarket_count_bucket": bucket(len(premarket), COUNT_EDGES),
        "news_minutes_since_last_bucket": bucket(_minutes_since(latest, as_of), MINUTES_EDGES),
        "news_density_bucket": ratio_bucket(len(session), baseline, DENSITY_EDGES),
        "news_scheduled_event": any(
            bool(item.payload.get("scheduled_event")) for item in session
        ),
    }


def compress_sentiment(
    records: Sequence[ExogenousRecord], *, as_of: datetime,
    prior_close: datetime | None = None,
) -> dict[str, int | bool]:
    """Social activity, as velocity rather than as a standing level.

    Volume relative to the symbol's own baseline and acceleration into the
    decision are the parts a breakout could plausibly turn on.  A raw bullish
    percentage is mostly a popularity measurement.

    Authors are de-duplicated for the unique-author count so one prolific
    poster cannot manufacture a signal, which is the dominant failure mode on
    both StockTwits and the finance subreddits.
    """
    overnight_start, premarket_start = session_windows(as_of, prior_close=prior_close)
    items = [item for item in records if item.source == "sentiment"]
    session = [item for item in items if _in_window(item, overnight_start, as_of)]
    premarket = [item for item in session if item.available_at >= premarket_start]
    velocity_start = as_of - timedelta(minutes=VELOCITY_MINUTES)
    recent = [item for item in session if item.available_at >= velocity_start]
    tagged = [item for item in session if item.payload.get("tag") in ("bullish", "bearish")]
    bullish = [item for item in tagged if item.payload["tag"] == "bullish"]
    authors = {
        item.payload.get("author_id") for item in session if item.payload.get("author_id")
    }
    baseline = trailing_baseline(items, as_of=as_of)
    # Per-minute rates make the two windows comparable: a burst in the last
    # quarter-hour should register even when total pre-market volume is thin.
    premarket_minutes = max((as_of - premarket_start).total_seconds() / 60.0, 1.0)
    premarket_rate = len(premarket) / premarket_minutes
    recent_rate = len(recent) / float(VELOCITY_MINUTES)
    return {
        "sentiment_present": bool(session),
        "sentiment_premarket_volume_bucket": bucket(len(premarket), COUNT_EDGES),
        "sentiment_density_bucket": ratio_bucket(len(session), baseline, DENSITY_EDGES),
        "sentiment_bull_ratio_bucket": (
            bucket(len(bullish) / len(tagged), RATIO_EDGES) if tagged else ABSENT
        ),
        "sentiment_unique_authors_bucket": bucket(len(authors) if session else None, COUNT_EDGES),
        "sentiment_velocity_bucket": ratio_bucket(recent_rate, premarket_rate, DENSITY_EDGES),
    }


def compress_fundamentals(
    records: Sequence[ExogenousRecord], *, as_of: datetime,
    prior_close: datetime | None = None,
) -> dict[str, int | bool]:
    """Filing *events*, never filing values.

    At 09:45 on an opening-range breakout the tape is not reacting to an EPS
    figure; it is reacting to the fact that this name reported sixteen hours
    ago.  Narrowing to the event also sidesteps the restatement problem almost
    entirely, which is the single worst point-in-time risk in the exogenous set.

    ``next_report_at`` must be the schedule *as known at* ``as_of``.  Scheduled
    report dates are themselves revised, so a store that overwrites them
    reintroduces the leak this narrowing was meant to remove.
    """
    overnight_start, _ = session_windows(as_of, prior_close=prior_close)
    items = [item for item in records if item.source == "fundamentals"]
    filings = [item for item in items if item.payload.get("event_type") == "filing"]
    visible = [item for item in filings if item.available_at <= as_of]
    latest = max((item.available_at for item in visible), default=None)
    hours_since = None if latest is None else (as_of - latest).total_seconds() / 3600.0
    next_report = None
    for item in items:
        raw = item.payload.get("next_report_at")
        if not raw:
            continue
        try:
            scheduled = datetime.fromisoformat(str(raw))
        except ValueError as exc:
            raise AnalystError("next_report_at is not ISO-8601") from exc
        if scheduled.tzinfo is None:
            raise AnalystError("next_report_at must be timezone-aware")
        if scheduled >= as_of and (next_report is None or scheduled < next_report):
            next_report = scheduled
    days_to_next = None if next_report is None else (next_report - as_of).total_seconds() / 86400.0
    return {
        "fundamentals_present": bool(visible),
        "fundamentals_reported_since_last_close": any(
            item.available_at >= overnight_start for item in visible
        ),
        "fundamentals_hours_since_filing_bucket": bucket(hours_since, HOURS_EDGES),
        "fundamentals_days_to_next_report_bucket": bucket(days_to_next, DAYS_EDGES),
        "fundamentals_guidance_issued": any(
            item.payload.get("event_type") == "guidance"
            and item.available_at >= overnight_start
            for item in items
        ),
    }


def compress_macro(
    records: Sequence[ExogenousRecord], *, as_of: datetime,
    prior_close: datetime | None = None,
) -> dict[str, int | bool]:
    """Scheduled macro releases as a market-wide record.

    An 08:30 ET print lands seventy-five minutes before the range freezes and
    sets the tone the opening range forms inside.  Surprise is read from
    ``surprise_z`` when the store carries a defensible consensus series; when it
    does not, the release-event flags ship without it rather than guessing.
    """
    overnight_start, _ = session_windows(as_of, prior_close=prior_close)
    items = [item for item in records if item.source == "macro"]
    session = [item for item in items if _in_window(item, overnight_start, as_of)]
    latest_at = max((item.available_at for item in session), default=None)
    latest = None
    for item in session:
        if item.available_at == latest_at:
            latest = item
    surprise = None
    category = "none"
    if latest is not None:
        raw = latest.payload.get("surprise_z")
        if raw is not None:
            try:
                surprise = float(raw)
            except (TypeError, ValueError) as exc:
                raise AnalystError("surprise_z is not numeric") from exc
        candidate = str(latest.payload.get("category", "other"))
        category = candidate if candidate in MACRO_CATEGORIES else "other"
    return {
        "macro_present": bool(session),
        "macro_release_since_last_close": bool(session),
        "macro_minutes_since_release_bucket": bucket(
            _minutes_since(latest_at, as_of), MINUTES_EDGES
        ),
        "macro_surprise_bucket": bucket(surprise, SURPRISE_EDGES),
        "macro_category_code": MACRO_CATEGORIES.index(category),
    }


def compress_prediction_market(
    records: Sequence[ExogenousRecord], *, as_of: datetime,
    prior_close: datetime | None = None,
) -> dict[str, int | bool]:
    """Prediction-market state, as a market-wide record.

    Provenance is excellent -- on-chain trades carry real block timestamps --
    and relevance to a single-name intraday breakout is close to nil, because
    available markets are macro and political rather than per-equity.  This
    compressor exists to exercise the market-wide record path and prove the
    contract generalizes past equities.  It is not expected to carry signal.
    """
    overnight_start, _ = session_windows(as_of, prior_close=prior_close)
    items = [
        item for item in records
        if item.source == "prediction_market" and _in_window(item, overnight_start, as_of)
    ]
    latest_at = max((item.available_at for item in items), default=None)
    probability = None
    for item in items:
        if item.available_at == latest_at:
            raw = item.payload.get("implied_probability")
            if raw is not None:
                try:
                    probability = float(raw)
                except (TypeError, ValueError) as exc:
                    raise AnalystError("implied_probability is not numeric") from exc
    return {
        "prediction_market_present": bool(items),
        "prediction_market_probability_bucket": bucket(probability, RATIO_EDGES),
    }


#: Ordered registry.  The tuple order fixes the feature key order in a snapshot.
COMPRESSORS = (
    ("news", compress_news),
    ("sentiment", compress_sentiment),
    ("fundamentals", compress_fundamentals),
    ("macro", compress_macro),
    ("prediction_market", compress_prediction_market),
)

#: Version string for the whole compression stage.  Any change to a window, a
#: baseline, a bucket edge or a key name must bump this.
COMPRESSOR_VERSION = "athena-exogenous-compressors-v1"


def compressor_identity() -> dict[str, Any]:
    """Hashable description of exactly how features were produced."""
    identity = {
        "version": COMPRESSOR_VERSION,
        "sources": [name for name, _ in COMPRESSORS],
        "feature_keys": list(feature_keys()),
        "windows": {
            "premarket_open_et": PREMARKET_OPEN.isoformat(),
            "regular_close_et": REGULAR_CLOSE.isoformat(),
            "velocity_minutes": VELOCITY_MINUTES,
            "baseline_days": BASELINE_DAYS,
        },
        "bucket_edges": {
            "count": list(COUNT_EDGES),
            "minutes": list(MINUTES_EDGES),
            "hours": list(HOURS_EDGES),
            "days": list(DAYS_EDGES),
            "density": list(DENSITY_EDGES),
            "ratio": list(RATIO_EDGES),
            "surprise": list(SURPRISE_EDGES),
        },
        "macro_categories": list(MACRO_CATEGORIES),
    }
    identity["identity_hash"] = canonical_hash(identity)
    return identity


def feature_keys() -> tuple[str, ...]:
    """The frozen key set, in registry order.

    Derived by running every compressor over empty evidence, so the key set can
    never drift from what the compressors actually emit.
    """
    epoch = datetime(2026, 1, 5, 9, 45, tzinfo=EASTERN)
    keys: list[str] = []
    for _, compress in COMPRESSORS:
        keys.extend(compress((), as_of=epoch))
    return tuple(keys)


def compress_all(
    records: Sequence[ExogenousRecord], *, as_of: datetime,
    prior_close: datetime | None = None,
) -> dict[str, int | bool]:
    """Run every compressor and return the merged, frozen-key feature vector."""
    features: dict[str, int | bool] = {}
    for _, compress in COMPRESSORS:
        produced = compress(records, as_of=as_of, prior_close=prior_close)
        collisions = set(produced) & set(features)
        if collisions:
            raise AnalystError(f"compressor key collision on {sorted(collisions)}")
        features.update(produced)
    if not all(isinstance(value, (int, bool)) for value in features.values()):
        raise AnalystError("compressors emitted a non-integer feature")
    return features


def coverage(features: Mapping[str, Any]) -> dict[str, bool]:
    """Per-source presence flags pulled out of a feature vector."""
    return {
        name: bool(features[f"{name}_present"])
        for name, _ in COMPRESSORS
        if f"{name}_present" in features
    }
