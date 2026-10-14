> **RESEARCH REFERENCE — product direction restored 24 September 2026.** This document retains its experiment/component history and restrictions. Its product-level next-step instructions are superseded by [Athena Trading Canon](ATHENA_TRADING_CANON.md) and [Build Plan](BUILD_PLAN.md). Read [Implementation Status](IMPLEMENTATION_STATUS.md) for current capability.

# AAT-V1 training planner

`run_aat_v1_training.py` validates a separately materialized `TRAINING` JSONL
projection and emits a deterministic dry-run plan. It does not invoke an
Actor, read a mixed dataset, score outcomes, contact a broker, or grant
authority. The projection receipt must bind `dataset_hash`, `assignment_hash`,
`protocol_hash`, row count, and an exact SHA-256 of the JSONL file.

`compile_aat_v1_opportunities.py` is the only bridge from Athena's raw bar
projection to this boundary. It verifies the complete source hash and explicit
absence of sealed content, then emits the first completed close breakout after
the frozen 15-minute ORB-M range. Its features are available at signal time and
contain neither outcomes nor symbol/date identifiers. It does not implement or
approximate the still-unbuilt Breakout Quality Score.

The initial canary is capped at $20 total spend. It may contain at most ten
opportunities and therefore at most 30 Actor calls: deterministic Arm A makes
no model request, while Arms B, C, and D each make one. No request may occur
until a separate immutable pricing record makes the transport bound explicit.

The command requires explicit call, token, and spend ceilings and refuses to
overwrite its output. The transport canary may consume this boundary only
under its explicit configuration; an adaptation or outcome-scoring runner
remains separately gated.

## Pre-canary validation evidence

Validated locally on 3 September 2026 against Athena projection
`aef846f2b26bac428e8de48845bd4ce129eaa2c00a62e4b17272dd522e9113cc`:

- source rows verified: 1,165,277;
- opportunity rows emitted: 10;
- opportunity rows SHA-256:
  `1ac694b3b25b6f7c8e49c09c01b1abe5b46de08ec66f03cb9498b312d9f39c38`;
- dry plan: 30 Actor calls and 11,730 tokens under the original $10 ceiling;
- full repository tests: 158 passed;
- spend estimate: `UNPRICED`, therefore no Actor request is permitted;
- at validation time, API calls made: 0 and spend incurred: $0;
- execution authority: `ABSENT`.

## Terra transport canary

The authorized transport canary ran on 3 September 2026 using the official
Terra rates frozen in `configs/openai_gpt_5_6_terra_pricing_2026-09-03.json`:
$2.00 per million input tokens and $12.00 per million output tokens. The source
is the official OpenAI model page recorded in that configuration.

This run is explicitly `TRANSPORT_CANARY_NOT_ADAPTATION`. No lesson inventory
exists yet, so it cannot support a comparison among memoryless, naive-memory,
and Athena-memory behavior. Two pre-ledger diagnostic calls are counted against
the 30-call ceiling and assigned a conservative cost upper bound rather than an
invented exact cost.

- total calls including diagnostics: 30;
- durably recorded calls: 28;
- accepted structured responses: 27;
- rejected responses: 1 (`RESPONSE_NOT_COMPLETED`), with no retry;
- full repository tests after runner implementation: 164 passed;
- recorded usage: 7,986 input tokens and 5,679 output tokens;
- recorded cost: $0.08412;
- corrected total cost upper bound including diagnostics: $0.095888;
- ledger SHA-256:
  `0f60516bd3df904e46c6f05592df81aed96088ab9aa4cb374ec9d1bd69a139ff`;
- sealed holdout consumed: false; execution authority: `ABSENT`.

## Frozen final claim contract

The final AAT-V1 claim contract was frozen on 5 September 2026 without reading
sealed-holdout content. It binds the registered protocol and completed
four-arm TRAINING evidence. A future one-time evaluation may support only the
claim `AAT_V1_MEMORY_IMPROVES_DECISION_QUALITY`, comparing D against both the
memoryless B arm and naive-memory C arm on at least 300 matched sealed-holdout
opportunities.

Support requires every comparator to show at least 0.01R mean paired-regret
improvement, a positive deterministic 95% bootstrap lower bound, no drawdown
regression above 0.1R, and at least 100 observations in each LONG and SHORT
regime. Missing, mismatched, reused, or incomplete evidence is invalid;
otherwise any failed gate produces `CLAIM_NOT_SUPPORTED`. Neither outcome
grants execution authority. The mutable Terra provider alias remains a
permanent limitation.

- contract hash:
  `269a2e4842ac591d1f89de5b518bd9c2ffc49d682e2e313156df8c75e37fd904`;
- freeze receipt hash:
  `fd13d70c59147fca250036d180c5a736a6a5528c357899c6c7161e1486921c6c`;
