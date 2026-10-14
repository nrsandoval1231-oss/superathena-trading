# Paper trading

`paper/` is the shared paper runtime: sessions, the fixture broker, learning, ownership, and the compatibility aliases. The Alpaca adapter, journal, shared gate, and strategy runners live in `core/` and `strategies/` and are aliased here so older imports keep working.

`deploy/athena-paper.service` and `deploy/athena-earnings.service` are the unit texts from the source anchor. They still start `/opt/athena-trading` and `python -m athena_trading.paper.cloud` or `paper.earnings_cloud`. Those module paths alias the migrated implementations. This migration did not install the units and did not restart the Hostinger service.

`deploy/install.sh` refuses to run when either service is already active. Do not point it at the live host as part of migration.

PAPER is opt-in. LIVE is rejected. Running a paper script from this tree can send a paper order if the operator passes PAPER and supplies keys. The migration verification does not do that.
