> **RESEARCH REFERENCE — product direction restored 24 September 2026.** This document retains its experiment/component history and restrictions. Its product-level next-step instructions are superseded by [Athena Trading Canon](ATHENA_TRADING_CANON.md) and [Build Plan](BUILD_PLAN.md). Read [Implementation Status](IMPLEMENTATION_STATUS.md) for current capability.

# AAT-V2 Progress, Status and Handoff

Written 8 September 2026. Status refreshed 16 September 2026 against current
`main` (macro-only claim contract, `REGISTERED_NOT_AUTHORIZED` protocol,
GDELT rejection, TRAINING dry-run plans, model-execution options, the
non-authorizing E-arm compact-schema amendment, a DeepSeek Flash
**candidate / pilot** identity, a **local Ollama / Qwen TRAINING
candidate** identity on `qwen3.5:9b`, a **RunPod / remote Ollama
`qwen2.5:14b` gold TRAINING candidate**, and an **7b volume
`qwen2.5:7b` TRAINING candidate**). The Terra protocol is unchanged. The
recommended next TRAINING step is **7b volume (1,000 stratified
opportunities) + 14b gold (100 overlapping opportunities)**, not the full
16,705 / 116,935 overnight. Nick authorized a **bigger live Flash pilot**
at $50 / ~500 calls / ~71 opportunities; that is still not TRAINING.
DeepSeek API overload (503) blocked that sample; Nick then authorized a
pivot to a fail-closed local Ollama TRAINING path, and separately
authorized RunPod remote-Ollama plumbing. The 14b Community 4090 smoke
(~35.4 s/call → ~48 days / ~$400 for the full plan) rejected that full
plan as the default. None of these paths silently flips Terra to authorized.

**One-line status.** The V2 experiment is built through a frozen macro-only
claim contract and a `REGISTERED_NOT_AUTHORIZED` protocol.
`execution_authority` is `ABSENT`. Arm E has a non-authorizing compact-schema
amendment so 64-token deliberation turns can emit complete JSON without
raising TRAINING spend. A live DeepSeek Flash pilot (not TRAINING) accepted
B/C/D 21/21 and E only 3/28, mostly schema mismatch rather than truncation;
E prompts now carry per-turn example json and rejected receipts store a raw
snippet. Nick authorized a bigger live Flash sample at $50 / ~500 calls
(~71 opportunities × 7 = 497 with deliberation); API 503 blocked it, and
that path is still not TRAINING. Adapters are not the blocker: the ALFRED
macro adapter is built, GDELT was rejected for this run after a bounded
coverage study, and news stays explicitly missing. DeepSeek Flash remains a
provider-scoped **candidate / pilot** identity. Local Ollama
`qwen3.5:9b` is a separate hashed `LOCAL_TRAINING_CANDIDATE`. RunPod Ollama
`qwen2.5:14b` is a separate hashed `RUNPOD_TRAINING_CANDIDATE` (gold).
Volume Ollama `qwen2.5:7b` is a separate hashed `VOLUME_TRAINING_CANDIDATE`.
Recommended in-sample TRAINING is the stratified 1,000-opportunity 7b
volume sample (`--authorize-volume-training`) plus the 100-opportunity 14b
gold slice (`--authorize-runpod-training`). That volume flag does not
authorize Terra, desktop 9b, or gold 14b. The full 16,705 / 116,935 plan is
plumbing, not the recommended next step. Astra Desk stays isolated. Holdout
stays untouched.

---

## 1. What this was, and what we borrowed

