> **RESEARCH REFERENCE — product direction restored 24 September 2026.** This document retains its experiment/component history and restrictions. Its product-level next-step instructions are superseded by [Athena Trading Canon](ATHENA_TRADING_CANON.md) and [Build Plan](BUILD_PLAN.md). Read [Implementation Status](IMPLEMENTATION_STATUS.md) for current capability.

# AAT-V2 Implementation Plan

Companion to `docs/AAT_V2_VISION.md`. That document says what we are building
and why. This one says in what order, in which files, and what has to be true
before each step is allowed to start.

Status: Phases 1-2 BUILT. Phase 3 machinery BUILT, the assignment drawn, a
macro-only claim contract frozen, a non-authorizing V2 protocol registered,
and a TRAINING dry-run plan prepared.
The 35-symbol TRAINING campaign, outcome-free opportunity index, and macro
snapshot are built and receipted. GDELT was evaluated through a bounded
multi-slice study and rejected for inadequate coverage. The TRAINING run
remains separately gated; Phase 4 is proposed.

## Ground rules for the whole plan

1. **AAT-V1 is immutable.** No file under `src/athena_trading/aat_v1/` changes
   its behaviour, and no V1 identity hash changes by a single byte. Phase 2
   touches that directory and is the one place this rule needs a test to prove
   it held.
2. **The constitution does not move.** `orb_m/constitution.py` is untouched in
   every phase. If a phase seems to need a constitution change, the phase is
   wrong.
3. **One-way dependencies.** The new `exogenous/` package may import from
   `athena_adapter/`. It may not import from `orb_m/` or `aat_v1/`. The
   deterministic strategy must stay runnable with `exogenous/` deleted, and a
   test asserts that.
4. **Nothing spends money or calls a model until Phase 3**, and Phase 3 does
   not start without explicit authorization.
5. **`execution_authority` stays `ABSENT`** in every receipt, every phase.

---

## Phase 1 — exogenous evidence layer — BUILT

Pure infrastructure. Adds no evidence, makes no claim, calls nothing.

Delivered in `src/athena_trading/exogenous/`: `contracts.py`, `buckets.py`,
`analysts.py`, `ingest.py`, `snapshot.py`, `alfred.py`, plus
`scripts/measure_exogenous_coverage.py`. Twenty-four bucketed feature keys
across five source categories. The full suite passes with the package
physically deleted, so the deterministic strategy carries no dependency on it.

The ALFRED macro adapter is built (`exogenous/alfred.py`, provenance in
`docs/ALFRED_MACRO_SOURCE_PROVENANCE.md`) and the training macro snapshot
measures 1.0 coverage across 16,705 opportunities. GDELT's parser is built,
but its bounded study measured 0.0778% news coverage and it is not adopted.
News is therefore explicitly missing for the current run. The adapter surface
remains a pure per-row function so a future source swap is a new adapter rather
than a new pipeline.

### 1.1 Record contract — `src/athena_trading/exogenous/contracts.py`

`ExogenousRecord`: frozen dataclass carrying `source`, `symbol`, `event_at`,
`available_at`, `payload`, `revision_of`.

The two timestamps stay separate and both are required. `event_at` is when the
fact became true; `available_at` is when it first became observable. For an
earnings figure those are weeks apart, and collapsing them is the leak that
makes exogenous backtests worthless.

Enforced at construction:
- both timestamps timezone-aware, `available_at >= event_at`
- `source` drawn from a frozen vocabulary (`news`, `sentiment`,
  `fundamentals`, `macro`) — a new source is a schema change, not a new string
- `symbol` required except for market-wide sources
- non-empty payload

`visible_records(records, as_of=..., symbol=..., lookback_seconds=...)` is the
single visibility path. Rules: `available_at <= as_of` inclusive, revisions
dropped rather than substituted (a replay sees the stale number the trader
actually had), deterministic sort by `(available_at, record_id)` so analyst
output never depends on input file order.

`assert_no_lookahead()` is the belt-and-braces check callers run on an
already-filtered set.

