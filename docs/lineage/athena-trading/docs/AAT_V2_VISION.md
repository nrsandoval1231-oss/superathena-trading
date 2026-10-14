> **RESEARCH REFERENCE — product direction restored 24 September 2026.** This document retains its experiment/component history and restrictions. Its product-level next-step instructions are superseded by [Athena Trading Canon](ATHENA_TRADING_CANON.md) and [Build Plan](BUILD_PLAN.md). Read [Implementation Status](IMPLEMENTATION_STATUS.md) for current capability.

# AAT-V2 Vision — exogenous evidence, portable Actors, testable deliberation

Status: VISION. Nothing in this document is registered evidence, and nothing
here modifies AAT-V1. AAT-V1 is frozen, its sealed holdout is consumed, and its
claim contract is closed. V2 is a **new** experiment with a new dataset
assignment and a new, separately authorized holdout.

## Why this exists

The AAT-V1 four-arm comparison was audit-passing but structurally incapable of
producing a strong positive result. Every arm — deterministic, memoryless,
naive-memory, Athena — reasoned over the *same* price-derived feature vector.
Arm D received one promoted lesson and nothing else. There was no information
in arm D's packet that arm A did not already have, so the largest honest effect
available was a re-weighting of sizing under identical evidence.

That is a ceiling on the experiment, not on Athena.

TradingAgents (TauricResearch) sits at the opposite extreme: a wide exogenous
data surface (news, social sentiment, fundamentals, macro) consumed by an
LLM-only agent graph with no deterministic control arm, no partition
discipline, and an explicit disclaimer that its results do not reproduce. It
has the inputs we lack and none of the governance we have.

V2 takes their inputs and keeps our governance.

## Problem statement

Athena's research question is unchanged: **can validated adaptation improve
decision quality over a frozen deterministic baseline without violating hard
risk authority?**

V1 could not answer it because the adaptive arm had no informational advantage.
V2 gives the adaptive arms information the deterministic baseline structurally
cannot use — while keeping the baseline, the partitions, the receipts, and the
refusal-to-claim machinery exactly as they are.

## Outcomes

1. An ablation in which a positive result for arm D has a *mechanism*: the
   adaptive arm saw exogenous evidence, the deterministic arm did not.
2. An exogenous evidence layer whose point-in-time correctness is enforced in
   code and provable from a receipt, not asserted in prose.
3. Actor identity that survives a provider or model change as a declared,
   hashed axis rather than a permanent limitation.
4. No weakening of any V1 boundary: partition separation, single-use holdout,
   `execution_authority: ABSENT`, and the negative-knowledge registry all carry
   forward unchanged.

## Scope

### In scope
- A provider-neutral exogenous record contract with hard point-in-time and
  revision-leakage enforcement.
- Deterministic "analyst" compressors that reduce raw exogenous records to a
  bounded, frozen-key, bucketed feature vector.
- An exogenous snapshot projection with its own receipt, hashed and joined to
  opportunity ids.
- A provider registry that makes Actor identity portable across vendors while
  keeping V1 identity hashes byte-identical.
- A non-consuming sufficiency probe that runs *before* holdout authorization.

### Out of scope (deliberately)
- Any change to `orb_m/constitution.py`. The baseline stays frozen.
- Any change to AAT-V1 modules, hashes, protocols, or receipts.
- Live or automated execution of any kind. `execution_authority` remains
  `ABSENT` at every layer.
- Adopting TradingAgents' agent graph as a decision architecture (see below).

## Principles

**Analysts compress; they do not decide.** TradingAgents' analyst roles are
useful as a *decomposition of the input space* and worthless as a decision
architecture — an LLM debate with no control arm cannot be evaluated. We keep
the decomposition and throw away the authority. Each analyst is a deterministic
function from visible records to a fixed set of bucketed features. It calls no
model, and its output is reproducible from the snapshot hash alone.

**Exogenous data is leakage until proven otherwise.** News, sentiment, and
fundamentals are the easiest way to destroy a backtest. Every record carries an
explicit `available_at`; visibility is `available_at <= decision_time` and
nothing else. Revisions are rejected in favor of first publication. A snapshot
that cannot prove its own as-of discipline does not compile.

**Features are bucketed, not precise.** Continuous exogenous values are
quantized before they reach an Actor. Precision that the strategy cannot act on
is precision the Actor can overfit to.

**Asymmetry is the experiment.** Arm A cannot consume exogenous features by
construction — it is the frozen deterministic strategy. Arms B/C/D receive
them identically. That asymmetry is the treatment; memory quality remains the
B/C/D contrast.

**One frozen thing at a time.** V1's discipline holds: freeze the contract
before the data, register before the run, and let an insufficient result end as
`INVALID_EVIDENCE` rather than a lowered bar.

## Capabilities

| Capability | Borrowed from | Change from V1 |
| --- | --- | --- |
| Exogenous record contract + as-of enforcement | their data breadth | new |
| Six-category source surface (news, macro, social, fundamentals, prediction markets) | their data breadth | new; see `docs/EXOGENOUS_SOURCES_V1.md` |
| Deterministic analyst compressors | their analyst-team split | new, authority removed |
| Bucketed exogenous feature vector in the Actor packet | — | new, arms B/C/D only |
| Provider registry for Actor identity | their multi-provider support | replaces hardcoded OpenAI transport |
| Non-consuming holdout sufficiency probe | — | new; fixes the 249/300 burn |
| Bull/bear deliberation as arm E | their debate loop | deferred to Phase 3 |