- status: `FROZEN_AWAITING_SEPARATE_HOLDOUT_AUTHORIZATION`;
- claim authorized: false; sealed holdout accessed: false; execution authority:
  `ABSENT`.

The evaluation boundary now also has deterministic, fail-closed enforcement.
It rejects authorization that is not separately identified, contract-bound,
single-use, and unused; rejects incomplete three-arm pairs, wrong partitions,
authority drift, duplicate identities, and insufficient LONG/SHORT support;
and applies the frozen bootstrap, effect, and drawdown gates to both
comparators. These controls were exercised with synthetic fixtures only. No
production authorization receipt was created and no sealed evidence was read.

## One-time holdout authorization and export

On 4 September 2026 the repository owner explicitly instructed the project to
continue past the frozen authorization boundary. That instruction was recorded
as authorization `aat-v1-owner-authorization-2026-09-04`, bound to the final
claim-contract hash and the existing $20 ceiling. Authorization hash:
`845cf5d3fb72991cd9866085c0b47ccb32f875c3f4451d83bd48e962cf3e45aa`.

Athena Core then exported exactly the 203,735 rows assigned to the registered
sealed holdout. The exporter reverified every canonical evidence ID against
the original frozen source and refused overwrite or contract drift. The sealed
holdout is now consumed and may not be reused, resealed, tuned against, or
treated as fresh evidence again.

- holdout projection hash:
  `d3764af4c21500f077404ebb15e4ba4b48af96217d426270fad4382f3e120784`;
- holdout rows SHA-256:
  `2d311d317ed604608f97b770dcf5b1f733fb3f2eeb2fa8bcdca360fe3153b64e`;
- source SHA-256 remained:
  `ef97982d3e015db27347dea5a4d988734bcc46a7a89d600ff3343f89b110635a`;
- Actor calls: 0; incremental model cost: $0; execution authority: `ABSENT`.

No claim result exists yet. The next implementation must compile the fixed
holdout opportunities without reusing the TRAINING-only compiler interface or
changing its frozen ORB-M semantics.

## Final holdout disposition: invalid evidence

The dedicated compiler reused the frozen
`ORB_M_FIRST_CLOSE_BREAKOUT_V3_RESOLVED_ATR14` semantics and used only the
previously known TRAINING projection as point-in-time ATR history. Candidate
selection remained restricted to sealed sessions. It produced 249 qualified
opportunities, below the frozen minimum of 300.

The preflight therefore ended the evaluation as `INVALID_EVIDENCE` before any
Actor call. The threshold will not be relaxed and the consumed holdout will not
be mined, extended, resealed, or reused. This result neither supports nor
refutes the adaptation claim; it establishes that the preregistered claim is
not evaluable from this holdout.

- opportunity projection hash:
  `e088945ba2c75e14192187552380396d41f09f5c3aecd31d62ac49bd86a785b9`;
- opportunity rows SHA-256:
  `5477305c2e598cdd8cc71d51abc6534f960d512d9613b8384a64550ea4e75d64`;
- qualified opportunities: 249; frozen minimum: 300;
- preflight result hash:
  `29891a9ecd711a120c626a8d31594788d9c76ef1ee060a385660f99bef6416b5`;
- Actor calls: 0; additional model cost: $0; claim authorized: false;
  execution authority: `ABSENT`.

The consumed state is now enforced by the tracked registry
`configs/aat_consumed_holdouts_v1.json`, canonical hash
`4cf3fd33452a86352d57262be0181271093147ab4ccff99cb64fea63e79b85aa`.
It binds the dataset assignment, authorization, raw holdout projection,
opportunity projection, and terminal preflight result. Both the Trading gate
and Core exporter reject reuse of the authorization or dataset assignment.

## Four-arm matched TRAINING comparison

On 4 September 2026 the registered four-arm comparison completed across the
same 300 TRAINING opportunities: deterministic ENTER_STANDARD (A), memoryless
Terra (B), Terra with the strongest rejected lesson (C), and Terra with the
promoted PASS lesson (D). Arms C and D each received a 12-token memory item.
The Actor produced 900 accepted decisions from 918 attempts; 18 attempts were
rejected fail-closed. One decision exhausted its two registered attempts, and
an immutable recovery record authorized exactly one same-inference retry.

The final evidence contains 1,200 matched episodes. Mean regret was 0.13895R
for A, 0.12172R for B, 0.10877R for C, and 0.07858R for D. D selected PASS in
300 of 300 TRAINING episodes. This is an in-sample prompt-steering result: the
PASS lesson was derived from these same TRAINING outcomes, so it is neither an
adaptation claim nor trading-performance evidence. The independent audit
therefore passes the comparison infrastructure while explicitly setting
`claim_authorized` to false.

- final result hash:
  `aa0bb85683fc7b0062f97143bcdb9d996257625ef805d595e2dbec13cdaf7702`;