### 1.2 Per-source ingest

Six source categories, specified in `docs/EXOGENOUS_SOURCES_V1.md`, each with
its own receipted ingest step. Order is Tier 1 (macro via ALFRED vintages, news
with first-seen publication timestamps) → coverage measurement → Tier 2
(StockTwits, Reddit, fundamentals as filing events only) if coverage clears the
floor → Polymarket stub.

Ingest is separate and receipted. Compression is pure and offline. Compressors
map to categories rather than vendors, so swapping a source inside a category
does not change the feature key set.

### 1.3 Analyst compressors — `src/athena_trading/exogenous/analysts.py`

This is where TradingAgents' analyst-team split gets borrowed and stripped of
its authority. Their analysts *decide*; ours *compress*. Each is a pure
function from visible records to a fixed, versioned key set. No model call, no
network, fully reproducible from a snapshot hash.

Four compressors, each emitting a frozen key set:
- **news** — item counts over trailing windows, scheduled-event flag, coverage
  density relative to the symbol's own baseline
- **sentiment** — mean and dispersion of pre-scored sentiment, mention volume
  vs. baseline (only if a defensible source is found; see open decisions)
- **fundamentals** — days since last first-publication report, surprise bucket
- **macro** — regime flags from macro series

Every continuous value is **bucketed** before it leaves the compressor.
Precision the strategy cannot act on is precision the Actor can overfit to.
Bucket edges are frozen constants and part of the compressor version hash.

Each compressor carries a version string. Changing a compressor changes its
version and invalidates prior snapshots rather than silently re-scoring them.

Deliberately unvalidated: these scoring semantics are guesses. They are frozen
so they are *reproducible*, not because they are known to be predictive. The
docstrings must say so, so nobody later mistakes a frozen constant for a
validated one.

### 1.4 Snapshot projection — `src/athena_trading/exogenous/snapshot.py`

Joins compressed features to opportunity ids and writes a projection plus a
receipt, mirroring the existing `aat_v1/opportunities.py` shape: canonical
hash, `rows_sha256`, row count, `contains_sealed_holdout`,
`execution_authority: ABSENT`, and the compressor versions in the receipt so a
snapshot names the code that produced it.

Fetching is a separate receipted step. Compression is pure and offline.

### 1.5 Coverage measurement — `scripts/measure_exogenous_coverage.py`

Reports coverage rate per source across the frozen 50-name universe. This is
the input to the coverage-floor decision in the vision doc: if coverage is thin
the treatment is weak for most opportunities and the comparison loses power.
Better to learn that here than after registering a protocol.

### 1.6 Tests

- as-of boundary: a record at exactly `as_of` is visible; one microsecond later
  is not
- revision records never surface, in place of their original or otherwise
- naive-datetime and `available_at < event_at` rejected at construction
- compressor determinism: shuffled input, identical output hash
- bucket edges pinned by explicit expected values
- snapshot receipt round-trips and detects a mutated row file
- `exogenous/` imports nothing from `orb_m/` or `aat_v1/`

**Exit criteria:** tests green, coverage report produced for the frozen
universe, zero changes outside `exogenous/`, `scripts/`, `tests/`, `docs/`.

---

## Phase 2 — portable Actor identity — BUILT

The one phase that touches `aat_v1/`. Small, contained, and the riskiest to get
wrong, because V1 receipts must keep verifying.

Delivered: `aat_v1/providers.py`, the `OPENAI` descriptor wired through
`actor_canary.py` and `four_arm.py` behind defaults, the non-consuming
sufficiency probe in `holdout_gate.py`, `scripts/probe_holdout_sufficiency.py`,
and 30 tests. The V1 identity digests are pinned as literals in
`tests/test_aat_v1_identity_pinning.py`, written before the refactor.

**One correction to this plan as originally written.** It said
`PROVIDER_MODEL_MUTABILITY` would stop being a permanent limitation. It does
not, and must not, for V1: that limitation is recorded in a frozen protocol
whose holdout is consumed, and rewriting how spent evidence describes itself
would be exactly the kind of retroactive edit the governance exists to prevent.
`readiness.py` and `training.py` keep their literal model pin untouched. What
Phase 2 actually delivers is that a *V2* protocol can register a
provider-scoped identity and therefore never inherits the limitation.