## Architecture direction

```text
raw exogenous records ──► visibility filter (available_at <= T, no revisions)
                                  │
                                  ▼
                    deterministic analyst compressors
                    (news / sentiment / fundamentals / macro)
                                  │
                                  ▼
                     bucketed exogenous feature vector
                                  │
        ┌─────────────────────────┼─────────────────────────┐
        │                         │                         │
   arm A (never)            arms B/C/D                  snapshot receipt
   frozen ORB-M          Actor packet + memory         (hash, as-of proof)
```

The exogenous layer is a sibling of `market_data/`, not a dependency of
`orb_m/`. The deterministic strategy must remain runnable with the exogenous
package deleted.

## Phases

Four phases, each gated on the previous one producing something auditable.
The work breakdown, file-by-file sequencing and test strategy live in
`docs/AAT_V2_PLAN.md`; this section is the shape only.

**Phase 1 — exogenous evidence layer.** Record contract, visibility and
revision enforcement, deterministic analyst compressors, hashed snapshot
projection with receipt. No Actor, no model call, no spend.

**Phase 2 — portable Actor identity.** Provider registry;
`PROVIDER_MODEL_MUTABILITY` becomes a declared, hashed axis instead of a
permanent limitation. V1 identity hashes preserved byte-for-byte.

**Phase 3 — V2 protocol and arm E.** New dataset assignment, new claim
contract, exogenous features in the B/C/D packets, and an optional fifth arm
running a bounded bull/bear deliberation to test whether TradingAgents'
signature mechanism beats a single Actor call at equal token budget.

**Phase 4 — V2 sealed holdout.** New authorization, new single-use dataset.
Gated on Phase 3 producing an audit-passing TRAINING result *and* the
sufficiency probe clearing before authorization is issued.

Phases 1 and 2 are pure infrastructure: they add no evidence, make no claim,
and cannot contaminate V1. Phases 3 and 4 are the actual experiment and each
requires explicit authorization before it starts.

## Constraints

- Python 3.11+, stdlib only in the exogenous layer. No new runtime dependency
  is worth the reproducibility cost.
- The exogenous package must not import from `orb_m/` or `aat_v1/`. Dependency
  direction is one-way, as with the Athena Core boundary.
- Analyst outputs are versioned and hashed. Changing a compressor changes its
  version and invalidates prior snapshots rather than silently re-scoring them.
- No network access in the compression path. Fetching is a separate, receipted
  step; compression is pure.

## Risks

**Exogenous data quality is the whole bet.** If `available_at` is wrong in the
source, every downstream guard is theater. Provenance for each source must be
documented before Phase 3 registers anything, the same way
`docs/HISTORICAL_SOURCE_PROVENANCE.md` covers bars today.

**Survivorship and coverage bias.** News and sentiment coverage is far denser
for large caps and for names that later moved. The frozen 50-name universe
limits this but does not remove it; coverage density must itself be a logged
feature so its effect is measurable.

**More features, more overfit surface.** Bucketing and a frozen key set are the
mitigation. The 300-pair floor and the sealed holdout remain the real defense.

**Arm E is expensive.** A deliberation loop multiplies token cost per
opportunity. It is gated behind equal-budget comparison so a win from
deliberation cannot be a win from simply spending more tokens.

## Success criteria

Phase 1–2 succeed when the exogenous layer compiles a hashed snapshot whose
as-of discipline is enforced by tests, the analyst compressors are
deterministic under replay, Actor identity is provider-portable with V1 hashes
unchanged, and the sufficiency probe can reject an insufficient dataset without
consuming an authorization.

The *experiment* succeeds when it produces a defensible answer — including
"adaptation did not help" — on a sealed V2 holdout. A null result that survives
audit is a success. A positive result that cannot name its mechanism is not.

## Open decisions

These need an answer before Phase 3 registers anything. Phases 1 and 2 can
proceed without them.

~~**Which exogenous sources actually get used.**~~ **Resolved:** copy the full
TradingAgents breadth — news, macro, StockTwits, Reddit, fundamentals and
Polymarket — tiered by relevance to a 09:45 ET intraday decision and graded by
provenance. See `docs/EXOGENOUS_SOURCES_V1.md`. That document also corrects an
error in an earlier draft of this one: fundamentals, not social sentiment, is
the worst point-in-time risk in the set, because affordable fundamentals APIs
serve restated figures that silently backfill the originals.

**Whether arm E is worth its cost.** A deliberation loop multiplies token spend
per opportunity. It is the most interesting thing TradingAgents does and the
least likely to survive an equal-budget comparison. It stays optional.

**Coverage floor for the frozen universe.** If exogenous coverage is thin
across the 50 names, the treatment is weak for most opportunities and the
comparison loses power. A minimum coverage rate should be measured in Phase 1
and frozen into the V2 contract before Phase 3, not discovered afterward.

**What the V2 dataset assignment looks like.** V1's assignment is spent. V2
needs its own TRAINING/holdout split, and the split must be drawn before any
exogenous feature is inspected.
