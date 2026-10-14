# SuperAthena Trading

A unified repository for independent, reproducible trading strategies.

## Principles
- One strategy per directory under `strategies/`, using `strategies/_template/`.
- Strategies produce signals and orders through shared contracts; they do not directly access brokers.
- Shared portfolio risk and execution controls cannot be overridden by a strategy.
- Backtest and live use the same strategy logic, with explicit configuration and mode.
- No secrets, broker credentials, proprietary datasets, or large generated results in Git.
- No live trading enabled by repository scaffolding.

## Structure
- `strategies/`: independently versioned strategies and reusable template
- `core/`: interfaces, registry, portfolio, risk, execution, broker adapters, accounting
- `data/`: schemas, ingestion, normalization, catalog
- `evaluation/`: backtesting, walk-forward, stress, benchmarks, reporting
- `research/`: cross-strategy hypotheses and market studies
- `operations/`: paper/live orchestration, monitoring, reconciliation
- `docs/`: architecture, standards, risk policy, decisions
- `tests/`: integration and contract tests

## Adding a strategy
Copy `strategies/_template` to `strategies/<unique-slug>`, complete `strategy.yaml` and `hypothesis.md`, implement the signal/entry/exit/sizing modules, and add deterministic tests. A strategy is not approved for live deployment merely because it exists in the registry.
