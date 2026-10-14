# Verification

From the repository root, Python 3.12:

```bash
python -m pip install pytest ruff==0.15.8 .
python -m ruff check .
python -m pytest -q
bash -n deploy/install.sh
python -m compileall -q src strategies core data evaluation operations tests scripts
```

`pytest` uses `pythonpath = ["src"]`. The carried suite plus registration and manifest checks is the gate. Do not treat a fixture walk as a broker fill or as a performance result.

Offline demonstrations, neither of which submits a broker order:

```bash
PYTHONPATH=src python scripts/run_orb_m_paper.py --walk-bars
PYTHONPATH=src python scripts/run_fixture_self_improve.py --out /tmp/fixture-self-improve --generations 1
```

`--walk-bars` uses `FixtureBroker` and the tracked bar fixture. The self-improve command is the offline mutator. Its authority stays ABSENT. Its synthetic holdout is not the consumed AAT holdout file.

Paper commands that can talk to Alpaca (`scripts/run_athena_paper.py`, `scripts/run_athena_earnings.py`) are operator tools. This migration does not run them and does not enable the systemd units.

## Source baseline

Trading anchor `8bd0e7289e0a4899ec7e12291ca02a2c883c583d`, Python 3.12.3, pytest 9.1.1.

The first collection in this environment failed in `tests/test_build_pool_script.py` because the ambient NumPy was 1.26.4 and PyArrow required NumPy 2. That was an environment mismatch. After `numpy>=2`:

```text
python -m pytest -q --tb=line -p no:cacheprovider
871 passed in 13.78s
```

No source test failed. The migrated tree was then compared by running the same suite here. Results are in [STATUS.md](STATUS.md).
