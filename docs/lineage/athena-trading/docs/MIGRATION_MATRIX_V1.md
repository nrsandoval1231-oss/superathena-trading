# Migration Matrix V1

| Source family in historical Athena | Canonical owner now | Disposition |
|---|---|---|
| Arena / policy genomes / lineage | Athena Core | KEEP |
| Gauntlet / validation / authority | Athena Core | KEEP |
| generic evidence / DecisionEpisode semantics | Athena Core | KEEP / generalize |
| `src/athena_lab/massive*` | Athena Trading | MIGRATED ownership; historical compatibility copy retained |
| Alpaca market/reference adapters | Athena Trading | MIGRATED ownership |
| ORB scanners/candidates | Athena Trading | MIGRATED ownership/spec |
| APDE trading state/config | Athena Trading | MIGRATED |
| paper broker/risk | Athena Trading | MIGRATED ownership/config |
| fills/slippage/timing trading diagnostics | Athena Trading | MIGRATED ownership; historical experiment copies retained |
| NVDA/equity observed replay results | Historical research | PRESERVE, do not treat as Athena identity |
| Athena vision/math/adaptation canon | Athena Core | KEEP |

No new trading implementation belongs in `Athena/src/athena_lab`. That path is now historical compatibility/reproducibility territory.
