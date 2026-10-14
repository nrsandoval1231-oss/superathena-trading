# Earnings Adaptive

Paper book for a post-earnings gap that lands in the screener's 4–12% band, in the gap's direction, on a name from the operator universe. `earnings/earnings.py` is the book. `earnings/earnings_calendar.py` reads the Nasdaq calendar. `earnings/earnings_cloud.py` is the supervisor.

New brackets are DAY orders. Exits start before the regular close, including early closes. Legacy multi-day journals can be recovered and cannot authorize a new overnight hold. Client order ids use `athe-`.

`news_for_decision` can label a headline `confirmed` when the text looks like a report. That label is not a verified issuer release or filing, and it does not authorize the order. Jev and the deterministic caps still have to accept the trade. A filing verifier is not in this source and was not added.

The historical import path is `athena_trading.paper.earnings`.

Tests: `tests/test_earnings_paper.py`, `tests/test_earnings_close_recovery.py`, `tests/test_shared_entry_atomicity.py`.

Research input, not an order path: `research/earnings-universe/`.

Status: paper. Not promoted. LIVE is rejected. No overnight position.
