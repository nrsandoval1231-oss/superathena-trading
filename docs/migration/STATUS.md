# Implementation status

Migration of `athena-trading` at `8bd0e7289e0a4899ec7e12291ca02a2c883c583d` is in this checkout. The implementation commit is `87bdb66`. On 2026-10-14 Nick excluded Athena Core: it stays an external, unmigrated dependency, recorded as `excluded-external-dependency`. The Hostinger paper service was not changed.

## What runs

| Check | Result in this environment |
|---|---|
| Source baseline, after NumPy 2 | 871 passed in 13.78s. 0 failed |
| `python -m pytest -q` on this tree | 877 passed in 14.17s. 0 failed |
| `python -m ruff check .` (ruff 0.15.8) | All checks passed |
| `bash -n deploy/install.sh` | Clean |
| `compileall` of the Python trees | Clean |
| `pip install --target` then import paper, earnings, ORB, cloud, legacy v2, authority | Imports succeeded. `LIVE` raised |
| `run_orb_m_paper.py --walk-bars` | Completed on `FixtureBroker`. Not an Alpaca session |
| `run_fixture_self_improve.py --generations 1` | Completed offline. Authority remains ABSENT |

The six tests beyond the 871 are strategy registration, dependency boundaries, and manifest reconciliation. No carried test was removed or rewritten.

These results do not measure trading performance, broker fills, or the health of the running paper host.

## What is not true

- Astra 6 is not operational.
- The hybrid Astra 6 → Jev entry path is not implemented. The paper arms are Jev-only.
- Full APDE ratchets are not on the one-share pilot.
- Portfolio correlation, concentration, and loss thresholds are not active.
- Headline `confirmed` is not a verified issuer release or filing. The decided confirmation policy is recorded and was not implemented as a new gate, because the source has no filing verifier and this migration does not invent one. The existing label still does not authorize a trade by itself.
- Legacy experiments are not promoted.
- This checkout is not deployed. `deploy/athena-paper.service` still describes `/opt/athena-trading` and was not installed.

## Paper trading

The paper runners, journals, shared gate, and Alpaca paper adapter are in the tree and pass the offline suite. Using them against a broker requires an operator, PAPER authority, and secrets that are not in git. Migration did not place orders and did not restart `athena-paper.service`.

SuperAthena is able to run the same paper code paths as the source checkout. It is not the process currently running on the Hostinger VPS, and it should not replace that process until a separate reviewed install says so.
