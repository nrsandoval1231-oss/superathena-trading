# Dependencies

Runtime:

- Python 3.11+ (verified on 3.12.3)
- `pyarrow` for the ORB candidate-pool builder
- `numpy>=2`, required by the installed PyArrow build
- `tzdata` on Windows only; Linux uses the system time zone database

The package name on import is `athena_trading`. The distribution name is `superathena-trading`. `src/athena_trading` links each subpackage to the directory that owns it. A wheel copies those files into one install tree.

External services, used only when an operator runs a paper command with credentials:

| Service | Module | Notes |
|---|---|---|
| Alpaca paper API | `broker_adapters.alpaca` | Paper host only. Keys come from the environment |
| TypeSafe Jev | `athena_adapter.jev` | `jev-1.13.0`. A transport failure is not an approval |
| Nasdaq earnings calendar | earnings calendar | Free calendar, no SLA |
| Massive / Polygon, GDELT, ALFRED | market data and exogenous | Research and ingestion. Not required for the fixture suite |

Athena Core is not installed and is not importable from this environment. See [ATHENA_CORE_BLOCKER.md](ATHENA_CORE_BLOCKER.md).

Not pinned: a live trading dependency. `LIVE` is not an authority.

Environment names are listed in `.env.example` and in `deploy/paper.env.example` and `deploy/earnings.env.example`. Values stay in the host secret store. This repository does not contain keys.
