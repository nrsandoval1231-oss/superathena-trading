"""Compute lookback statistics and freeze the ORB-M campaign universe.

Two stages, deliberately separate so the selection rule is applied to data that
provably predates the campaign window:

  stats  -- pull lookback bars for a candidate pool and write per-symbol
            liquidity statistics.  Refuses a lookback that overlaps the campaign.
  freeze -- apply the frozen SelectionRule to those statistics and write an
            immutable universe manifest.

Requires MASSIVE_API_KEY and network access to the provider.  Neither is
available in every environment; run this where both are.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo

from athena_trading.orb_m.constitution import Constitution
from athena_trading.orb_m.universe import (
    PoolProvenance, SelectionRule, SymbolStatistics, select_universe,
)
from athena_trading.market_data.massive import download_minute_bars


def _write_once(path: Path, payload: dict) -> None:
    if path.exists():
        raise SystemExit(f"refusing to overwrite {path}; frozen artifacts are immutable")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _iso(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


MARKET_TZ = ZoneInfo("America/New_York")
REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)
#: Taken from the frozen strategy rather than restated, so the window this
#: measures cannot drift from the window the engine trades.
OPENING_MINUTES = Constitution().opening_minutes


def _session_statistics(rows: list[str], *, opening_minutes: int = OPENING_MINUTES
                        ) -> tuple[float, float, float, int]:
    """Median price, median dollar volume, median opening volume, session count.

    Bars arrive stamped in UTC and cover extended hours.  Two consequences have
    to be handled explicitly:

    * Grouping on the UTC date splits a session, because after-hours trading
      runs to 20:00 ET, which is past midnight UTC.  Sessions are therefore
      keyed on the exchange-local date.
    * The first bars of a raw day are 04:00 ET premarket, not the opening
      range.  Opening volume is taken from the regular-hours window starting at
      09:30 ET so it means what RVOL needs it to mean.

    Statistics describe regular trading hours only; extended-hours bars are
    excluded rather than blended into medians they would distort.
    """
    sessions: dict[str, list[tuple[datetime, dict]]] = {}
    for raw in rows:
        row = json.loads(raw)
        local = datetime.fromisoformat(row["event_at"]).astimezone(MARKET_TZ)
        if not REGULAR_OPEN <= local.time() < REGULAR_CLOSE:
            continue
        sessions.setdefault(local.date().isoformat(), []).append((local, row))
    if not sessions:
        return 0.0, 0.0, 0.0, 0
    prices, dollars, openings = [], [], []
    for bars in sessions.values():
        bars.sort(key=lambda item: item[0])
        closes = [float(row["close"]) for _, row in bars]
        volumes = [float(row["volume"]) for _, row in bars]
        prices.append(median(closes))
        dollars.append(sum(c * v for c, v in zip(closes, volumes, strict=True)))
        cutoff = (datetime.combine(bars[0][0].date(), REGULAR_OPEN, tzinfo=MARKET_TZ)
                  + timedelta(minutes=opening_minutes))
        openings.append(sum(volume for (stamp, _), volume in zip(bars, volumes, strict=True)
                            if stamp < cutoff))
    return median(prices), median(dollars), median(openings), len(sessions)


def load_env_file(path: Path) -> bool:
    """Populate os.environ from a dotenv file without overriding real exports.

    The Massive adapter performs its own load, but only once a download is
    already under way.  The credential check below has to happen before the
    first request, so the file is read here too.
    """
    if not path.is_file():
        return False
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() and not key.lstrip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
    return True


def command_stats(args: argparse.Namespace) -> int:
    env_path = Path(args.env_file)
    found = load_env_file(env_path)
    if not os.environ.get("MASSIVE_API_KEY"):
        raise SystemExit(
            f"MASSIVE_API_KEY is not set.\n"
            f"  Looked in: {env_path.resolve()} ({'found' if found else 'MISSING'})\n"
            f"  Fix: create that file with a line reading MASSIVE_API_KEY=<your key>\n"
            f"       (no quotes, no spaces around '='), or set the variable in your shell.")
    campaign_start = _iso(args.campaign_start)
    lookback_end = _iso(args.lookback_end)
    if lookback_end > campaign_start:
        raise SystemExit(
            f"lookback_end {lookback_end} is inside the campaign window starting "
            f"{campaign_start}; selection would leak outcomes into the universe")
    lookback_start = lookback_end - timedelta(days=args.lookback_calendar_days)
    symbols = [line.strip().upper() for line in Path(args.pool).read_text().splitlines()
               if line.strip() and not line.startswith("#")]
    if not symbols:
        raise SystemExit(f"no candidate symbols in {args.pool}")

    computed = []
    for index, symbol in enumerate(symbols, start=1):
        print(f"[{index}/{len(symbols)}] {symbol}", file=sys.stderr)
        try:
            normalized_path, _ = download_minute_bars(
                symbol=symbol, start=lookback_start.isoformat(),
                end=lookback_end.isoformat(), output_root=Path(args.data_root))
        except Exception as error:  # noqa: BLE001 - one bad symbol must not end the pull
            print(f"  skipped: {type(error).__name__}: {error}", file=sys.stderr)
            continue
        rows = normalized_path.read_text(encoding="utf-8").splitlines()
        price, dollars, opening, sessions = _session_statistics(rows)
        computed.append({"symbol": symbol, "sessions_observed": sessions,
                         "median_price": price, "median_dollar_volume": dollars,
                         "median_opening_volume": opening})

    _write_once(Path(args.output), {
        "schema_version": "athena-orb-m-universe-stats-v1",
        "lookback_start": lookback_start.isoformat(),
        "lookback_end": lookback_end.isoformat(),
        "campaign_start": campaign_start.isoformat(),
        "campaign_end": args.campaign_end,
        "pool_size": len(symbols), "statistics": computed,
    })
    print(f"wrote {args.output} ({len(computed)}/{len(symbols)} symbols)")
    return 0


def command_freeze(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.stats).read_text(encoding="utf-8"))
    rule = SelectionRule(universe_size=args.universe_size,
                         lookback_sessions=args.lookback_sessions)
    statistics = [SymbolStatistics(item["symbol"], item["sessions_observed"],
                                   item["median_price"], item["median_dollar_volume"],
                                   item["median_opening_volume"])
                  for item in payload["statistics"]]
    manifest = select_universe(
        statistics, rule, provenance=PoolProvenance(args.provenance),
        lookback_start=_iso(payload["lookback_start"]),
        lookback_end=_iso(payload["lookback_end"]),
        campaign_start=_iso(payload["campaign_start"]),
        campaign_end=_iso(payload["campaign_end"]))
    _write_once(Path(args.output), manifest.to_payload())
    print(f"wrote {args.output}: {len(manifest.members)} symbols, "
          f"hash {manifest.identity_hash[:16]}")
    if manifest.carries_survivorship_bias:
        print("WARNING: pool provenance is CURRENT_SNAPSHOT. Names delisted during "
              "the campaign cannot appear, so results carry survivorship bias.",
              file=sys.stderr)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    stats = sub.add_parser("stats", help="pull lookback bars and compute statistics")
    stats.add_argument("--pool", required=True, help="newline-delimited candidate symbols")
    stats.add_argument("--lookback-end", required=True, help="YYYY-MM-DD, before campaign")
    stats.add_argument("--lookback-calendar-days", type=int, default=120)
    stats.add_argument("--campaign-start", required=True)
    stats.add_argument("--campaign-end", required=True)
    stats.add_argument("--output", required=True)
    stats.add_argument("--data-root", default="data",
                       help="where raw, normalized and manifest files are written")
    stats.add_argument("--env-file", default=".env",
                       help="dotenv file supplying MASSIVE_API_KEY")
    stats.set_defaults(func=command_stats)

    freeze = sub.add_parser("freeze", help="apply the rule and write the manifest")
    freeze.add_argument("--stats", required=True)
    freeze.add_argument("--output", required=True)
    freeze.add_argument("--universe-size", type=int, default=50)
    freeze.add_argument("--lookback-sessions", type=int, default=60)
    freeze.add_argument("--provenance", required=True,
                        choices=[item.value for item in PoolProvenance])
    freeze.set_defaults(func=command_freeze)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
