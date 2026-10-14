# Legacy Strategy Research

Historical experiments from Athena Trading. The directory name is the product name. The Python packages stay `aat_v1` and `aat_v2` so frozen identities, configs, and tests keep their names.

| Package | What it is | What it is not |
|---|---|---|
| `aat_v1` | Training plans, lessons, claim contract, holdout gate | A production strategy. The consumed holdout is `INVALID_EVIDENCE` |
| `aat_v2` | Exogenous packets, arm definitions, actor identities | The canonical dual-strategy runtime. Execution authority stays absent |

Do not reuse consumed holdouts. Do not edit `configs/aat_consumed_holdouts_v1.json` or the sealed claim artifacts. Do not import these packages from the paper arms.

Tests: `tests/test_aat_v1_*.py`, `tests/test_aat_v2_*.py`.

Status: historical. Not promoted.
