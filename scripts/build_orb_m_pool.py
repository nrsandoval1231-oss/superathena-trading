"""Build a point-in-time ORB-M candidate pool from daily grouped aggregates.

The pool this replaces was assembled from model knowledge of names liquid
*today*, so every symbol in it survived to the present by construction and the
manifest had to record ``carries_survivorship_bias: true``.  That bias is not a
rounding error in a breakout study: the names that blew up, got acquired, or
delisted mid-campaign are exactly the ones whose breakouts failed worst, and
excluding them silently flatters every statistic computed downstream.

This builder removes it by reading two point-in-time sources:

  * daily grouped aggregates, one file per session, each listing every ticker
    that traded *that day* -- a name delisted in 2024 is still present in its
    own 2023 file;
  * the provider ticker reference *as of the lookback end*, which is what
    separates common stock from the ETFs, units, and warrants that otherwise
    dominate a raw dollar-volume ranking.

Both predate the campaign window, and the builder refuses to run if the
lookback overlaps it.  The result is over-inclusive on purpose: it is a
candidate pool, not a universe.  SelectionRule still ranks it on measured
minute bars and keeps the top 50, which is only meaningful if the pool handed
to it is substantially larger.

Requires POLYGON_API_KEY for the reference call.  The grouped aggregates are
read from a local directory; their content hashes are recorded in the manifest
so the pool can be traced back to the exact bytes it was built from.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from statistics import median

import pyarrow.parquet as pq

from athena_trading.orb_m.constitution import Constitution
from athena_trading.orb_m.universe import PoolProvenance

REFERENCE_URL = "https://api.polygon.io/v3/reference/tickers"
SCHEMA_VERSION = "athena-orb-m-candidate-pool-v1"


def _iso(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _write_once(path: Path, text: str) -> None:
    if path.exists():
        raise SystemExit(f"refusing to overwrite {path}; frozen artifacts are immutable")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _get_json(url: str, *, attempts: int = 6) -> dict:
    """GET with backoff.  The reference endpoint is rate limited on some plans."""
    delay = 2.0
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            if error.code != 429 or attempt == attempts:
                raise
        except urllib.error.URLError:
            if attempt == attempts:
                raise
        time.sleep(delay)
        delay = min(delay * 2, 60.0)
    raise RuntimeError("unreachable")


def common_stock_symbols(*, as_of: date, api_key: str) -> set[str]:
    """Tickers typed common stock *as of* ``as_of``, not as of today.

    Asking for today listings would reintroduce exactly the survivorship bias
    the grouped aggregates were chosen to avoid.
    """
    query = urllib.parse.urlencode({
        "market": "stocks", "type": "CS", "date": as_of.isoformat(),
        "limit": 1000, "apiKey": api_key,
    })
    url = f"{REFERENCE_URL}?{query}"
    symbols: set[str] = set()
    pages = 0
    while url:
        payload = _get_json(url)
        for item in payload.get("results", []):
            if item.get("ticker"):
                symbols.add(item["ticker"].upper())
        pages += 1
        next_url = payload.get("next_url")
        url = f"{next_url}&apiKey={api_key}" if next_url else ""
    print(f"  reference: {len(symbols)} common stocks over {pages} pages", file=sys.stderr)
    return symbols


def session_files(grouped_root: Path, start: date, end: date) -> list[Path]:
    """Grouped files inside the window that represent an actual session.

    The cache stores a zero-row placeholder for every market holiday.  Counting
    those as sessions inflates the coverage denominator and quietly relaxes the
    coverage floor, so they are dropped here rather than filtered downstream.
    """
    chosen = []
    for path in sorted(grouped_root.glob("*.parquet")):
        try:
            day = _iso(path.stem)
        except ValueError:
            continue
        if start <= day <= end and pq.ParquetFile(path).metadata.num_rows > 0:
            chosen.append(path)
    return chosen


def daily_observations(paths: list[Path]) -> dict[str, list[tuple[float, float]]]:
    """symbol -> [(close, share volume)] across the lookback sessions."""
    observations: dict[str, list[tuple[float, float]]] = {}
    for index, path in enumerate(paths, start=1):
        table = pq.read_table(path, columns=["ticker", "c", "v"])
        for symbol, close, volume in zip(table.column("ticker").to_pylist(),
                                         table.column("c").to_pylist(),
                                         table.column("v").to_pylist(), strict=True):
            if symbol and close is not None and volume is not None:
                observations.setdefault(symbol.upper(), []).append((float(close), float(volume)))
        if index % 20 == 0 or index == len(paths):
            print(f"  read {index}/{len(paths)} sessions", file=sys.stderr)
    return observations


def build(args: argparse.Namespace) -> int:
    campaign_start = _iso(args.campaign_start)
    lookback_end = _iso(args.lookback_end)
    if lookback_end >= campaign_start:
        raise SystemExit(
            f"lookback_end {lookback_end} is not strictly before campaign start "
            f"{campaign_start}; pool construction would see the campaign")
    lookback_start = lookback_end - timedelta(days=args.lookback_calendar_days)

    grouped_root = Path(args.grouped_root)
    if not grouped_root.is_dir():
        raise SystemExit(f"no grouped aggregates at {grouped_root}")

    api_key = os.environ.get("POLYGON_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("POLYGON_API_KEY is required for the point-in-time reference")

    paths = session_files(grouped_root, lookback_start, lookback_end)
    if not paths:
        raise SystemExit(
            f"no non-empty grouped sessions between {lookback_start} and {lookback_end}")
    print(f"  {len(paths)} sessions {paths[0].stem} -> {paths[-1].stem}", file=sys.stderr)

    reference = common_stock_symbols(as_of=lookback_end, api_key=api_key)
    observations = daily_observations(paths)

    constitution = Constitution()
    required = args.min_session_coverage * len(paths)
    funnel = {"tickers_seen": len(observations)}

    covered = {s: o for s, o in observations.items() if len(o) >= required}
    funnel["with_session_coverage"] = len(covered)

    common = {s: o for s, o in covered.items() if s in reference}
    funnel["typed_common_stock"] = len(common)

    ranked = []
    for symbol, obs in common.items():
        price = median(c for c, _ in obs)
        shares = median(v for _, v in obs)
        if price < constitution.price_min or shares < constitution.adv_min:
            continue
        ranked.append((median(c * v for c, v in obs), symbol))
    funnel["passing_price_and_adv_floors"] = len(ranked)

    ranked.sort(key=lambda item: (-item[0], item[1]))
    members = [symbol for _, symbol in ranked[:args.pool_size]]
    funnel["written_to_pool"] = len(members)
    if len(members) < args.pool_size:
        print(f"  WARNING: only {len(members)} names cleared the floors, "
              f"below the requested pool size {args.pool_size}", file=sys.stderr)

    sources = [{"file": p.name, "sha256": _sha256(p)} for p in paths]
    corpus_hash = hashlib.sha256(
        "".join(f"{s['file']}:{s['sha256']}" for s in sources).encode()).hexdigest()

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "provenance": PoolProvenance.POINT_IN_TIME.value,
        "carries_survivorship_bias": False,
        "generated_at": datetime.now(UTC).isoformat(),
        "lookback_start": lookback_start.isoformat(),
        "lookback_end": lookback_end.isoformat(),
        "campaign_start": campaign_start.isoformat(),
        "sessions_observed": len(paths),
        "min_session_coverage": args.min_session_coverage,
        "pool_size_requested": args.pool_size,
        "price_min": constitution.price_min,
        "adv_min": constitution.adv_min,
        "ranking_metric": "median daily close * share volume, unadjusted",
        "funnel": funnel,
        "reference": {
            "source": "polygon_v3_reference_tickers",
            "as_of": lookback_end.isoformat(),
            "filters": {"market": "stocks", "type": "CS"},
            "symbols_returned": len(reference),
        },
        "grouped_corpus_sha256": corpus_hash,
        "grouped_sources": sources,
        "members": members,
    }

    header = "\n".join([
        "# ORB-M v1.0 candidate pool -- POINT_IN_TIME",
        "#",
        f"# Built from daily grouped aggregates over {lookback_start} .. {lookback_end}",
        f"# ({len(paths)} sessions), intersected with the common-stock reference as of",
        f"# {lookback_end}.",
        "#",
        "# Pass --provenance POINT_IN_TIME when freezing. Unlike the CURRENT_SNAPSHOT",
        "# pool this replaces, names that delisted after the lookback are present:",
        "# each grouped file lists what traded on its own day, and the type filter is",
        "# asked for the lookback date rather than for today.",
        "#",
        f"# Floors: median close >= {constitution.price_min}, median daily volume >=",
        f"# {constitution.adv_min:,} shares, session coverage >= {args.min_session_coverage:.0%}.",
        f"# Ranked on median daily dollar volume, top {args.pool_size} kept.",
        "#",
        "# Over-inclusive by design: SelectionRule re-ranks these on measured minute",
        "# bars and keeps 50. Handing the freeze exactly 50 names would make it",
        "# decorative.",
        "#",
        f"# Corpus sha256: {corpus_hash}",
        f"# Manifest: {Path(args.manifest).name}",
        "",
    ])
    _write_once(Path(args.output), header + "\n".join(members) + "\n")
    _write_once(Path(args.manifest), json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    print(f"wrote {args.output} ({len(members)} symbols)")
    print(f"wrote {args.manifest} (corpus {corpus_hash[:16]})")
    print("  funnel: " + " -> ".join(f"{k}={v}" for k, v in funnel.items()))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--grouped-root", required=True,
                        help="directory of YYYY-MM-DD.parquet daily grouped aggregates")
    parser.add_argument("--lookback-end", required=True, help="YYYY-MM-DD, before the campaign")
    parser.add_argument("--lookback-calendar-days", type=int, default=120)
    parser.add_argument("--campaign-start", required=True)
    parser.add_argument("--pool-size", type=int, default=400)
    parser.add_argument("--min-session-coverage", type=float, default=0.95)
    parser.add_argument("--output", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--env-file", default=".env")

    args = parser.parse_args()
    if not 0 < args.min_session_coverage <= 1:
        raise SystemExit("--min-session-coverage must be within (0, 1]")
    if args.pool_size < 1:
        raise SystemExit("--pool-size must be positive")

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from freeze_orb_m_universe import load_env_file
    load_env_file(Path(args.env_file))
    return build(args)


if __name__ == "__main__":
    raise SystemExit(main())
