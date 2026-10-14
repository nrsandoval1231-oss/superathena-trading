# Working in Athena Trading

Nick's explicit instructions govern the task. The owner-supplied dual-strategy diagram and docs/ATHENA_TRADING_CANON.md define product direction.

Read, in order:
1. docs/ATHENA_TRADING_CANON.md
2. docs/IMPLEMENTATION_STATUS.md
3. docs/BUILD_PLAN.md

## Architecture rules

- Build Earnings Adaptive and Athena Predictive Intraday on one shared decision/context/risk/execution/APDE/outcome workflow.
- The owner-approved target is Astra 6 as the generative LLM, TypeSafe Jev as the bounded judge, and deterministic code as final authority. Astra 6 interprets source-linked evidence and proposes structured theses/plans; Jev receives the underlying evidence plus proposal, and can abstain. Code owns calculations, validated forecasts, freshness, sizing, shared portfolio risk, execution and APDE transition enforcement. Critical protection and exits must not wait for either model. See docs/HYBRID_MODEL_CONTRACT.md.
- Astra 6 is the owner-selected model name; its provider deployment/API model ID, access and SDK support are unverified. Resolve those explicitly before implementation. Never guess an identifier or silently substitute another model. The main runtime is still Jev-only; the hybrid is not implemented by a documentation change.
- ORB-M is an intraday component and baseline. AAT-V1/V2 and Astra Desk are research references, not competing product architectures.
- Athena Core remains domain-neutral. Reuse its contracts through athena_adapter; do not create a second Core or generic orchestration framework here.
- Preserve the canonical APDE states: EXPLORE, PROTECT, HARVEST, DEFEND, EXIT.
- The diagram is target architecture, not evidence of implemented capability or trading performance.

## Scope and simplification

- Work on the earliest incomplete slice in BUILD_PLAN.md relevant to the owner's task.
- Extend existing modules when practical. Add a strategy package or shared contract only when it contains real behavior for the current slice.
- Do not add empty directories, parallel runtime stacks, new provider matrices, or another governing roadmap.
- Research files carry experiment-specific restrictions. Old provider/runbook next steps do not override the product build sequence.
- Do not rename or move frozen research code, manifests, datasets, identities, receipts, or referenced paths solely to make the tree cleaner. Any later retirement requires a dependency/reference check and preserved provenance.
- Preserve consumed-holdout status and frozen hashes. Canon restoration does not authorize changing historical evidence.
- Current execution authority remains PAPER/ABSENT. Existing spend and external-action boundaries still apply.
- Nick explicitly requested active live-data paper trading, with no mandatory shadow stage. Follow the bounded pilot policy and LIVE_PAPER.md. This is permission for paper operation, not real-money LIVE authority or a frozen research rerun.

- Nick selected cloud operation independent of his PC. Extend the existing paper runner through CLOUD_DEPLOYMENT.md toward the Astra 6 + Jev target; keep the current Jev-only operational instructions distinct from future integration. Do not restore historical Terra/Ollama paths or create a second runtime. Keep persistent journals and recover unfinished exposure before daily rollover.
- Aggressive operation means capturing valid opportunities and adapting winner management inside existing risk limits. It does not authorize larger caps, looser stops, more leverage, overnight exposure, or LIVE. Nick explicitly confirmed no overnight positions on 13 October 2026. Both arms must cancel pending entries and start flattening owned exposure before the broker's regular-session close, including early closes. Old multi-day journals remain recovery inputs, never renewed holding permission. Unresolved exposure blocks new entries and stays visible until broker-confirmed flat.
- Source facts, deterministic values, validated forecast outputs and model hypotheses must remain distinct. Stale, malformed or unavailable model results cannot authorize new exposure. Model agreement is not independent proof; neither model's confidence is a probability of profit.

- Every reconciled paper trade enters the trading experience store. Nightly review runs after 20:15 America/New_York. Follow docs/LEARNING.md: facts become available intraday; risk-reducing rules require prospective validation. Never promise improvement from every trade or reuse frozen research outcomes as fresh paper evidence.

## Verification and handoff

- Keep fixtures/simulation separate from actual provider or broker evidence.
- Test changed behavior with meaningful cases and run the relevant existing suite.
- Root pytest covers this repository's tests only. Astra Desk was extracted to its own repository; do not imply this gate runs its independent suite. Follow IMPLEMENTATION_STATUS.md for dated evidence.
- Report existing gate failures separately from regressions. Do not relabel a partial test pass as a clean repository.
- Update IMPLEMENTATION_STATUS.md with the tested commit, commands, observed results, and remaining limitations.
- Use one clear PR explaining the problem, resulting behavior, verification, and material limits.
