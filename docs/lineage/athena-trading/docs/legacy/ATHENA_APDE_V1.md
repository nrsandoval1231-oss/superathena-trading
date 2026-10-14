# Athena APDE V1

> Migrated from `nrsandoval1231-oss/Athena/docs/ATHENA_APDE_V1.md` during the Athena/Athena-Trading separation. Preserved as trading-domain provenance.

The Adaptive Position Defense Engine is a deterministic, paper/replay-only state machine: `EXPLORE → PROTECT → HARVEST → DEFEND → EXIT`. It translates frozen position state into one allowed post-entry action and cannot route an order or grant execution authority.

Forced exits take priority: risk halt, session deadline, then thesis invalidation. Profit protection, harvesting, trailing, and adverse-risk defense follow. The LLM may propose a post-entry action in future work, but the APDE and risk engines remain the final authorization path.
