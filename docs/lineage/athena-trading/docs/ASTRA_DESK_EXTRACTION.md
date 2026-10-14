# Astra Desk standalone extraction receipt

Status: Astra Desk destination [PR #1](https://github.com/nrsandoval1231-oss/astra-desk/pull/1) merged on 7 October 2026.

## Scope and verification

- Source: `research/astra-desk/` at Athena Trading commit `77d5f8918460cac1e7d30c991d305762e618f440`.
- Destination: private `nrsandoval1231-oss/astra-desk`, with 64 tracked source files.
- All 87 unique blobs across the three Astra-affecting source commits matched their SHA-1 Git object identities in the destination.
- All three extracted historical source-directory Git trees matched exactly: `64a9a7d499417a41513c95ab14000cf633fbdfe5`, `6226c8e76ef4d00865682911faed6bbc063c4caa`, `9d1f58537c1677beb2cf15d0d704184e07371733`.
- The source commits were `ac0d2598a8a6f22d426ebf375c79df0f4395c7ee`, `4559538293f95743783d58319f39c8f0458ded19`, and `733a1c441dbed15799397192cf6470b46c370d45`.
- Historical subtree *file states* were reconstructed in chronological commits. Original commit identities, author metadata, and ancestry outside Astra are **not** transplanted; the source repository Git history remains unchanged and retains those originals.
- Standalone GitHub Actions ran tests and Ruff on Python 3.11 and 3.12: each job passed (158 tests, no lint errors). These are automated fixture tests, not broker evidence.

## Isolation policy

The active Athena broker/paper execution path is unrelated to Astra Desk. No imports or dependencies from Astra may remain. The research scaffold's AT-04/AT-05 execution and snapshot integrity defects follow Astra Desk as its own work; they are not resolved by migration. Both projects continue to prohibit unauthorized live-money execution.

Historical audit files under `docs/audits/` and frozen research evidence remain unchanged. Source code can be recovered from the original Athena commit even after this directory is removed from current `main`.
