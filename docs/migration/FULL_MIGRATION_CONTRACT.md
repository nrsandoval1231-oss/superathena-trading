# Full Athena consolidation — migration contract

## Immutable source anchors
- Trading source: nrsandoval1231-oss/athena-trading @ 8bd0e7289e0a4899ec7e12291ca02a2c883c583d
- Shared Core source: nrsandoval1231-oss/Athena @ adba694563751256f5f5e95ad47079b37c7697ec
- Destination: nrsandoval1231-oss/superathena-trading

## Scope
1. Inventory all source-tracked files and categorize strategy implementations, contracts, tests, configs, research, docs, scripts, workflows and data manifests.
2. Map the original strategy modules to dedicated strategy packages (ORB Momentum, Predictive Intraday, Earnings Adaptive, historical research). Do not invent executable behavior.
3. Migrate needed shared infrastructure once under core/, preserving dependency boundaries. Avoid copying Athena Core wholesale if only an adapter is required.
4. Preserve source SHA, original path and relevant commit identity for each migrated file, with a manifest and SHA-256 checksums.
5. Preserve historical experiments, frozen/consumed holdouts, invalid evidence labels and test fixtures without reinterpretation. Keep large/private data outside Git.
6. Carry forward tests and adapt imports, packaging, config and CI. Test deterministic risk, same-session flatten, broker reconciliation, APDE, model fallbacks and paper order idempotency.
7. Reconcile existing deployed paper runtime separately; do not redirect deployment or mutate credentials without explicit approval.
8. Keep LIVE disabled. No broker operations or real orders as part of migration.
9. Compare source and destination inventories, document intentional omissions, run tests, and only then consider merging.

## Acceptance
- Every eligible tracked source file accounted for as migrated, intentionally excluded, or external dependency.
- Strategy imports and tests pass with no silent logic changes.
- Evidence and history provenance retained; invalid holdouts remain invalid.
- No new live authority, changed deployed process, or modified source repo.
- Exact commits and validation receipts retained.

## Status
Trading-source migration is implemented on this branch from anchor `8bd0e7289e0a4899ec7e12291ca02a2c883c583d`. Every tracked trading file is migrated, import-adjusted, or preserved byte-for-byte under `docs/lineage/athena-trading/`. See [MIGRATION_MANIFEST.md](MIGRATION_MANIFEST.md) and [STATUS.md](STATUS.md).

Athena Core anchor `adba694563751256f5f5e95ad47079b37c7697ec` was not readable. That blocker is [ATHENA_CORE_BLOCKER.md](ATHENA_CORE_BLOCKER.md). The pull request stays open until that source can be accounted for. No live service was changed.