`four_arm.py` is pinned to `OPENAI` explicitly rather than parameterized. Its
run is complete and frozen; making it provider-portable would be churn on
finished evidence.

### 2.1 Provider registry — `src/athena_trading/aat_v1/providers.py`

Today `actor_canary.py` hardcodes `API_URL`, derives
`model_hash = canonical_hash({"provider": "openai", "model": model_id})`,
requires pricing `source_url` to start with `developers.openai.com`, and
`readiness.py` pins the literal `gpt-5.6-terra`. That is why
`PROVIDER_MODEL_MUTABILITY` is a permanent limitation rather than a managed
axis.

A provider descriptor carries: provider id, endpoint URL, request builder,
response text extractor, usage extractor, and the allowed pricing source-URL
prefix. The registry returns a descriptor by provider id.

**Byte-compatibility requirement.** For `provider="openai"` the registry must
reproduce the existing `model_hash`, `prompt_hash`, `inference_hash` and
`action_schema_hash` exactly. A test pins the current V1 digests as literals
and fails if any of them move. Without that test this phase is not safe to
merge.

### 2.2 Rewiring

`actor_canary.py` and `four_arm.py` take a provider descriptor instead of
module-level constants, defaulting to the OpenAI descriptor so existing call
sites and receipts are unchanged. `readiness.py` reads the model id from the
registered protocol instead of a literal.

### 2.3 Tests

- V1 digests pinned as literals, unchanged
- a second provider produces a *different* `model_hash` (identity is
  provider-scoped, not model-name-scoped)
- pricing validation rejects a source URL from the wrong provider
- an unregistered provider id fails closed

**Exit criteria:** the full existing test suite passes untouched, plus the new
pinning test.

### 2.4 Non-consuming sufficiency probe — `aat_v1/holdout_gate.py`

Separable from the provider work; grouped here because it is the other small
fix to existing code.

`audit_holdout_preflight()` hardcodes `"sealed_holdout_consumed": True`, so
merely *asking whether the dataset is big enough* burns the authorization. That
is what cost the V1 holdout: the compiler found 249 of a required 300, the gate
correctly returned `INVALID_EVIDENCE`, and the authorization was spent on a
question that should have been answered before it was issued.

Add `probe_holdout_sufficiency()`: takes the candidate dataset assignment and
the frozen contract, returns the qualified-opportunity count and a
sufficient/insufficient verdict, sets `sealed_holdout_consumed: False`, and
touches no authorization. Run it at dataset-construction time, before sealing.

To keep the probe from becoming a tuning channel it returns a count and a
boolean only — no per-symbol breakdown, no distribution — and each probe is
logged with the assignment hash so repeated probing against one assignment is
visible in the record.

**Exit criteria:** probe cannot run against an authorization, cannot mark
anything consumed, and its result hash is reproducible.

---

## Phase 3 — V2 protocol and arm E — MACHINERY BUILT, RUN BLOCKED

Authorized and started. `src/athena_trading/aat_v2/` holds `arms.py`,
`packet.py`, `assignment.py` and `contract.py`, plus
`scripts/draw_aat_v2_assignment.py` and 49 tests.

**Step 1 is done.** `configs/aat_v2_dataset_assignment_v1.json` was drawn at
seed 20260908 over the frozen 50-name universe: 35 TRAINING symbols, 15
holdout, split by symbol so no name straddles partitions. It was drawn while no
exogenous feature existed anywhere in the repository, which is the strongest
form of "drawn before looking" available.

The draw surfaced a real defect. The first version split by symbol alone, and
GOOG and GOOGL landing in the same partition was luck, not design. Dual-class
shares of one issuer move together, so splitting them would have let the
holdout measure memorization of the same tape. `LINKED_SYMBOL_GROUPS` now binds
them into one draw unit, curated by hand rather than inferred — a
prefix-matching rule fires on V/VZ, BA/BAC and C/CVX, which are unrelated
issuers. A test checks sixty seeds.