The starting question was how Athena Trading compares to
[TradingAgents](https://github.com/TauricResearch/TradingAgents) by Tauric
Research. (For the record, since it came up: TradingAgents is an LLM
agent-framework research project. It is not KuCoin or any other exchange, and
no exchange code, API or data was involved at any point.)

### The two projects are different kinds of thing

TradingAgents is an LLM-orchestration framework: a LangGraph graph of about
seven agent roles — fundamentals, sentiment, news and technical analysts, then
bull and bear researchers who debate, then a trader, then risk and portfolio
managers. It supports many LLM providers, splits "deep think" from "quick
think" models, and pulls a wide data surface: Yahoo Finance, StockTwits,
Reddit, global news, FRED, Alpha Vantage, Polymarket. Its own README states
that backtests will not reproduce and that it should be treated as a research
scaffold, not a strategy with a replicable return.

Athena Trading is a falsification experiment with a deterministic strategy at
the centre. ORB-M V1 is a complete, frozen, non-LLM strategy — opening range,
close confirmation, ATR/structure R, APDE trailing, bar-walking fill
simulation with slippage and commission, hard risk ceilings. The LLM Actor is
one *arm* in a controlled ablation, not the product.

The essential contrast: **TradingAgents assumes the multi-agent architecture is
the value. Athena built the machinery to test whether it is.**

### What we took

| Borrowed | What it became here | Why the change |
| --- | --- | --- |
| Analyst-role decomposition | Five deterministic compressors in `exogenous/analysts.py` | Their analysts *decide*; ours *compress*. An LLM panel with no control arm cannot be evaluated, so we kept the decomposition of the input space and discarded the decision authority. |
| Wide data surface | Six source categories in `docs/EXOGENOUS_SOURCES_V1.md` | Re-tiered for a 09:45 ET intraday decision instead of their daily horizon. |
| Multi-provider LLM support | `aat_v1/providers.py` descriptor registry | Identity is scoped by provider, so the same model string from a different vendor is a different Actor rather than a silent substitution. |
| Bull/bear debate loop | Arm E in `aat_v2/arms.py` | Demoted from the architecture to a *testable arm*, capped at the token budget of a single non-deliberating call. |

### What we deliberately did not take

- **Their agent graph as a decision architecture.** Without a deterministic
  control arm there is no way to attribute any result to the agents.
- **Their memory design.** `trading_memory.md` is appended in place, with no
  provenance and no partition discipline, so nothing distinguishes in-sample
  from out-of-sample.
- **Their posture on reproducibility.** They disclaim it. Athena's entire value
  is that it does not have to.

---

## 2. The thesis

### What was wrong with AAT-V1

The V1 four-arm comparison (A deterministic, B memoryless, C naive memory, D
Athena) was audit-passing and *structurally incapable of producing a strong
positive result*. Every arm reasoned over the same price-derived feature
vector. Arm D received one promoted lesson — "PASS versus standard sizing" —
and nothing else. There was no information in arm D's packet that arm A did not
already have.

Under those conditions the largest honest effect available is a re-weighting of
sizing under identical evidence. If arm D had beaten arm A, the most likely
explanation would have been sizing variance, not adaptation. The experiment
could produce a null, and it could produce an unattributable win. It could not
produce a defensible positive.

That is a ceiling on the experiment's design, not on Athena as an architecture.

### The V2 thesis

**Give the adaptive arms information the deterministic baseline structurally
cannot use, and the asymmetry becomes the mechanism.**

Arms B through E receive a bucketed exogenous feature vector — news, macro,
social, fundamentals, prediction markets. Arm A cannot receive it, because arm
A is the frozen ORB-M strategy and makes no model call at all. If arm D beats
arm A now, there is a named mechanism: the adaptive arm saw evidence the
control arm did not. If it does not, that is a real null about adaptation
rather than an artifact of a starved packet.

Everything else — the partitions, the receipts, the 300-pair floor, the
single-use holdout, the negative-knowledge registry, the refusal to claim — is
carried forward from V1 unchanged. The governance was never the problem.

### The intraday reframe

This is the single most important design decision in the whole effort, and it
is what makes copying TradingAgents' data surface non-trivial.

TradingAgents evaluates daily-horizon decisions. ORB-M decides at **09:45 ET**,
when the 15-minute opening range freezes, and is flat by 15:45 and hard-flat by
15:59. The relevant evidence window is **prior session close → 09:45**. That
re-ranks their entire source list:

- Overnight and pre-market catalysts are the whole game.
- A fundamentals *value* is nearly worthless at 09:45. The fundamentals
  *event* — "this name reported after yesterday's close" — is one of the
  strongest gap catalysts there is. So fundamentals is narrowed to filing
  events only, which also sidesteps the restatement problem almost entirely.
- Macro matters as a scheduled-event flag: an 08:30 print lands 75 minutes
  before the range freezes.
- Sentiment matters as *velocity into the decision*, not as a standing level.
- Polymarket has essentially no single-name equity coverage and lands in
  Tier 3, implemented as a stub that proves the record contract generalizes
  beyond equities.

### A correction I made along the way

In my first pass I told Nick that social sentiment carried the worst
point-in-time provenance of the set. **That was wrong**, and it changed the
build order, so it is recorded here rather than quietly fixed.

A Reddit or StockTwits post has an immutable `created_utc` — that *is* the
moment the content became observable, exactly the `available_at` semantics the
contract needs. Social's problems are retrieval, coverage bias and deletion
survivorship: real, but tractable and measurable.

**Fundamentals is the worst.** Most affordable fundamentals APIs serve a
*current view* — latest restated figures, silently backfilled over the original
filings. A backtest reading them sees numbers that did not exist on the
decision date, and nothing in the response says so. It is the one source that
leaks by default and looks clean while doing it.

---

## 3. What was built

Five commits on `claude/tradingagents-comparison-qi58ri`. **368 tests pass**
(228 pre-existing, 140 new), `ruff` clean.

### Phase 1 — exogenous evidence layer (`src/athena_trading/exogenous/`)

Six modules, ~1,080 lines, 61 tests. Stdlib only.

| Module | Responsibility |
| --- | --- |
| `contracts.py` | `ExogenousRecord`; `event_at` and `available_at` kept separate; visibility is `available_at <= decision_time` and nothing else |
| `buckets.py` | Frozen quantization; `ABSENT` distinct from bucket 0 |
| `analysts.py` | Five deterministic compressors → 24 frozen feature keys |
| `ingest.py` | Receipted record store; anti-backfill guard |
| `snapshot.py` | Joins features to opportunities; per-source coverage rates |
| `alfred.py` | FRED ALFRED vintage adapter; fixture-tested; no data acquired |
| `__init__.py` | Public surface |

Plus `scripts/measure_exogenous_coverage.py`.

**Design decisions worth knowing:**

- **Revisions are stored but never shown.** They stay in the store so their
  existence is auditable, but `visible_records` drops them rather than
  substituting them for originals. A replay sees the stale number the trader
  actually had — the conservative direction.
- **`ABSENT` (-1) is not bucket 0.** "No news at all" and "the fewest news
  items we bucket" are different facts. This surfaced a real bug mid-build:
  the first `bucket()` returned ABSENT for anything below the first edge,
  which on the signed macro-surprise scale collided a large miss with "no
  observation". Values below the first edge now clamp to 0; only `None` is
  ABSENT.
- **The anti-backfill guard is what makes news usable at all.**
  `assert_stable_availability` rejects a record whose `available_at` moves
  between pulls, matched on `payload.external_id`. Many news APIs re-timestamp
  a story on update or backfill, silently rewriting the one number the whole
  contract depends on. A vendor with no stable id passes unchecked, so its
  adapter must synthesize one and its provenance document must say how.
- **`session_windows` takes an optional `prior_close`.** The fallback is 16:00
  ET on the previous *calendar* day, which is wrong across weekends — a Monday
  decision would miss Friday afternoon. The fallback exists so compressors are
  testable in isolation and is documented as not good enough for a registered
  run; the snapshot builder passes the real prior close.
- **The compressors are explicitly unvalidated.** Windows, baselines and
  bucket edges are frozen so results are *reproducible*, not because any of
  them is known to be predictive. The docstrings say so, so nobody six months
  from now mistakes a frozen constant for a validated one.

**Independence is verified, not asserted.** `exogenous/` imports nothing from
`orb_m/` or `aat_v1/`. There is an AST test enforcing it, and the package was
physically deleted and the remaining 228 tests run green.

### Phase 2 — portable Actor identity (`src/athena_trading/aat_v1/`)

30 tests. The only phase that touched V1, and the riskiest.

**The pinning test was written first**, before any refactor —
`tests/test_aat_v1_identity_pinning.py` holds the four registered digests as
literals, with a docstring saying they must never be regenerated from the code
they guard. If a refactor moves one, every V1 receipt stops verifying while the
code keeps running.

```
prompt_hash        b7fa5ec9928d3ec22225bd757aa25b408ffdc9a5d3897bf8717a9d7d44bca88a
inference_hash     2c1cc91e081dd2f02283a520b0d01a226e9fc8320844e2126f95099de2b68633
action_schema_hash 852c32a80b5f4187ea6629270bfaf14162779e1a742690716a337eb107a26b3c
model_hash         9c4aaaa136ed098624bee45f5f75d0654f4d56ea526fc4cc51a1f3f3bf1ae5db
```

All four unchanged after the refactor.

- `providers.py` — descriptor carrying endpoint, payload builder, response
  readers, pricing guard. `model_hash` is provider-scoped. `OPENAI` is the only
  V1-registered provider. `DEEPSEEK` is a named descriptor for a V2 candidate
  identity and is **not** inserted into `registered_providers()`.
- `actor_canary.py` / `four_arm.py` — take the `OPENAI` descriptor by default,
  so no V1 behaviour or hash changes. `four_arm.py` is pinned explicitly rather
  than parameterized; its run is complete and frozen, and making finished
  evidence portable is churn.

**Correction to the plan as originally written.** It said Phase 2 would make
`PROVIDER_MODEL_MUTABILITY` stop being a permanent limitation. It does not, and
must not, for V1: that limitation is recorded in a frozen protocol whose
holdout is consumed, and rewriting how spent evidence describes itself is
precisely the retroactive edit this governance exists to prevent.
`readiness.py` and `training.py` keep their literal model pin untouched. What
Phase 2 delivers is that a *V2* protocol can register a provider-scoped
identity and therefore never inherits the limitation.

**No second vendor is registered in V1.** `registered_providers()` returns
`("openai",)` and a test asserts it. DeepSeek Flash is declared as a V2
candidate / pilot identity (`configs/aat_v2_deepseek_flash_actor_identity_v1.json`)
using the same hashed `provider` axis. It is not a V1 provider and it is not
bound to the registered Terra protocol.

#### The non-consuming sufficiency probe

`audit_holdout_preflight()` hardcodes `sealed_holdout_consumed: True`, so
merely *asking whether the dataset is big enough* spends the authorization.
That is what cost the V1 holdout: the frozen compiler found 249 of a required
300, the gate correctly returned `INVALID_EVIDENCE`, and a single-use
authorization was spent on a question that should have been settled before it
was issued.

`probe_holdout_sufficiency()` takes **no authorization argument at all** — it
cannot consume one because it is never given one, which is a stronger guarantee
than remembering not to. A test asserts those parameter names do not exist.
Verified against the exact V1 scenario:

```json
{ "qualified_opportunity_count": 249,
  "minimum_opportunity_count": 300,
  "status": "INSUFFICIENT",
  "sealed_holdout_consumed": false }
```

It returns a count and a verdict only — no per-symbol breakdown, no
distribution — so it cannot become a tuning channel, and every call is stamped
with the assignment hash so redrawing-until-it-clears appears in the log rather
than in someone's shell history.

### Phase 3 — experiment machinery (`src/athena_trading/aat_v2/`)

Five modules, ~617 lines, 49 tests.

| Module | Responsibility |
| --- | --- |
| `arms.py` | Five arms; treatment asymmetry; arm E equal-budget guard |
| `packet.py` | V2 Actor packet; fails closed in both directions; post-hoc ledger audit |
| `assignment.py` | Symbol-level split; linked-symbol grouping |
| `contract.py` | V2 claim contract; refuses to freeze without measured coverage |

Plus `scripts/draw_aat_v2_assignment.py`.

**The asymmetry is structural, not a flag.** Arm A cannot have a packet built
for it at all — it is the frozen strategy, not an Actor with features withheld.
`build_packet` fails closed in both directions: a treated arm without the
vector would silently degrade to a V1 packet and produce a null for the wrong
reason; a control arm with it would destroy the comparison. Neither is
recoverable from a ledger afterwards, so a finished run is audited again.

**Arm E is capped at one arm-D call's output budget** (4 turns × 64 tokens ≤
256). Without that, a win for deliberation is unattributable — it could simply
be more thinking tokens. The five-field Actor schema does not fit those
64-token turns (local Qwen accepted 0/400 E responses to unbounded JSON).
The compact closed-enum schema is bound by
`configs/aat_v2_e_arm_compact_schema_amendment_v1.json`, a
`NON_AUTHORIZING_PROTOCOL_NOTE`. A live DeepSeek Flash pilot then accepted
B/C/D 21/21 but E 3/28 (`24` schema mismatch, `1` `OUTPUT_TRUNCATED`,
output-token counts often well under 64). Chat Completions cannot pin
`json_schema`, so E system prompts now include a per-turn `EXAMPLE json
OUTPUT` object and rejected pilot records persist a raw content snippet.
The 4 x 64 budget is unchanged. The amendment does not rewrite the
registered protocol and does not authorize TRAINING.

