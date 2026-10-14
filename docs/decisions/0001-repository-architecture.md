# ADR 0001: Independent strategies, shared infrastructure

Decision: keep each strategy self-contained for research and signal logic while sharing contracts, data, evaluation, risk and execution.

The trading source was migrated under that rule. `src/athena_trading` links one copy of each module into the strategy and core directories. Athena Core was not imported because that repository could not be read.
