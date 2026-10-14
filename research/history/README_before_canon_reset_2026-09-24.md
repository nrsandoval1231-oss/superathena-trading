> **Superseded on 24 September 2026.** Historical snapshot. Product authority: [Athena Trading Canon](../../docs/ATHENA_TRADING_CANON.md). Relative links below retain their original context.

# Athena Trading

Canonical trading-domain repository powered by Athena Core.

Athena itself is domain-neutral adaptive intelligence. This repository owns market data, strategies, trading risk, position management/APDE, fills/execution simulation, backtesting, paper trading, and trading-domain experiments.

## Current baseline

`ORB-Momentum V1`: 15-minute opening range, 1-minute close confirmation, both directions independently live, ATR/structure initial R, early momentum harvest, APDE, dynamic trailing, peak-profit retention, and separately risked continuation re-entry.

The point-in-time 400-name candidate pool and 50-name universe are frozen. The
full-session TRAINING evaluator and AAT-V1 readiness boundary are implemented;
the current readiness state is
`READY_TRAINING_ONLY_WITH_PROVIDER_MODEL_MUTABILITY`. No performance or
learned-adaptation claim has been made. AAT / TRAINING execution authority
remains `ABSENT`.

A preregistered TRAINING-only gate promotes one abstention lesson (PASS versus
standard sizing) and retains two rejected alternatives as negative knowledge.
The subsequent 300-opportunity four-arm TRAINING comparison is complete and
audit-passing, but remains in-sample prompt-steering evidence—not proof that
Athena adaptation works. The final claim contract is frozen. The single-use
authorization gateway and deterministic claim scorer are ready. The AAT-V1
sealed holdout has been identity-verified and exported; it is consumed
(`INVALID_EVIDENCE`) and must not be tuned, resealed, or reused. No final
claim is supported: the frozen compiler found only 249 of the required 300
qualified opportunities, so evaluation ended `INVALID_EVIDENCE` before any
Actor call.
The consumed dataset assignment and authorization are recorded in a tracked
negative-knowledge registry that future export paths must check. The paper
path does not read, write, or reseal that registry.

Paper execution is a separate path. An operator may grant `PAPER` authority so
ORB-M decisions can be sized, halt-gated, and submitted to an Alpaca **paper**
adapter (or a fixture double). `LIVE` is not a value and is rejected. Default
authority in `configs/orb_m_paper_session_v1.json` is `ABSENT`. This is not
live trading.

## Layout

- `src/athena_trading/strategies/` — trading strategies
- `src/athena_trading/orb_m/` — ORB-M engine (constitution, entry, management, fill sim)
- `src/athena_trading/execution/` — PAPER-only authority, order intent, broker protocol
- `src/athena_trading/risk/` — constitutional halt gate (refuse before send)
- `src/athena_trading/paper/` — paper session runner, fixture broker, Alpaca paper adapter
- `src/athena_trading/market_data/` — provider adapters (Massive historical; Alpaca corporate actions)
- `src/athena_trading/position_management/` — APDE/trailing/harvest logic
- `configs/` — trading-only risk/research configuration
- `docs/` — canon, strategy specs, provenance and migration record
- `tests/` — trading-domain tests

## Paper session (not live trading)

The paper loop can consume ORB-M campaign decisions from
`run_symbol_session`, or **walk a recorded bar sequence** bar by bar.
Each completed bar is shown to the engine as a prefix. When a sendable
close-through fires, it builds an entry `OrderIntent`, refuses the send if
`SessionRiskState` would breach `max_open_positions` / `max_daily_loss_r` /
`max_drawdown_r`, then submits / cancels / tracks through a `BrokerAdapter`.

It does **not** stream harvests, trails, or hard-flat exits to the broker;
those remain engine-side (`run_position` on the arrived prefix so the halt
ledger can close, not broker-side stops). It does **not** pull Massive bars.
It does **not** enable live money. It does **not** reopen the AAT holdout.
Live streaming is not implemented.

Walk fixture bars (no network, no API keys):

```text
python scripts/run_orb_m_paper.py --walk-bars
```

Halt-gate demonstration on that walk:

```text
python scripts/run_orb_m_paper.py --walk-bars --halt-demo
```

Recorded bars use schema `athena-orb-m-paper-bars-v1` (timezone-aware
timestamps). The shipped fixture is `configs/fixtures/orb_m_paper_bars_v1.json`.
Pass `--bars path.json --authority PAPER` to walk another file. Naive
timestamps fail closed.

The earlier decision-dump dry-run remains:

```text
python scripts/run_orb_m_paper.py --dry-run
```

Optional Alpaca paper call. Missing `ALPACA_API_KEY` / `ALPACA_API_SECRET`
fails closed. With keys, the default is a read-only preflight; `--submit-demo`
would submit the synthetic demo to paper and is never implied by `--dry-run`.

```text
python scripts/run_orb_m_paper.py --broker alpaca --authority PAPER
```

With no flags, config authority stays `ABSENT` and nothing is sent.

## Migration status

Forward ownership has migrated from the historical trading Lab inside `Athena`. Historical copies remain there only where required to reproduce old Arena/Gauntlet experiments and receipts. New trading work belongs here.

See `docs/MIGRATION_COMPLETE.md`, `docs/MIGRATION_MATRIX_V1.md`,
`docs/ORB_M_STATUS.md`, and `docs/AAT_V1_TRAINING_RUNNER.md`.

## Proposed next experiment

`docs/AAT_V2_VISION.md`, `docs/AAT_V2_PLAN.md` and
`docs/EXOGENOUS_SOURCES_V1.md` propose AAT-V2: an exogenous (non-price)
evidence layer, provider-portable Actor identity, and a non-consuming holdout
sufficiency probe.

Phases 1 and 2 of that plan are built. `src/athena_trading/exogenous/`
enforces point-in-time visibility over non-price evidence and compresses it
into a frozen, bucketed feature set; it imports nothing from `orb_m/` or
`aat_v1/`, and the strategy suite passes with the package deleted.
`aat_v1/providers.py` makes Actor identity provider-scoped without moving any
registered V1 digest, and `probe_holdout_sufficiency` answers the
is-the-dataset-big-enough question without consuming an authorization — the
gap that cost the V1 holdout at 249 of 300.

Phase 3's machinery is built in `src/athena_trading/aat_v2/`, and the V2
dataset assignment is drawn and frozen at
`configs/aat_v2_dataset_assignment_v1.json` — 35 TRAINING and 15 holdout
symbols, split by symbol, drawn before any exogenous feature existed. The
comparison itself is blocked on data acquisition: the claim contract requires a
measured exogenous coverage rate and refuses to freeze against an intended one.

A full progress, status and handoff report is at `docs/AAT_V2_HANDOFF.md`.

No phase holds registered evidence or supports any claim. No contract is
frozen and no protocol registered. AAT-V1 remains frozen and closed, and its
`PROVIDER_MODEL_MUTABILITY` limitation stands.
