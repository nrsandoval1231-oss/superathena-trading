# ORB Momentum

Frozen 15-minute opening-range breakout. The constitution in `orb_m/constitution.py` is the strategy definition: 09:30–09:45 America/New_York, close confirmation rather than a wick, session flat, and the recorded risk ceilings. `ManagementParameters` is the only adaptive surface, and it drives the research simulator.

The predictive-intraday paper runner uses this package for the opening-range candidate. It does not replace the constitution with a second copy of the rules. `strategies/orb_momentum.py` is the older wrapper and delegates to this package.

Historical write-up: `docs/lineage/athena-trading/docs/ORB_MOMENTUM_V1.md`.

Tests: `tests/test_orb_m_*.py`, `tests/test_orb_momentum.py`.

Status: research baseline. Not promoted. LIVE is rejected. No overnight position.
