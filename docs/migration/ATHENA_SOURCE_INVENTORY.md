# Athena strategy migration inventory

Source: https://github.com/nrsandoval1231-oss/athena-trading

- Predictive Intraday: partially implemented product arm.
- Earnings Adaptive: partially implemented event-driven product arm; earnings PR #29 was unmerged in inspected README.
- ORB-M: frozen opening range momentum baseline and reusable component.
- Legacy Strategy Research: historical AAT V1/V2 experiments, not production. Stored under strategies/custom/legacy-strategy-research; original source labels retained only for traceability.

The inventory folders now hold the implementations. Provenance is in [source-manifest.json](source-manifest.json). Holdout bytes were copied unchanged. LIVE stays rejected.

On 2026-10-14 Nick excluded Athena Core from this migration. It stays an external, unmigrated dependency. See [ATHENA_CORE_BLOCKER.md](ATHENA_CORE_BLOCKER.md).
