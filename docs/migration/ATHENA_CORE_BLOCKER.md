# Athena Core exclusion

On 2026-10-14 Nick decided that the Athena Core repository is outside this migration.

| Field | Value |
|---|---|
| Repository | https://github.com/nrsandoval1231-oss/Athena |
| Historical anchor | `adba694563751256f5f5e95ad47079b37c7697ec` |
| Disposition | `excluded-external-dependency` |
| Decision | Athena stays an external, unmigrated dependency |

SuperAthena keeps the trading adapter that already lived in `athena-trading` (`athena_adapter`, including `canonical_hash` and the Jev client). It does not vendor Arena, Gauntlet, or any other Core module. Core must still not import market, broker, ticker, ORB, or PnL types from this repository.

The anchor remains a historical reference. It is not a file inventory, and this migration does not require one.