#### The dataset assignment is drawn

`configs/aat_v2_dataset_assignment_v1.json`, seed 20260908:

```
assignment_hash  46f25ba0f64c5088add6d37a72752d6fbe156de6c33e8b8d7d4415e160f5e731
TRAINING (35)    AAPL ADBE AMAT AVGO BAC BRK.B COIN COST CRM CVX DIS INTC KO
                 LLY MA META MSFT MU NFLX NKE NVDA ORCL PANW PEP PFE PLTR
                 RIVN SMCI TMO UBER UNH V VZ WMT XOM
SEALED HOLDOUT   AMD AMZN BA C CMCSA CSCO GOOG GOOGL HD JNJ JPM PG PYPL QCOM
     (15)        TSLA
```

Split by symbol, not by opportunity: sessions of one name are correlated, and
an opportunity-level split would put February's AAPL in TRAINING and March's
AAPL in the holdout, so the holdout would measure memorization. It was drawn
while **no exogenous feature existed anywhere in the repository**, which is the
strongest available form of drawing before looking.

**The draw exposed a real defect.** The first version split by symbol alone, and
GOOG and GOOGL landing in the same partition was luck, not design. Dual-class
shares of one issuer move as one asset; a split pair would have contaminated
the holdout. `LINKED_SYMBOL_GROUPS` now binds them into a single draw unit,
**curated by hand** — a prefix-matching rule fires on V/VZ, BA/BAC and C/CVX,
which are unrelated issuers. A test checks sixty seeds. The first assignment was
deleted and redrawn under the fix.

