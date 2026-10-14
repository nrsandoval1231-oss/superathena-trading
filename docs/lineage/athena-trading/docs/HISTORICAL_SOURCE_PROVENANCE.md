# Historical Source Provenance

The following implementation lineage originated in `nrsandoval1231-oss/Athena` before the domain split.

## Trading-owned source families

- `src/athena_lab/massive*.py` → market-data/provider lineage
- `src/athena_lab/alpaca_corporate_actions.py` → Alpaca market/reference lineage
- paper/broker adapters and `configs/legacy/athena_paper_risk_v1.json` → paper execution/risk lineage. Older notes cited `configs/athena_paper_risk_v1.json`; that path is not in this tree. The file labels itself `HISTORICAL_NOT_ORB_V1_AUTHORITY` and is not the active pilot policy.
- ORB observation/scanning scripts → ORB strategy lineage
- fill/slippage/timing diagnostics → trading execution research lineage
- APDE trading state machine → position-management lineage

## Deliberately not copied as trading ownership

`models.py`, `episodes.py`, generic evidence semantics, Arena, Gauntlet, policy lineage and validation authority remain Athena Core concepts even when their earliest implementation used trading terminology.

Historical files in Athena are compatibility snapshots. They should not receive new trading features after this split.

## Market data sources

Implementation lineage is not the only provenance that matters; the data a
campaign is measured on carries its own.

**Minute bars — Massive**, `massive_stocks_aggregates_v2`, unadjusted, pulled on
demand into `data/` (gitignored, regenerable). Extended hours included: bars run
04:00–20:00 ET, so anything that groups them by day must resolve to
`America/New_York` first.

**Daily grouped aggregates — Polygon**, unadjusted, one file per session listing
every ticker that traded that day. Held outside this repository under the
Trading project. This is what makes the candidate pool point-in-time: a name
that stopped trading in 2024 is still present in its 2023 files. The files
consumed by a pool build are hashed individually into that pool's manifest, so
the pool traces back to exact bytes rather than to a directory path.

**Ticker reference — Polygon** `/v3/reference/tickers`, queried with an explicit
`date` so the common-stock filter reflects the lookback rather than the present.
The same endpoint cannot be trusted for *current* listing status on the plan in
use: it returns 404 for tickers that plainly still trade. Measure disappearance
from the grouped aggregates instead.

### Rejected for ORB-M

The Polygon minute cache under the Trading project (and its copies under
`Desktop/Eggman`) is 1-minute but regular-session only, and covers a median of
11 days per symbol clustered around each symbol's earnings dates. It is an
earnings-event cache, not a panel, and cannot substitute for a universe pull.

## Macro — ALFRED vintages

The macro adapter and its point-in-time rules are documented in
`docs/ALFRED_MACRO_SOURCE_PROVENANCE.md`. No ALFRED series has been pulled into
this repository; coverage has not been measured.
