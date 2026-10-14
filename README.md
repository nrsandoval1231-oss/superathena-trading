# SuperAthena Trading

Canonical repository for Athena trading strategies, shared execution infrastructure, research, and paper operations.

Two product arms share one execution stack: **Predictive Intraday** and **Earnings Adaptive**. **ORB Momentum** is the frozen opening-range component and research baseline. **Legacy Strategy Research** keeps historical experiments under their original module names. Those experiments are not production strategies.

The target decision path is Astra 6, then Jev, then deterministic code. Astra 6 is the selected model name. Its provider, API model id, and access were not verified in the source and are not verified here. The running paper path is Jev-only (`jev-1.13.0`). Deterministic code owns calculations, freshness, sizing, shared account checks, order ids, and the APDE state order. Protective exits do not wait for a model.

**LIVE is rejected.** This migration does not start a broker session and does not change the Hostinger paper service.

| Question | Where |
|---|---|
| What is implemented? | [docs/migration/STATUS.md](docs/migration/STATUS.md) |
| How is the code laid out? | [docs/architecture/README.md](docs/architecture/README.md) |
| Which strategies exist? | [docs/migration/STRATEGY_INVENTORY.md](docs/migration/STRATEGY_INVENTORY.md) |
| Where did each source file go? | [docs/migration/MIGRATION_MANIFEST.md](docs/migration/MIGRATION_MANIFEST.md) |
| How do I test? | [docs/migration/VERIFICATION.md](docs/migration/VERIFICATION.md) |
| Historical Athena Trading documents | [docs/lineage/athena-trading/](docs/lineage/athena-trading/) |

Source anchors, verified before the move:

- `nrsandoval1231-oss/athena-trading` @ `8bd0e7289e0a4899ec7e12291ca02a2c883c583d` (also the remote `main` head)
- `nrsandoval1231-oss/Athena` @ `adba694563751256f5f5e95ad47079b37c7697ec` was not readable. See [the blocker](docs/migration/ATHENA_CORE_BLOCKER.md).