- ledger SHA-256:
  `654d7333b8dcb9bc9209971b22d29b0d6afc59711f91642c4af21bbb20fe8e15`;
- episode rows SHA-256:
  `e4918daa4cfc5e0fffb66c3e7d18dce063d9091990174113e38f0724477b113e`;
- audit hash:
  `6df8e9105acbbcdd496809e39fe931c4222ed2d739e1d64a1cbb3ed3a3200452`;
- measured incremental cost: $2.213500; cumulative upper bound including the
  prior canary: $2.309388, below the registered $20 ceiling;
- sealed holdout consumed: false; execution authority: `ABSENT`.

The original ignored result used the mean planned request size for its two-call
diagnostic allowance and reported `$0.0958772`. The immutable amendment
`artifacts/aat-v1/terra-canary-amendment.json` replaces only that bound with
the maximum-request calculation above; it does not alter the ledger or any
Actor output.

## Outcome-readiness diagnostic

A second, independently hashed opportunity projection requires 15 complete
earlier TRAINING sessions before computing ATR14. It preserves the same frozen
15-minute close-breakout rule and contains no outcomes. On 3 September 2026 it
produced ten rows:

- compiler: `ORB_M_FIRST_CLOSE_BREAKOUT_V2_ATR14`;
- projection hash:
  `9d01a497285a2e8c890063a910800307fc974d320ba1f4c419cc4fef5788deae`;
- rows SHA-256:
  `d708495ae7916597bcb16c5adb8efa9ab301f67fbcd67ae5e747887250ae7552`.

The separate future-bar evaluator resolved all ten using adverse-first fills,
the frozen constitution and management defaults, and no deterioration signal.
It is therefore labeled
`ORB_M_FIRST_BREAKOUT_NO_DETERIORATION_DIAGNOSTIC_V1`, is never Actor-visible,
and is not adaptation evidence. Its result hash is
`8d1ca4ba7b81cccfb04ad52c6b0216d271b7ca73c1ffad4c798dd6fdd41f9df9`
and its rows SHA-256 is
`0c6f02f5399357eefea369546dd2ccbeeece6d7d1b120bb54b4d0c379c5570ea`.

The ten-row diagnostic happened to average approximately +0.20R. That is not
an edge, performance estimate, validation result, or basis for promotion. The
sample is tiny, selected from TRAINING, and omits the unbuilt deterioration
detector and full session/re-entry runner. Execution authority remains
`ABSENT`.

## Adaptation readiness gate

`audit_aat_v1_adaptation_readiness.py` verifies the registered protocol,
opportunity projection, outcome receipt, and their row hashes before evaluating
readiness. The command returns exit code 2 for durable negative knowledge and
cannot call an Actor or consume a holdout.

The real audit on 3 September 2026 returned
`BLOCKED_NEGATIVE_KNOWLEDGE`, report hash
`7b7cb7d5b2d4764f73e1229e3a2f3ad7f8c4efa6509c9109c3addfdbe89315d4`,
with seven blockers:

1. `gpt-5.6-terra` is an alias, not an immutable dated snapshot.
2. The registered `minimum_pairs` is 1; the hard floor is 300.
3. The current outcome-ready sample contains 10 opportunities, not 300.
4. The outcome evaluator is explicitly diagnostic-only.
5. Full session, re-entry, and deterioration semantics are absent.
6. The outcome receipt does not bind the registered scoring hash.
7. No hash-bound TRAINING lesson inventory exists.

Full repository validation after adding the gate: 169 tests passed. The audit
made no API request, consumed no sealed evidence, and left execution authority
`ABSENT`.

### 300-opportunity scale check

The first attempt to scale the V2 compiler correctly failed because one
selected session lacked a complete future bar sequence. V3 adds an explicit
complete-current-session requirement rather than silently emitting an
unresolved or data-exhausted result.

The corrected 300-row TRAINING run completed on 3 September 2026:

- compiler: `ORB_M_FIRST_CLOSE_BREAKOUT_V3_RESOLVED_ATR14`;
- opportunity projection hash:
  `ef8b572fe54ae95493692a8700f17af0e3e48e3a4f2d32c6c9dc49d1d49377ea`;
- opportunity rows SHA-256:
  `7b61627062ec3ac58e61e008fe5d4d631b29246c28ae639f16848296435c9e12`;
- resolved diagnostic outcomes: 300;
- outcome result hash:
  `dbf7b29ebb0ff7ed2336c05c759b05c0d5f6f8a03d1c219b8a35eff4ace73f91`;
- outcome rows SHA-256:
  `54cda402668121cfb0cb1360e36ef432f1abfa04531cbefb6651572357d92ebd`.

