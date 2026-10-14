# Source-to-destination manifest

Machine-readable records: [source-manifest.json](source-manifest.json).

Trading source: `nrsandoval1231-oss/athena-trading` @ `8bd0e7289e0a4899ec7e12291ca02a2c883c583d`.

That commit was the remote `main` head when this migration read it. The source repository was not modified.

## Reconciliation

| Disposition | Files | Meaning |
|---|---:|---|
| `migrated` | 217 | Working copy is byte-identical to the source blob |
| `migrated-import-adjusted` | 9 | Only import paths and config lookup changed |
| `preserved-lineage` | 39 | Byte-identical historical copy under `docs/lineage/athena-trading/` |
| Total source files | 265 | Every path from `git ls-files` at the anchor |

Nothing tracked in the trading source was dropped. Configs, tests, scripts, research, deploy units, and `data/universe` moved with their bytes. The universe files are the campaign's dataset identity, not a regenerated market dump. Parquet pulls were never in git and were not created here.

Nine import-adjusted modules:

- Earnings book and earnings supervisor
- Intraday runner and intraday supervisor
- Shared account gate, now in `core/portfolio`
- Paper bar fixture path
- Three legacy identity modules whose config paths no longer assume `src/athena_trading/<package>/<file>.py`

`tests/test_migration_manifest.py` recomputes every destination SHA-256 and checks the 265 source paths. Consumed-holdout bytes are part of that check.

Compatibility modules under `operations/paper-trading/paper/` (`live.py`, `earnings.py`, `journal.py`, and the other aliases) are new files. They rebind `sys.modules` to the implementation module. They contain no order logic.

## Athena Core

`nrsandoval1231-oss/Athena` @ `adba694563751256f5f5e95ad47079b37c7697ec` could not be listed. Disposition: `external-dependency-unavailable`. Details: [ATHENA_CORE_BLOCKER.md](ATHENA_CORE_BLOCKER.md).

The trading adapter that already lived in `athena-trading` (`athena_adapter`, including the local `canonical_hash`) is migrated. Domain-neutral Core was not invented and was not copied.

## Recompute a source hash

```bash
git clone https://github.com/nrsandoval1231-oss/athena-trading.git
git -C athena-trading checkout 8bd0e7289e0a4899ec7e12291ca02a2c883c583d
sha256sum <source-path>
```

Compare that digest to `source_sha256` in `source-manifest.json`.
