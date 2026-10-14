# Predictive Intraday

Paper runner for one opening-range candidate per session. `intraday/live.py` builds the candidate from ORB-M, asks Jev, and submits only after deterministic checks. `intraday/cloud.py` is the supervisor.

The historical module path `athena_trading.paper.live` is this implementation. Client order ids use the `athp-` prefix. The runner flattens its own symbol and ignores earnings orders prefixed `athe-`.

Astra 6 is not called. Jev is `jev-1.13.0`. A model failure does not approve a trade. The one-share pilot and its caps are unchanged. PROTECT, HARVEST, and DEFEND ratchets are not on this order path.

Tests: `tests/test_active_paper.py`, `tests/test_cloud_paper.py`, `tests/test_paper_learning.py`, `tests/test_shared_risk_and_evaluation.py`.

Status: paper pilot. Not promoted. No overnight position. Not the Hostinger process. That process still runs the source checkout.