Readiness report
`ab7d2652372424fe54cfa0bb5c365ef738d91b28c2bda62b5531a838b707788b`
contains six blockers; `TRAINING_OPPORTUNITIES_BELOW_FLOOR` is no longer one
of them. These remain diagnostic TRAINING outcomes, not performance or
adaptation evidence. No Actor call or sealed-holdout access occurred, and
execution authority remains `ABSENT`.

## Six-blocker closure: TRAINING-only readiness

The six local blockers were closed on 3 September 2026 without consuming the
sealed holdout or granting execution authority. `FROZEN_FULL_ORB_M_EVALUATOR_V1`
walks the complete session, keeps both directions live, permits one qualified
re-entry per direction, and uses completed-bar deterioration signals. The
300-row run produced 688 evaluated episodes, including 313 re-entries across
277 source rows. Those counts describe evaluator coverage only; they are not
performance or adaptation claims.

- full-session outcome result hash:
  `f460f01e27ffe3adec2a4354df93b07de9354a830b4bc7fb491717cc5c06080e`;
- outcome rows SHA-256:
  `c62d9328d2d02a78e0d012e67835a629179536988128435c0c599fd31f83dab9`;
- scoring hash:
  `bcdcf129aaa0f9427cfa070364554c16e594a8c9bcd5d6bbba3de62de016be7c`;
- protocol amendment hash:
  `3d02c5ec67b921e40381ecc2693e9db73115398e708bbe22b704bac1541fabfa`;
- lesson inventory hash:
  `b1e287428b4ddfad5208c83a4e434c28757395ab2b3d524bcf6f432ecede317e`;
- readiness report hash:
  `526c8b1591e729a6bf45d7d36b94772ea8851d22105005d29bbbcf6257c9e4c4`;
- readiness status: `READY_TRAINING_ONLY_WITH_PROVIDER_MODEL_MUTABILITY`;
- local blockers: 0; promoted lessons: 0;
- full repository validation: 175 tests passed.

After merging the point-in-time universe completion branch on 4 September
2026, the combined repository passed Ruff and all 197 tests. The AAT receipt
hashes above did not change.

OpenAI exposes `gpt-5.6-terra` as a mutable provider alias and no dated Terra
snapshot was available for registration. The authorized substitute binds the
original Actor model, prompt, inference, and action-schema hashes plus the
actual transport-ledger SHA-256 in a local immutable amendment. The readiness
audit independently re-hashes that ledger. `PROVIDER_MODEL_MUTABILITY` remains
a permanent limitation and is not represented as solved.

At that checkpoint the lesson inventory was deliberately empty because no
promotion rule had been registered. Its hash-bound `NO_PROMOTED_LESSONS`
disposition required Arm D to receive empty memory. The scoring multipliers and
moderate re-entry threshold remain frozen V1 implementation decisions, not
author-confirmed or empirically calibrated parameters. Execution authority
remains `ABSENT`.

## TRAINING-only lesson promotion

On 4 September 2026, a deterministic rule was preregistered before inspecting
candidate-policy effects. It compares the frozen global PASS, reduced-size,
and high-conviction actions against ENTER_STANDARD on all 300 TRAINING
outcomes. Promotion requires at least 300 total observations, at least 100 LONG
and 100 SHORT observations, mean improvement of 0.01R, positive deterministic
95% bootstrap lower bounds overall and in both direction regimes, and no
drawdown regression above 0.1R. At most one eligible global action may be
promoted; any later TRAINING lower bound at or below zero or drawdown regression
requires revocation.

The registered rule produced one promoted TRAINING lesson: PASS rather than
ENTER_STANDARD for this registered opportunity population. PASS improved the
hypothetical action score by 0.06038R on average with a 0.04424R lower bound.
The direction strata were 169 LONG and 131 SHORT rows, with positive lower
bounds of 0.04404R and 0.02874R. Reduced sizing was eligible but rejected as
weaker than PASS. High-conviction sizing was rejected for negative effect,
uncertainty, regime contradiction, and drawdown regression.

These are in-sample TRAINING policy diagnostics, not trading-performance or
learned-adaptation claims. No Actor was called in this step, the earlier
empty-memory canary was not relabeled as an adaptation run, and the promoted
lesson has no execution authority.

- promotion rule hash:
  `49e9d73aa57f46018727a8c96d182be49f2f03cd9b67511b8c239d1ea4c4ef04`;
- lesson inventory hash:
  `9156aca7b76382a263cfa67a5fbca6bd61bf8e43710da320909c75121de2b2bc`;
- readiness report hash:
  `9ad899ded7b3c8864c5fb56a73e1390df813eb4c2c8b69bd58916a63bc58d7e6`;
- readiness: `READY_TRAINING_ONLY_WITH_PROVIDER_MODEL_MUTABILITY`, zero local
  blockers, one promoted TRAINING lesson;
- full repository validation: Ruff passed and 200 tests passed;
- sealed holdout consumed: false; execution authority: `ABSENT`.