---

## 4. Current status

| Item | State |
| --- | --- |
| Vision, plan, source spec | Written |
| Phase 1 exogenous layer | Built, 61 tests |
| Phase 2 provider registry | Built, 30 tests, V1 digests pinned and unchanged |
| Phase 2 sufficiency probe | Built, verified on the 249/300 case |
| Phase 3 arms / packet / contract | Built, 49 tests |
| Phase 3 dataset assignment | **Drawn and frozen** |
| Macro ALFRED adapter | Built and fixture-tested (`exogenous/alfred.py`). Provenance in `docs/ALFRED_MACRO_SOURCE_PROVENANCE.md`. No dump is committed. |
| GDELT news parser | Built and fixture-tested. Bounded coverage study complete. **Rejected for this run** (0.0778% `news_present` on the 16,705-opportunity TRAINING index). News stays explicitly missing. See `docs/GDELT_NEWS_SOURCE_PROVENANCE.md`. |
| Phase 3 coverage / claim contract | **Frozen, macro-only.** Required source is `macro` at floor 0.90; frozen measured coverage is macro 1.0, news 0.0. `claim_authorized` is false. Do not freeze a new contract. |
| Phase 3 protocol registration | **Registered as `REGISTERED_NOT_AUTHORIZED`.** `configs/aat_v2_registered_protocol_v1.json`. Actor identity remains OpenAI / `gpt-5.6-terra`. DeepSeek Flash is a separate `CANDIDATE_PILOT` identity and does not rewrite this protocol. |
| Phase 3 TRAINING dry-run plans | Present. `configs/aat_v2_training_plan_v2.json` supersedes v1: 16,705 opportunities, **116,935** planned calls, `dry_run: true`, `execution_authorized: false`. |
| Model execution options | Documented in `docs/AAT_V2_MODEL_EXECUTION_OPTIONS.md`. DeepSeek Flash dry-run / fixture preflight planner exists; thinking is disabled and Actor JSON is required on the B/C/D path. Arm E uses the compact closed-enum schema with per-turn example json after the live Flash E mismatch. A bounded pilot entrypoint exists (`scripts/run_aat_v2_deepseek_flash_pilot.py`) and defaults to fixture/dry. Nick-authorized **bigger live Flash pilot** (not TRAINING): **500 calls**, **$50.00**, **71 opportunities** (71 × 7 = 497 with E). Hard fail-closed caps are 80 opportunities / 500 calls / $50.00. Dry default stays 1 / 7 / $1.00. Hard PREFLIGHT spend ceiling remains $1.00. DeepSeek API 503 blocked that bigger sample. **Recommended TRAINING is 7b volume + 14b gold**, not the full 16,705 overnight. |
| Local Ollama TRAINING plumbing | Present. Hashed identity `configs/aat_v2_ollama_qwen_actor_identity_v1.json` (`LOCAL_TRAINING_CANDIDATE`, default model `qwen3.5:9b`). Authorization artifact `configs/aat_v2_ollama_local_training_authorization_v1.json` records Nick's local-TRAINING direction but still requires `--authorize-local-training` and does **not** rewrite Terra. Runner: `scripts/run_aat_v2_ollama_local_training.py`. Defaults to dry smoke (tiny N, mocked transport). Live loopback HTTP is `--allow-live-ollama`. Full 16,705 / 116,935 remains plumbing and still requires the flag plus frozen receipts. Resume/checkpoint is supported. Status `LOCAL_TRAINING_IN_SAMPLE` or `LOCAL_TRAINING_SMOKE`; `execution_authority` `ABSENT`. |
| RunPod / remote Ollama 14b gold plumbing | Present. Separate hashed identity `configs/aat_v2_ollama_qwen_14b_runpod_actor_identity_v1.json` (`RUNPOD_TRAINING_CANDIDATE`, `qwen2.5:14b`). Authorization `configs/aat_v2_ollama_runpod_training_authorization_v1.json` requires `--authorize-runpod-training` and does **not** authorize Terra, desktop 9b, or volume 7b. Same runner; `--base-url` native `/api/chat`. Recommended live use is the **100-opportunity gold slice** overlapping the 7b volume sample, full arms including E. The frozen 16,705 / 116,935 14b overnight is plumbing, not the recommended next step (measured ~35.4 s/call → ~48 days). `execution_authority` `ABSENT`. |
| RunPod / remote Ollama 7b volume plumbing | Present. Separate hashed identity `configs/aat_v2_ollama_qwen_7b_volume_actor_identity_v1.json` (`VOLUME_TRAINING_CANDIDATE`, `qwen2.5:7b`). Authorization `configs/aat_v2_ollama_volume_training_authorization_v1.json` requires `--authorize-volume-training` and does **not** authorize Terra, 9b, or 14b. Documented volume plan is a **stratified 1,000-opportunity** TRAINING subsample (`configs/aat_v2_training_subsample_plan_v1.json`, draw script `scripts/draw_aat_v2_training_subsample.py`). Default volume arms are full B/C/D+E; `--no-include-deliberation` is optional thin-E. Same native `/api/chat` runner. `execution_authority` `ABSENT`. |
| Phase 3 TRAINING run | **7b volume + 14b gold plumbing is ready; the 116,935-call run is not started in-repo and is not the recommended next step.** Nick can draw the subsample, then run volume 7b (1,000) and gold 14b (100) on a RunPod GPU. Prior local evidence was `qwen3-coder:30b` at ~0.348 calls/s → **~93h**; that tag is a different Actor. Compact E-arm schema now applies. DeepSeek remains blocked on API overload. |
| Phase 4 sealed holdout | Not started; needs a completed Phase 3 TRAINING run and separate authorization. The consumed AAT-V1 holdout must not be reused. V2 holdout symbols must not appear in the TRAINING index. |
| AAT-V1 | Frozen and closed. Holdout consumed (`INVALID_EVIDENCE`). Limitation stands. |
| Execution authority | `ABSENT` everywhere. No live-trading code exists. Astra Desk stays isolated. |

