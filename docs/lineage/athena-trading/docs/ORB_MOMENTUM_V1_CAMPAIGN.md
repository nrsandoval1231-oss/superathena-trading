> **RESEARCH REFERENCE — product direction restored 24 September 2026.** This document retains its experiment/component history and restrictions. Its product-level next-step instructions are superseded by [Athena Trading Canon](ATHENA_TRADING_CANON.md) and [Build Plan](BUILD_PLAN.md). Read [Implementation Status](IMPLEMENTATION_STATUS.md) for current capability.

# ORB-Momentum V1 Campaign Contract

Status: point-in-time candidate pool and universe frozen; TRAINING-only
evaluation ready. Do not score sealed evidence until partition identities and
the remaining campaign contract are frozen.

- Universe: 50 liquid U.S. equities selected by a frozen, outcome-blind liquidity rule
  from a 400-name point-in-time candidate pool.
- Window: 2024-01-02 .. 2025-12-31, regular-session minute bars.
- Opening range: 09:30–09:45 ET.
- Trigger: first completed 1-minute close beyond ORH/ORL; opening-candle color is not a directional gate.
- Both sides: one initial long and one initial short attempt may independently qualify per symbol/session; one continuation re-entry per direction.
- Initial stop: long `max(ORL, entry - 1*ATR)`; short `min(ORH, entry + 1*ATR)`, subject to minimum tradable distance.
- R: frozen from entry to initial stop.
- Re-entry impulse: actual entry to peak favorable excursion.
- Promotion evidence floor: 300 paired eligible episodes. Fewer means `INSUFFICIENT_EVIDENCE`.
- Partition identities/hashes must be frozen before outcome inspection.
- Sealed holdout cannot be used for tuning.
- Explicit costs/slippage required.
- No overnight positions.

## Dataset identity

Fixed once and recorded here so it is not re-derived. See `ORB_M_STATUS.md` for
the working state behind these values.

| Field | Value |
|---|---|
| Lookback | 2023-08-31 .. 2023-12-29 (120 calendar days, 84 sessions) |
| Candidate pool | `configs/orb_m_candidate_pool_point_in_time.txt` |
| Pool provenance | `POINT_IN_TIME`; `carries_survivorship_bias: false` |
| Pool manifest | `configs/orb_m_candidate_pool_point_in_time.manifest.json` |
| Frozen universe | `data/universe/manifest.json` (50 names) |
| Universe manifest hash | `2533dd04d370bbe0c667bfcc96d402434db4bf168432cb3273e9816fdb2c854a` |

The lookback ends strictly before the campaign opens, and both the pool builder
and `stats` refuse to run otherwise: a pool or a ranking that has seen the
campaign has seen its own outcomes.

The pool is built from daily grouped aggregates, one file per session listing
every ticker that traded that day, intersected with the provider's common-stock
reference **as of the lookback end**. Asking for today's listings instead would
reintroduce survivorship bias through the type filter, which is the failure the
point-in-time construction exists to avoid.

The superseded `configs/orb_m_candidate_pool.txt` was assembled from model
knowledge of currently liquid names and carries survivorship bias by
construction. It must not be used to freeze a universe for this campaign.
