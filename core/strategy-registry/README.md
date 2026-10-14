# Strategy registry

`strategy_registry` reads `strategies/**/strategy.yaml` and skips the template. Nested blocks are not runtime fields. A runtime entrypoint is imported. A specification-only archive (`research-specification-only`, or `execution_enabled: false`) is registered and is not imported. The registry does not route orders.
