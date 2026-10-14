# Documentation index

Inventory reviewed against main `8e9062a182c25c3745e8fd03326a66235fde04ed` and this earnings branch's lifecycle repair `5baae398e05c5a31b956280a002641694a4a4052`, on 13 October 2026. PR #29 remains open and unmerged.

Start with [canon v4.0](ATHENA_TRADING_CANON.md), [current implementation](IMPLEMENTATION_STATUS.md), [build plan](BUILD_PLAN.md), then the [hybrid contract and image acceptance map](HYBRID_MODEL_CONTRACT.md). **Astra 6 + Jev + deterministic enforcement is the owner-approved target.** Current main remains Jev-only. Model deployment identity/access and full hybrid implementation remain unresolved. Nick confirmed no overnight holdings on 13 October 2026; both arms must pursue same-session, broker-confirmed exits.

## Historical boundary

Current guides are updated for the new direction. Dated audits, frozen AAT/ORB documents, data-source studies, source/migration receipts and former entry points retain their original content and evidence. Their old “next step,” provider choice, Jev-only, deployment or no-fill statements do not override current product requirements/status. This is deliberate preservation, not an instruction to execute an old experiment. Model names in those files must not be globally replaced with Astra 6.

In particular, ORB_M_STATUS.md includes an October 10 install/waiting paragraph within a research record; IMPLEMENTATION_STATUS.md's October 13 filled-bracket account supersedes it as operational history. September audit/learning claims and old verification counts stay tied to their named commits. Frozen/consumed holdouts, manifests, model identities and receipts are not reopened by this change. Astra Desk and the fixture lab's Astra-style gate are distinct from the owner-selected Astra 6 LLM.

## Full Markdown inventory

