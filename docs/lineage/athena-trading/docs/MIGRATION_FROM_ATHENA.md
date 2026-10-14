# Migration Plan: Athena → Athena Trading

> **HISTORICAL — superseded.** This plan described the Athena → Athena Trading split. Completion is recorded in [MIGRATION_COMPLETE.md](MIGRATION_COMPLETE.md). Product direction is [Athena Trading Canon](ATHENA_TRADING_CANON.md) and [BUILD_PLAN.md](BUILD_PLAN.md). The phases below are kept as a dated record.

Do not delete historical material from Athena during the first migration pass.

## Classification

Every source artifact must be assigned one class before movement:

1. `ATHENA_CORE` — remains in Athena.
2. `ARENA_GAUNTLET` — remains in Athena.
3. `TRADING_DOMAIN` — copy/migrate into Athena Trading, then replace with a pointer or historical note when appropriate.
4. `HISTORICAL` — preserve for lineage; archive rather than treating as current canon.

## Known trading-domain candidates

- `src/athena_lab/`
- trading-specific market-data integrations and Alpaca documents
- trading execution/fill/slippage/timing implementations
- trading episode runners
- trading-specific strategy and exit-policy experiments
- APDE trading configuration/implementation
- observed equity datasets/results and scale-readiness material
- paper-trading adapters

## Known Athena-Core candidates

- Arena abstractions that are domain-neutral
- Gauntlet validation/authority foundation
- policy genome and lineage concepts
- evidence/experience/lesson lifecycle
- domain-neutral adaptation contracts
- Athena mathematical and architectural canon

## Important rule

If an artifact mixes generic Athena architecture with trading implementation, split the concepts rather than moving the whole artifact blindly. Preserve the original in Git history.

## Migration phases

### Phase 1 — Identity
Completed: initialize Athena Trading and freeze the domain boundary and reconstructed ORB baseline.

### Phase 2 — Archaeology
Inventory the Athena repository and produce a source-of-truth migration matrix.

### Phase 3 — Extract
Copy trading-domain code/docs/tests into Athena Trading with provenance notes and working tests.

### Phase 4 — Decouple
Replace trading assumptions in Athena Core with explicit domain adapter contracts.

### Phase 5 — Verify
Both repositories must run independently. Athena Core must not require market/broker concepts. Athena Trading must declare its Athena interface explicitly.

### Phase 6 — Clean
Only after verification, simplify Athena's current docs/root layout and mark superseded trading documents as migrated/historical.