### Why the run was blocked, and what this dual-Actor plan changes

Not on adapters, and not on an unfrozen contract. The macro-only claim contract
is already frozen and the protocol is already registered as
`REGISTERED_NOT_AUTHORIZED`. DeepSeek Flash was the hosted candidate; a
bounded live pilot ran, then API 503 blocked the bigger Flash sample. Nick
authorized a pivot to **local Ollama** on his desktop (`qwen3.5:9b`), then
RunPod remote Ollama `qwen2.5:14b`. A Community 4090 14b smoke of ~35.4
s/call made the full 16,705 / 116,935 overnight (~48 days / ~$400) the
wrong default. The dual-Actor plan is 7b volume (1,000) plus 14b gold (100).

That plumbing does not rewrite
`configs/aat_v2_registered_protocol_v1.json`, does not grant broker
`execution_authority`, and does not consume V1 or V2 holdout. Volume still
needs `--authorize-volume-training`. Gold still needs
`--authorize-runpod-training`. Compact E JSON applies. Do not treat the
116,935-call plan as the next step.

```
registration_status: REGISTERED_NOT_AUTHORIZED
claim_authorized: false
execution_authority: ABSENT
```

---

## 5. Handoff — what to do next

### Immediate: 7b volume + 14b gold on the existing Ollama harness

