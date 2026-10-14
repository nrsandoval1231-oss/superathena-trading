# ALFRED Macro Source Provenance

Companion to `docs/HISTORICAL_SOURCE_PROVENANCE.md` and
`docs/EXOGENOUS_SOURCES_V1.md`. This is the point-in-time record for the macro
vendor adapter: how a FRED ALFRED vintage observation becomes an
`ExogenousRecord`, and what that adapter is not allowed to mean.

Status: adapter exists and is fixture-tested. No ALFRED series has been
acquired. Coverage has not been measured. This document does not freeze a V2
claim, register a protocol, or assign a dataset.

## Why ALFRED, and only ALFRED

ORB-M decides at 09:45 ET. Macro matters as a scheduled-event flag: an 08:30
ET print lands seventy-five minutes earlier and is visible at the decision
using the number as it stood that morning.

The trap is the current-view FRED series. `fred/series/observations` with the
default real-time period (today/today) returns the latest restated values.
A backtest that reads it sees January CPI as it exists *now*, not as it was
published on release day. Nothing in that response tells you the substitution
happened.

ALFRED is the vintage archive of the same series. Each observation carries a
real-time window: `date` is the period the number is about, `realtime_start`
is the first date that vintage was available in the archive, `realtime_end`
is when a later vintage superseded it (`9999-12-31` if it has not been). That
is the as-of split the exogenous contract already enforces as `event_at` and
`available_at`.

## Endpoints

Live pulls, when they happen, are pinned to `https://api.stlouisfed.org` and
to these two paths only:

- `GET /fred/series/vintagedates` — dates on which a series released a new
  value or a revision. This is how scheduled prints are listed as vintage
  dates rather than inferred from a current-view series.
- `GET /fred/series/observations` — vintage observations, and **only** with an
  explicit vintage constraint: `vintage_dates=...` **or** both
  `realtime_start` and `realtime_end`. `file_type=json`, `units=lin` (no
  transformation), `output_type=1` (observations by real-time period, so each
  vintage window is its own row).

The fetch refuses to construct a request that omits the vintage constraint.
That omission is what turns this endpoint into the current-view series, and
it is not a valid ALFRED pull.

`FRED_API_KEY` is required for any live call and is read from the
environment. Absence fails closed before the transport runs. Tests never
invoke the live path; CI proves the adapter against
`configs/fixtures/alfred_vintage_observations_v1.json`, which is a synthetic
ALFRED-shaped payload, not a dump.

## How `available_at` is derived

ALFRED vintage fields are calendar dates, not instants. The adapter will not
invent a clock time. A row without a timezone-aware `available_at` is
refused, as is a naive ISO string.

Callers that want the ORB-M scheduled-print convention run
`stamp_scheduled_availability` first. That helper combines `realtime_start`
with 08:30 America/New_York, which is the BLS/BEA-style print time the source
spec uses, and is the instant that is visible by 09:45 ET the same day. DST
is resolved by `zoneinfo`. This is a documented convention, not a timestamp
FRED supplied. A row may instead carry its own timezone-aware `available_at`;
the helper will not overwrite one.

`event_at` is `date` at 00:00 America/New_York: FRED's period label for the
observation, which is when the economic fact is about, not when anyone could
see it. The two timestamps stay separate. Visibility remains
`available_at <= decision_time` and nothing else.

## How `external_id` is synthesized

```
alfred:{series_id}:{observation_date}:{vintage_date}
```

`vintage_date` is `realtime_start`. The original January CPI print and a later
revision of that same month are different ids, because they are different
facts. `assert_stable_availability` matches on `(source, payload.external_id)`.
Re-pulling the *same* vintage with a moved `available_at` keeps this id and is
rejected — that is the anti-backfill guard. Sharing one id across vintages
would make a legitimate revision look like a retimestamped original and the
guard would refuse to store the revision.

## Scheduled print versus revision

`annotate_alfred_revisions` groups rows by `(series_id, date)` and stamps
`original_realtime_start` as the earliest `realtime_start` in that group.

- A **scheduled print** is the first vintage of an observation date:
  `original_realtime_start == realtime_start`. `revision_of` is `None`, so
  `visible_records` will show it once `available_at` is due. Payload
  `kind` is `scheduled_print`.
- A **revision** is any later vintage of that same observation date:
  `original_realtime_start < realtime_start`. `revision_of` is the original's
  `external_id`. Payload `kind` is `revision`. Revisions are admitted to the
  store so their existence is auditable, and they are never visible. A replay
  at a date after the revision still sees the original print.

The adapter requires `original_realtime_start`. An unannotated mixed-vintage
dump cannot pass a revision off as a second original.

Consensus / surprise is not in ALFRED. The adapter does not invent
`surprise_z`. Release-event flags ship without it.

## What this adapter does not do

- It does not call or treat `fred/series/observations` without a vintage
  constraint as a source of truth. That is the current-view series.
- It does not fall back to the current-view series when a vintage is missing.
- It does not ingest a historical dump into git, store an API key, or require
  a network to pass CI.
- It does not claim that coverage has been measured, that a series list is
  the campaign universe, or that 08:30 ET is a FRED-supplied timestamp.
- It does not freeze a V2 claim contract, register a V2 protocol, draw or
  redraw the dataset assignment, or touch the consumed AAT-V1 holdout, claim
  contract, or negative-knowledge registry.
- It does not change paper or execution authority. `LIVE` stays rejected.
  `ABSENT` stays the default.
- It does not change compressor scoring semantics. `compress_macro` still
  reads visible macro records; the adapter's job is to make the original
  print the one that is visible.

## Mapping onto the existing record

One vintage observation, one `ExogenousRecord`. `source` is `macro`, `symbol`
is `None` (market-wide). No second record type. Ingest remains
`normalize(..., source="macro", adapter=alfred_adapter)` then
`write_record_store`.
