# Astra 6 + Jev hybrid contract

Status: **TARGET CONTRACT, NOT IMPLEMENTED**. Owner-approved direction, 13 October 2026.
Authority: [Athena Trading Canon v4.0](ATHENA_TRADING_CANON.md). Sequence: [Build plan](BUILD_PLAN.md). Actual capability: [Implementation status](IMPLEMENTATION_STATUS.md).

This subordinate specification defines the role boundary and evidence needed to realize the owner's [diagram](assets/athena-trading-canon.jpg). It adds no runtime or operational authority. **Astra 6 is the owner's selected generative LLM.** Its exact provider deployment/API model ID, account access, SDK/API support and operating limits are unverified. Resolve those explicitly before implementation; do not invent an ID or silently substitute a model. Astra Desk, the fixture lab's “Astra gate,” and historical model providers are unrelated names, not implementations of this selection.

## Responsibility boundary

| Component | Owns | Must not do |
|---|---|---|
| Source and calculation code | Provenance, event/publication/availability times, corrections, freshness, arithmetic, features and validated quantitative forecasts | Turn model prose into an observed fact or calibrated forecast |
| Astra 6 | Interpret linked news/events/guidance and context; propose thesis, scenarios, trade/management plan, horizon, expiry and invalidation | Authorize execution, change risk limits, fabricate evidence, size a final order or claim unsupported profit probabilities |
| Jev | Judge code-defined choices from underlying evidence plus Astra 6 proposal; select a permitted action or INSUFFICIENT_EVIDENCE | Rely only on the narrative, invent missing facts, do authoritative arithmetic or override deterministic policy |
| Deterministic risk and APDE | Shared portfolio accounting, sizing, instrument/session permission, freshness rechecks, stops, legal APDE transitions and exact intent authorization | Treat agreement/confidence as a risk exception or wait for either model to protect exposure |
| Broker/execution | Submit authorized intents, reconcile fills/rejects/partials/cancels/positions/protection and track unresolved exposure | Treat an acknowledgment, model output or simulated fill as broker-confirmed reality |
| Athena boundary and learning | Attribute episodes, replay with temporal firewall, validate lessons and version/promote/retrieve knowledge | Rewrite old evidence or auto-promote a model hypothesis into a rule |

Both Earnings Adaptive and Predictive Intraday use this same design. Strategy-specific inputs and holding policy must not create separate portfolio authorities, model stacks or independent Core implementations.

## Required records and validation

The following are minimum target record requirements, not declarations of already available Python types or API parameters:

- Evidence packet: strategy/account/session and decision time; source URL or immutable record ID/content hash; event, publication and available-at times; correction/version lineage; freshness policy; missing/contradictory fields; computed feature/forecast method and version; reconciled portfolio state and context version.
- Astra 6 proposal: schema version and exact model identity; input and prompt hashes; cited evidence IDs; explicit observed facts versus inferred thesis/scenario assumptions; a supported candidate action; plan horizon, expiry and machine-checkable invalidation conditions; proposed entry/management rationale; unknowns and counterevidence. Quantitative fields must point to validated computation or be rejected as unsupported hypotheses.
- Jev judgment: exact model and question/schema versions; complete underlying evidence plus the proposal; permitted action set; selected choice, distribution/confidence where returned, abstention reason and full receipt identity. INSUFFICIENT_EVIDENCE remains a usable outcome even when Astra 6 sounds confident.
- Deterministic verdict: evidence/plan freshness checked after both model calls, current account/portfolio and risk-policy version, permitted state transition, precise authorized intent or refusal, and expiry. An ADD is new exposure and requires the full gate.
- Episode: every proposal/rejection, source correction, model failure, risk verdict, reservation, execution event, APDE transition and outcome is attributable by identity and time. Preserve raw versus validated outputs and distinguish actual, simulated and counterfactual outcomes.

Source content is untrusted data. It cannot change system instructions, action sets or policy. Test malicious news/guidance text, fabricated citations and source contradictions; asking a model to ignore instructions is not a security guarantee.

Neither Astra 6 confidence nor Jev answer confidence is a measured probability of profit. A Jev choice distribution measures its answer assessment, not the distribution of market returns. Agreement is not independent verification: shared evidence, anchoring and correlated errors remain possible. Quantitative forecasts require a defined outcome/horizon, point-in-time training/evaluation identity, calibration, sample support and uncertainty. Fractional Kelly remains disabled unless validated probabilities/payoffs and explicit risk policy support it.

## Bounded update and failure behavior

Recompute proposals/judgments on material arrived evidence, meaningful market/regime changes, expiry/invalidation or permitted APDE events. Deduplicate source/episode versions and set explicit call, token, cost, latency, timeout and retry budgets per episode/session before activation. No new numeric budgets are authorized here. Do not call both models on every tick or loop until they agree.

| Condition | Required target behavior |
|---|---|
| Fresh validated proposal + acceptable Jev judgment | Recheck freshness, risk and state; only code may authorize exact new exposure |
| Jev veto, disagreement or insufficient evidence | No new exposure; retain reason and contrary evidence |
| Either model unavailable, late, stale, malformed or wrong identity | No entry/ADD, no silent substitute or expired-plan reuse; record failure and keep protective management alive |
| Source correction or thesis expiry/invalidation | Invalidate dependent proposal; prevent new exposure; apply deterministic risk/exit policy while bounded reassessment runs |
| Missing stop, daily-loss/kill switch, emergency or mandated session close | Execute deterministic protection/exit immediately without awaiting Astra 6 or Jev; reconcile broker-confirmed outcome |
| Broker unavailable/rejects cleanup | Preserve unresolved exposure, halt new entries and surface operator action; never claim flatness from an attempted close |

