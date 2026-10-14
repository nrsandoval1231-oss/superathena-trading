# Athena Alpaca Paper Adapter V1

> Migrated from the historical Athena repository as trading-domain provenance.

The adapter is pinned to the Alpaca paper endpoint and rejects every other base URL. It uses dedicated paper credentials; market-data or live-trading credentials must not be reused or exposed.

`preflight()` is read-only: it checks the paper account and open orders and returns a redacted, hashed report. `submit()` exists only for a `PAPER` order intent with `execution_authority: ABSENT`; the runtime does not call it automatically. Explicit paper-run authorization is required before any submission.

Historical guardrail: at most three open positions. Historical paper-only risk policy: 2% maximum account-equity loss per trade, 6% daily-loss halt, three simultaneous positions. These values are preserved as historical research settings, **not automatically adopted by ORB-Momentum V1 and never authorized for live money**.

At migration time the historical continuous live-market paper loop was not implemented and the system had placed zero broker-paper orders.
