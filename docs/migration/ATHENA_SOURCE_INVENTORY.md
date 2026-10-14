# Athena strategy migration inventory

Source: https://github.com/nrsandoval1231-oss/athena-trading

- Predictive Intraday: partially implemented product arm.
- Earnings Adaptive: partially implemented event-driven product arm; earnings PR #29 was unmerged in inspected README.
- ORB-M: frozen opening range momentum baseline and reusable component.
- AAT V1/V2: historical research, not production.

Migration safeguards: retain source commit and file provenance; do not copy or reinterpret invalidated holdouts; preserve original research restrictions. No live authority. This inventory is not an executable code migration.

Next: inspect full source tree, dependency graph and test coverage; transfer eligible modules into isolated strategy folders with explicit provenance and verify behavior before merging.