| File | Treatment | Scope |
|---|---|---|
| [AGENTS.md](../AGENTS.md) | Current guide | Builder instructions and model/authority boundaries |
| [README.md](../README.md) | Current guide | Product entry point and present-versus-target overview |
| [docs/AAT_V1_TRAINING_RUNNER.md](AAT_V1_TRAINING_RUNNER.md) | Unchanged research/component record | Frozen experiment/baseline/provider choices; not current hybrid architecture or activation |
| [docs/AAT_V2_HANDOFF.md](AAT_V2_HANDOFF.md) | Unchanged research/component record | Frozen experiment/baseline/provider choices; not current hybrid architecture or activation |
| [docs/AAT_V2_MODEL_EXECUTION_OPTIONS.md](AAT_V2_MODEL_EXECUTION_OPTIONS.md) | Unchanged research/component record | Frozen experiment/baseline/provider choices; not current hybrid architecture or activation |
| [docs/AAT_V2_PLAN.md](AAT_V2_PLAN.md) | Unchanged research/component record | Frozen experiment/baseline/provider choices; not current hybrid architecture or activation |
| [docs/AAT_V2_VISION.md](AAT_V2_VISION.md) | Unchanged research/component record | Frozen experiment/baseline/provider choices; not current hybrid architecture or activation |
| [docs/ALFRED_MACRO_SOURCE_PROVENANCE.md](ALFRED_MACRO_SOURCE_PROVENANCE.md) | Unchanged source/research specification | Retained provenance and component limits; reuse needs current integration/acceptance |
| [docs/ARCHITECTURE.md](ARCHITECTURE.md) | Current guide | Short architecture navigation |
| [docs/ASTRA_DESK_EXTRACTION.md](ASTRA_DESK_EXTRACTION.md) | Unchanged provenance/receipt | Historical ownership and migration evidence |
| [docs/ATHENA_TRADING_CANON.md](ATHENA_TRADING_CANON.md) | Current guide | Authoritative product requirements, v4.0 |
| [docs/BUILD_PLAN.md](BUILD_PLAN.md) | Current guide | Single active implementation sequence |
| [docs/CLOUD_DEPLOYMENT.md](CLOUD_DEPLOYMENT.md) | Current guide | Existing cloud operator runbook; separate hybrid gate |
| [docs/EXOGENOUS_SOURCES_V1.md](EXOGENOUS_SOURCES_V1.md) | Unchanged source/research specification | Retained provenance and component limits; reuse needs current integration/acceptance |
| [docs/FIXTURE_SELF_IMPROVE.md](FIXTURE_SELF_IMPROVE.md) | Current guide | Current offline toy guide; names do not imply model integration |
| [docs/GDELT_NEWS_SOURCE_PROVENANCE.md](GDELT_NEWS_SOURCE_PROVENANCE.md) | Unchanged source/research specification | Retained provenance and component limits; reuse needs current integration/acceptance |
| [docs/HISTORICAL_SOURCE_PROVENANCE.md](HISTORICAL_SOURCE_PROVENANCE.md) | Unchanged source/research specification | Retained provenance and component limits; reuse needs current integration/acceptance |
| [docs/HYBRID_MODEL_CONTRACT.md](HYBRID_MODEL_CONTRACT.md) | Current guide | Subordinate role/record/failure contract and image acceptance map |
| [docs/IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) | Current guide | Current snapshot plus retained dated runtime evidence |
| [docs/LEARNING.md](LEARNING.md) | Current guide | Existing paper study and target hybrid/Core requirements |
| [docs/LIVE_PAPER.md](LIVE_PAPER.md) | Current guide | Existing Jev-only operator runbook; separate hybrid gate |
| [docs/MIGRATION_COMPLETE.md](MIGRATION_COMPLETE.md) | Unchanged provenance/receipt | Historical ownership and migration evidence |
| [docs/MIGRATION_FROM_ATHENA.md](MIGRATION_FROM_ATHENA.md) | Unchanged provenance/receipt | Historical ownership and migration evidence |
| [docs/MIGRATION_MATRIX_V1.md](MIGRATION_MATRIX_V1.md) | Unchanged provenance/receipt | Historical ownership and migration evidence |
| [docs/ORB_MOMENTUM_V1.md](ORB_MOMENTUM_V1.md) | Unchanged research/component record | Frozen experiment/baseline/provider choices; not current hybrid architecture or activation |
| [docs/ORB_MOMENTUM_V1_CAMPAIGN.md](ORB_MOMENTUM_V1_CAMPAIGN.md) | Unchanged research/component record | Frozen experiment/baseline/provider choices; not current hybrid architecture or activation |
| [docs/ORB_M_STATUS.md](ORB_M_STATUS.md) | Unchanged research/component record | Frozen experiment/baseline/provider choices; not current hybrid architecture or activation |
| [docs/README.md](README.md) | Current guide | This full inventory and historical supersession boundary |
| [docs/audits/2026-09-24-jev-learning.md](audits/2026-09-24-jev-learning.md) | Unchanged dated audit | Findings apply to named revision/date; no claim of current runtime status |
| [docs/audits/2026-09-24.md](audits/2026-09-24.md) | Unchanged dated audit | Findings apply to named revision/date; no claim of current runtime status |
| [docs/audits/2026-10-10-paper-readiness.md](audits/2026-10-10-paper-readiness.md) | Unchanged dated audit | Findings apply to named revision/date; no claim of current runtime status |
| [docs/legacy/ATHENA_ALPACA_PAPER_ADAPTER_V1.md](legacy/ATHENA_ALPACA_PAPER_ADAPTER_V1.md) | Unchanged legacy reference | Prior component contract; current canon and runbooks govern |
| [docs/legacy/ATHENA_APDE_V1.md](legacy/ATHENA_APDE_V1.md) | Unchanged legacy reference | Prior component contract; current canon and runbooks govern |
| [research/README.md](../research/README.md) | Current guide | Research navigation; no product authority |
| [research/earnings-universe/CONSOLIDATION_RECEIPT.md](../research/earnings-universe/CONSOLIDATION_RECEIPT.md) | Unchanged provenance/receipt | Historical ownership and migration evidence |
| [research/earnings-universe/README.md](../research/earnings-universe/README.md) | Unchanged source/research specification | Retained provenance and component limits; reuse needs current integration/acceptance |
| [research/history/CANON_before_reset_2026-09-24.md](../research/history/CANON_before_reset_2026-09-24.md) | Unchanged superseded snapshot | Historical product framing; canon v4.0 supersedes planning instructions |
| [research/history/README_before_canon_reset_2026-09-24.md](../research/history/README_before_canon_reset_2026-09-24.md) | Unchanged superseded snapshot | Historical product framing; canon v4.0 supersedes planning instructions |

The original [architecture image](assets/athena-trading-canon.jpg) is preserved unchanged. Its aspirational performance language is an objective to evaluate, not evidence or a guarantee.

## Pending branch documentation

PR #29's branch-only `docs/EARNINGS_PAPER.md` is not present on main and is intentionally not copied here as a working launch guide. On integration/rebase, reconcile it and all overlapping current guides to canon v4.0, verify the runtime head separately, and preserve the owner's confirmed no-overnight policy. This branch does not merge or deploy either service.