The existing Jev-only daily cutoff fallback is current pilot behavior, not a reusable hybrid loophole. Its future handling needs explicit reviewed policy and tests; it cannot bypass an absent/expired Astra 6 plan, insufficient evidence or a Jev veto. Existing runtime is unchanged by this contract.

## Diagram alignment and acceptance evidence

“Target” below means still to be delivered/verified as a complete capability. Existing fragments and fixtures do not satisfy an entire row. No requirement is removed because a data source, forecast or instrument is currently unsupported.

| Diagram block | Deliverable and acceptance evidence | Present boundary |
|---|---|---|
| Earnings intelligence | Point-in-time calendar/estimates, guidance/sentiment, options skew/IV, historical reactions and catalyst/risk map; receipts demonstrate original availability, corrections and missing-data behavior | Screener is research; PR #29 is pending narrow calendar/gap paper integration; full source set is target |
| Earnings thesis/scenario engine | Evidence-linked beat/meet/miss hypotheses and trade plan; validated reaction distribution, expected move/range and edge/calibration where supported; expire/invalidate on new facts | Astra 6 and full scenario engine are target |
| Earnings execution/positioning | Supported pre/post/intraday windows, sizing, instrument structure and shared correlation checks; tests for each enabled window/instrument and broker-confirmed paper lifecycle | PR #29 is unmerged post-event equities proposal; options/multi-leg and Kelly remain gated |
| Intraday market intelligence | Multi-timeframe technicals/order flow/VWAP, volume/volatility, news/social/macro and sector/correlation inputs with trustworthy provenance and explicit unknowns | Existing ORB features/data and research utilities are partial assets |
| Intraday prediction engine | Defined-horizon target probability, MFE/MAE/duration/path, invalidation, uncertainty and event-driven updates; fresh prospective calibration and baseline evidence | Full validated predictive engine is target; +1% in the image is an example |
| Intraday execution/positioning | Supported signal confluence, code-owned size/stops/instrument choice and exact authorized intent; reject stale/unsupported proposals | Narrow ORB/Jev paper path exists; full hybrid is target |
| APDE in both arms | EXPLORE → PROTECT → HARVEST → DEFEND → EXIT with reasoned, versioned plan changes and code-enforced transitions; replay/paper tests for winners, deterioration, partial exits, failures and restart | Broker protection exists; full shared adaptive ratchet/hybrid management is target |
| Exit and review in both arms | Planned/adaptive and mandatory exits, broker-confirmed reconciliation, P&L attribution and complete Decision Episode | Current intraday cleanup/learning is partial; complete shared hybrid attribution is target |
| Decision Actor / world state / context | Astra 6 proposals from frozen-time facts, validated experience, positions and bounded actions, with provenance, expiry and unknowns | Current main has bounded ORB packet and Jev only; general validated Core context is incomplete |
| LLM reasoning and decision | Separate facts, hypotheses and computed forecasts; Jev checks original evidence plus proposal; malformed/contradictory/expired outputs and anchoring tests | Both-model integration and quality evaluation are target |
| Risk and guardrails layer | Shared portfolio, daily/weekly/monthly/drawdown, stop/size/leverage/correlation, kill switches, circuit breakers, compliance/instrument/session and pre-close checks; atomic cross-arm race tests | Narrow pilot limits exist; comprehensive shared risk is target; owner confirmed no overnight positions |
| Execution engine | Authorized routing, slippage/quality controls, fill confirmation, partial/reject/lost-ack/idempotent recovery tests | Existing paper adapter/runtime supplies reusable components; model-free safety must be preserved |
| Reality and outcome | Observed P&L, MFE/MAE, fill quality/slippage, prediction accuracy, duration and labeled opportunity cost with coverage/measurement limits | Gross paper outcomes and sampled excursions are partial; fees/complete path and full metrics remain incomplete |
| Core replay engine | Frozen identities, temporal firewall and labeled counterfactual simulation; no future leakage or consumed-holdout reuse | General Core integration and full replay are target |
| Wisdom extraction | Outcome attribution, pattern discovery, candidate lessons and retained negative knowledge; trace every hypothesis to episodes | Narrow paper abstention study exists; richer shared extraction is target |
| Validation lab | Predeclared walk-forward/out-of-sample/statistical checks, meaningful controls, fresh evidence, rejection and sample-insufficiency outcomes | Existing narrow prospective veto protocol is not full validation or profit proof |
| Knowledge store | Versioned validated rules/models, promotion/rollback, lineage and demonstrated later retrieval through Core boundary | Trading-specific experience store exists; full Core knowledge loop is target |
| Continuous wisdom loop / performance principles / unified outcomes | End-to-end observe → propose → authorize/execute → APDE → exit → replay → extract → validate/promote → later retrieval, with measured risk/decision/performance reports | Objectives require evidence; each trade supplies information but cannot guarantee improvement or sustainable growth |

## Holding-policy and integration gate

The diagram's guardrails say pre-close flat. Current intraday policy starts flattening 15 minutes before the broker close and does not permit overnight exposure. Nick explicitly confirmed no overnight positions on 13 October 2026. PR #29 now uses DAY earnings brackets and the same 15-minute pre-close buffer, based on the actual broker calendar including early closes. Its earlier multi-day proposal is superseded. Old journals and GTC orders remain recovery inputs, not permission to renew a hold. That book is **open/unmerged**. An outage or market halt may prevent execution; unresolved exposure must block new entries, remain visible and be reconciled before claiming flatness.

PR #29's branch-only `docs/EARNINGS_PAPER.md` and overlapping current guides must be reconciled to this contract when integrating/rebasing. Do not import a branch runbook into main as though its runtime exists. Do not assume prior runtime audit findings are still present or resolved without reviewing the new head. Neither merge, deployment, credentials nor provider/broker calls are part of this documentation change.
