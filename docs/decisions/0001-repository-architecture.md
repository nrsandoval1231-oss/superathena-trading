# ADR 0001: Independent strategies, shared infrastructure

Decision: keep each strategy self-contained for research and signal logic while sharing contracts, data, evaluation, risk and execution.

The trading source was migrated under that rule. `src/athena_trading` links one copy of each module into the strategy and core directories. On 2026-10-14 Nick excluded Athena Core from the migration. It stays an external, unmigrated dependency.