The ALFRED adapter exists. GDELT was evaluated and rejected for this run. The
macro-only claim contract is frozen; the protocol is
`REGISTERED_NOT_AUTHORIZED`; the corrected dry-run plan is 116,935 calls
and is **no longer the recommended next step**. Recommended TRAINING is the
stratified 1,000-opportunity 7b volume sample plus the 100-opportunity 14b
gold slice. Nothing below authorizes broker execution, freezes a new
contract, or touches the consumed AAT-V1 holdout. Astra Desk stays isolated.

1. **Do not acquire a news dump for this run.** GDELT coverage was 0.0778%
   under the frozen compressor window. News remains explicitly missing unless
   a future provider supplies stable historical entity IDs and defensible
   point-in-time coverage, and that would be a *new* required-source decision
   — not a silent add to the frozen contract.
2. **Do not freeze another claim contract.** The current one already binds
   measured macro coverage 1.0 at a 0.90 floor. Lowering the floor because
   coverage disappointed is the move the contract exists to prevent.
3. **7b volume + 14b gold on RunPod, not a 16,705 overnight and not DeepSeek
   API.** Flash remains a `CANDIDATE_PILOT`. Desktop identity:
   `configs/aat_v2_ollama_qwen_actor_identity_v1.json`, default model
   `qwen3.5:9b` (loopback only). Volume identity:
   `configs/aat_v2_ollama_qwen_7b_volume_actor_identity_v1.json`, model
   `qwen2.5:7b`. Gold identity:
   `configs/aat_v2_ollama_qwen_14b_runpod_actor_identity_v1.json`, model
   `qwen2.5:14b`. A different Ollama tag is a new hashed identity, not a
   runtime swap. Transport is native `/api/chat` with `think: false`. Compact
   E-arm schema applies. Volume default is full arms; thin-E is
   `--no-include-deliberation`. Gold keeps E.
