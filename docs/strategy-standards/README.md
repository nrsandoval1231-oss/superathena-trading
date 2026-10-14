# Strategy directory standards

A strategy directory contains the implementation, a `strategy.yaml`, a hypothesis, and a README. Tests for the migrated code stay in `tests/` so the original suite remains one run.

A runtime `strategy.yaml` is a flat `key: value` manifest. Required fields:

- `id`, `version`, `status`, `entrypoint`
- `promotion` (`not-promoted` until a separate human promotion)
- `overnight` (`forbidden` for every current strategy)
- `authority` (`PAPER-or-ABSENT`)

A research archive may set `status: research-specification-only`, `entrypoint: null`, and `execution_enabled: false`. Nested blocks under that manifest are not runtime fields. `discover` records the archive and does not import it.

`athena_trading.strategy_registry.discover` loads these files and skips `strategies/_template`. `load_entrypoint` imports a runtime module and refuses a null entrypoint. Registration does not submit an order.

Rules:

- Do not put a second broker client in a strategy. Order sending goes through `broker_adapters` and `execution`.
- Do not import `aat_v1` or `aat_v2` from a product arm, the paper stack, or `core`.
- Do not rename `aat_v1` or `aat_v2`. Those module names are part of the frozen experiment identity.
- Do not edit consumed holdout files or `INVALID_EVIDENCE` dispositions.
- Do not promote a historical experiment by moving it to a product directory.
- The ORB constitution fields are the strategy definition. Changing one defines a different strategy.

`data/ingestion/exogenous` must not import `orb_m` or `aat_v1`. The deterministic ORB package stays runnable without that data package.