**Steps 5 and 6 are done.** `packet.py` carries the exogenous vector for arms
B-E and refuses to build one for arm A at all, since arm A is the frozen
strategy rather than an Actor with features withheld. Both directions fail
closed: a treated arm without the vector would silently degrade to a V1 packet
and produce a null for the wrong reason. `arms.py` holds arm E to the same
total output budget as one arm-D call, so a win from deliberation cannot be a
win from spending more tokens.

**The macro-only claim contract is now frozen and registered.** It requires 300 minimum pairs,
a 0.90 macro coverage floor, binds the measured 1.0 macro coverage, and keeps
news explicitly absent because GDELT failed its coverage gate. `claim_authorized`
remains false. The registered protocol is `REGISTERED_NOT_AUTHORIZED`. The
corrected dry-run plan requires 116,935 model calls because arm E has four
deliberation turns per opportunity. The earlier 66,820-call and $376.029464
estimate is superseded; the conservative Terra ceiling is approximately
$504.10. See `docs/AAT_V2_MODEL_EXECUTION_OPTIONS.md`. The remaining work is
an explicitly authorized TRAINING run; no model calls or holdout access are
implied by contract, registration, or plan.

Original sequence, for reference:
1. Draw the V2 dataset assignment — TRAINING and sealed holdout — **before any
   exogenous feature is inspected**.
2. Run the Phase 2 sufficiency probe against the holdout candidate. If it comes
   up short, redraw. No authorization is issued until the probe clears.
3. Freeze the V2 claim contract: minimum pairs, scoring semantics, arm
   definitions, exogenous feature key set and bucket edges.
4. Register the V2 protocol with the compressor versions and provider-scoped
   Actor identity bound in.
5. Extend the Actor packet with the exogenous feature vector for arms B/C/D
   only. Arm A is the frozen deterministic strategy and cannot consume them by
   construction — that asymmetry is the treatment.
6. Optional arm E: bounded bull/bear deliberation, capped at the *same* total
   token budget as a single arm-D call, so a win from deliberation cannot be a
   win from spending more.
7. Run the TRAINING comparison. Audit it. Expect it to be in-sample evidence
   and label it as such.

**Exit criteria:** audit-passing TRAINING result, honestly labelled as
in-sample.

---

## Phase 4 — V2 sealed holdout

Separate authorization, single use, same gateway as V1. Runs once. The result
stands whatever it says, including "adaptation did not help", and the
consumed-holdout registry gets its entry either way.

---

## Sequencing and what can run in parallel

Phase 1 and Phase 2 are independent and can be built in either order or at the
same time — they share no files. Phase 3 needs both. Phase 4 needs Phase 3.

Recommended order: **Phase 2 first**, despite the numbering. It is the smaller
change, it removes a limitation that currently blocks readiness, and the
sufficiency probe in 2.4 prevents repeating the mistake that cost the V1
holdout. Phase 1 is the larger build and nothing downstream is blocked by
starting it second.

## Where this can go wrong

**The pinning test in 2.1 is the load-bearing one.** If provider-registry
refactoring silently changes a V1 hash, every V1 receipt stops verifying and
the audit trail breaks. Write that test before the refactor, not after.

**Exogenous provenance is the real bet.** If `available_at` is wrong in the
source data, every guard in Phase 1 is theater. Source provenance needs the
same treatment `docs/HISTORICAL_SOURCE_PROVENANCE.md` gives bars, documented
before Phase 3 registers anything.

**Thin coverage silently weakens the experiment.** If most opportunities have
no exogenous evidence, arms B/C/D are effectively arm A with extra steps and the
comparison produces a null for a boring reason. 1.4 exists to catch that early;
the coverage floor belongs in the V2 contract.

**Scope creep into the constitution.** The temptation in Phase 3 will be to let
exogenous features adjust something the constitution freezes. That converts the
experiment into a different strategy and the evidence stops transferring.