4. **Draw the stratified subsample, then volume, then gold.** Exact commands
   are in `docs/AAT_V2_MODEL_EXECUTION_OPTIONS.md`. Default CLI is mocked
   smoke. Live needs `--allow-live-ollama`. Volume 1,000 needs
   `--authorize-volume-training` and the hashed volume subsample receipt.
   Gold 100 needs `--authorize-runpod-training` and the gold receipt.
   `--resume` is required after a hitch. Download RunPod artifacts before
   terminating the pod. Measured 14b pace was ~35.4 s/call; 7b wall-clock is
   unmeasured (hypotheses are labelled in the execution-options doc).
5. **DeepSeek Flash identity and bounded pilot remain in-tree and are not
   TRAINING.** The bigger-pilot command is still
   `python scripts/run_aat_v2_deepseek_flash_pilot.py --allow-live --opportunities 71 --call-ceiling 500 --spend-ceiling-usd 50.00`
   if the API recovers. Hard caps stay 80 / 500 / $50.00. Do not silently
   reuse the Terra protocol for either vendor.

### Then, in order

Item 5 below is done. Local Ollama TRAINING plumbing is in-tree and is
in-sample execution under Nick's flag, not a Terra protocol promotion.
DeepSeek identity + bounded pilot remains machinery only. Items 6-8 still
wait on a completed in-sample run and separate holdout authorization.

5. **E-arm JSON truncation is addressed without TRAINING spend.** The local
   Qwen 100-opportunity pilot accepted 0/400 E responses because 64-token
   turns required the five-field Actor schema. Compact closed-enum turns are
   bound by `configs/aat_v2_e_arm_compact_schema_amendment_v1.json`. The live
   Flash pilot showed a second E failure: extra keys / wrong enums / Actor
   shapes under `json_object`, not compact overflow. Prompts now include a
   per-turn example json object; the parser stays fail-closed (case and
   numeric-string coercions only); rejected receipts store a 512-character
   snippet. The 4 x 64 = 256 equal-budget cap is unchanged. That artifact is
   a `NON_AUTHORIZING_PROTOCOL_NOTE`: it does not rewrite the registered
   protocol, does not freeze a new coverage contract, and does not
   authorize TRAINING.
