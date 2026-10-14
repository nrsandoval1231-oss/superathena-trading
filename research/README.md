# Research and history
Product authority: [Athena Trading Canon](../docs/ATHENA_TRADING_CANON.md).
Active work: [Build plan](../docs/BUILD_PLAN.md).

Research supports the two canonical strategy arms. These projects and experiments do not define separate product roadmaps. The owner-approved direction as of 13 October 2026 is **Astra 6 generative LLM + Jev bounded judge + deterministic enforcement**; see the [hybrid contract](../docs/HYBRID_MODEL_CONTRACT.md) and [full documentation inventory](../docs/README.md). Historical providers and Jev-only architecture statements do not override it.

Astra 6 is a selected model name with deployment/API identity and access still unverified. Astra Desk is a separate historical project, and the fixture lab's Astra-style gate is a toy deterministic judge; neither implements Astra 6.

| Material | Keep it for | Current role |
|---|---|---|
| [Astra Desk](https://github.com/nrsandoval1231-oss/astra-desk) | Fixture/paper lifecycle, agent/risk/reporting experiments | Independent private research repository; audited execution/persistence defects remain |
| [Earnings universe](earnings-universe/README.md) | Historical event screening concepts | Candidate input to Earnings Adaptive; PR #29's narrower paper integration is pending/unmerged, not proof of a full thesis/scenario arm |
| [ORB-M status](../docs/ORB_M_STATUS.md) | Intraday signals, management, simulator/baseline | Reusable component; historical campaign semantics remain pinned |
| [AAT-V1](../docs/AAT_V1_TRAINING_RUNNER.md) | Prior controlled experiment, outcomes and negative knowledge | Closed experiment; consumed invalid holdout |
| [AAT-V2](../docs/AAT_V2_HANDOFF.md) | Exogenous/context, candidate model and comparison infrastructure | Research reference; not the canonical dual-strategy runtime |
| [Former README](history/README_before_canon_reset_2026-09-24.md) | Pre-reset roadmap and command history | Superseded product entry point |
| [Former written canon](history/CANON_before_reset_2026-09-24.md) | Earlier ownership/strategy framing | Superseded by the restored owner diagram |

Remaining in-repository code, configs, registered identities, and source-document paths stay in place to preserve reproducibility and imports. Astra Desk's source snapshots remain in Git history and are independently reconstructed in its destination repository. Historical documents and frozen evidence remain unchanged. The documentation index labels their scope and supersession; in particular ORB-M status's October install paragraph is a dated snapshot, superseded for current operations by IMPLEMENTATION_STATUS.md. Product planning begins with the canon, implementation status, and build plan.

The product has **two strategy arms**. AAT's A/B/C/D/E experimental treatments are a different concept and do not expand that product architecture.