6. Only after **explicit TRAINING authorization**: run the comparison. Audit
   it. Label it in-sample evidence, because that is what it is.
7. Compile holdout opportunities only under a future V2 authorization. If a
   sufficiency question comes up first, use `scripts/probe_holdout_sufficiency.py`
   — it takes no authorization and cannot consume one. Do not point it at the
   consumed AAT-V1 holdout.
8. Phase 4 sealed holdout requires separate, explicit authorization.

### Open decisions still outstanding

- **Whether 7b volume and 14b gold TRAINING starts finish, and at what
  E accept rate.** Compact E JSON is bound; the old 0/400 E result is stale.
  The recommended plan is 1,000 / 100, not 16,705. Hosted Flash remains
  blocked on API 503. Declaring either Ollama identity does not rewrite Terra.
- **Whether arm E earns its cost.** It is the most interesting thing
  TradingAgents does and the least likely to survive an equal-budget
  comparison. The 64-token turn no longer requires unbounded Actor JSON; the
  compact schema is bound. E stays in the registered arm set.
- **Which Tier-2 sources to adopt at all.** Social has sound timestamps but
  awkward retrieval — Pushshift has no public API since losing privileged
  ingestion after Reddit's 2023 changes; historical access now runs through
  Arctic Shift, Academic Torrents, or Reddit's researcher program, all frozen
  bulk archives. Fine for backtest, useless if this ever goes live. Not on
  the critical path for the current macro-only run.
- **A fundamentals vendor**, if fundamentals is adopted later. Must serve
  as-reported figures time-indexed to release date — Sharadar's as-reported
  dimensions, Calcbench's as-filed capture, LSEG's point-in-time product. A
  current-view REST API is disqualified regardless of price.

The coverage floor for *this* run is already decided: 0.90 on macro, measured
at 1.0. Do not reopen it after looking at a result.

### Known limitations carried forward

- `session_windows` calendar-day fallback is wrong across weekends; always
  pass `prior_close`.
- Compressor scoring semantics are frozen but unvalidated.
- Only one Actor provider is registered in V1 (`openai`). DeepSeek Flash is a
  V2 `CANDIDATE_PILOT` identity with a bounded fixture pilot. Local Ollama
  `qwen3.5:9b` is a V2 `LOCAL_TRAINING_CANDIDATE`. RunPod Ollama
  `qwen2.5:14b` is a V2 `RUNPOD_TRAINING_CANDIDATE`. Volume Ollama
  `qwen2.5:7b` is a V2 `VOLUME_TRAINING_CANDIDATE`. None is the registered
  Terra Actor. TRAINING receipts are in-sample and still
  `execution_authority: ABSENT`.
- `four_arm.py` is pinned to OpenAI by design.
- Exogenous coverage is denser for large caps and for names that later moved.
  Coverage density is emitted as a feature so the effect stays measurable, but
  it is not eliminated.
- GDELT is not adopted for the current run; news coverage is explicitly zero
  in the frozen contract.

---

## 6. Standing judgement

The governance is the asset. It is the thing TradingAgents has no equivalent
of, and the reason an eventual Athena claim would mean something where theirs
cannot. Nothing in this work weakened it: V1 stayed frozen, its digests are
pinned as literals, its holdout stays consumed, its limitation stands, and the
new contract refuses to freeze against a number nobody has measured.

The honest summary of V2 so far is that it removed the ceiling on the
experiment, froze a macro-only contract, and registered a protocol that still
cannot spend. Whether adaptation helps is still unknown. The machinery can
produce a defensible answer either way — including "it did not help" — once
TRAINING is separately authorized.

The next real risk is not a missing adapter. It is promoting the local Ollama,
RunPod Ollama, volume Ollama, or DeepSeek identity into the registered Terra
protocol, treating a ~93h or ~48-day start as a finished claim, lowering a
frozen floor, or reusing the consumed V1 holdout. The contract, the protocol
status, the candidate identities, the compact-schema amendment, the
local-TRAINING / RunPod-TRAINING / volume-TRAINING CLI flags, and the
consumed-holdout registry are written to make those moves visible. Keep them
that way.
