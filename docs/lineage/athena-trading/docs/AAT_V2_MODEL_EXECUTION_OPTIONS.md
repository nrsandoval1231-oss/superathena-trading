> **RESEARCH REFERENCE — product direction restored 24 September 2026.** This document retains its experiment/component history and restrictions. Its product-level next-step instructions are superseded by [Athena Trading Canon](ATHENA_TRADING_CANON.md) and [Build Plan](BUILD_PLAN.md). Read [Implementation Status](IMPLEMENTATION_STATUS.md) for current capability.

# AAT-V2 Model Execution Options

Status: local Ollama TRAINING plumbing is in-tree, and a **RunPod / remote-Ollama
path** now exists for Nick-directed TRAINING. The recommended next step is
the dual-Actor plan **7b volume + 14b gold** on the existing harness: a
stratified **1,000-opportunity** `qwen2.5:7b` volume sample plus a **100-
opportunity** overlapping `qwen2.5:14b` gold slice. The implied default of
a full **16,705-opportunity / 116,935-call overnight on one 14b GPU is no
longer the recommended next step** (measured Community 4090 `qwen2.5:14b`
smoke was ~35.4 s/call → ~48 days / ~$400). No full 116,935-call run has
been started in this repository. The registered protocol remains
`REGISTERED_NOT_AUTHORIZED` and `execution_authority` remains `ABSENT`.
DeepSeek Flash is a `CANDIDATE_PILOT` whose API is currently overloaded
(503). Desktop `qwen3.5:9b` remains a separate hashed local Actor. Astra
Desk stays isolated. V1/V2 holdout stays unused.

Do not start a live pod from CI or an agent. Do not authorize Terra.
Instructor / OpenAI-compat `/v1` toys are not this path.

## Workload

The full macro-only TRAINING plan contains 16,705 opportunities. Arm A is the
frozen deterministic control and makes no model calls. Arms B, C, and D make
one call per opportunity. Arm E has four deliberation turns per opportunity,
with 64 output tokens per turn so its total output allowance equals one 256
-token single call. Those E-arm turns now require a compact closed-enum JSON
object rather than the five-field Actor schema. The 4 x 64 = 256 output
ceiling is unchanged, so TRAINING spend is not raised.

The corrected workload is:

| Arm | Calls |
| --- | ---: |
| B — memoryless | 16,705 |
| C — naive memory | 16,705 |
| D — Athena memory | 16,705 |
| E — four-turn deliberation | 66,820 |
| **Total** | **116,935** |

The earlier dry-run estimate counted E as one call and reported 66,820 calls;
that number is superseded by the corrected total above.

The **documented volume plan** is not that full table. It is a stratified
1,000-opportunity subsample (7,000 calls with E, or 3,000 without) plus a
100-opportunity gold slice on 14b (700 calls with E). Commands are in
**7b volume + 14b gold** below.

## Recommended: 7b volume + 14b gold

Nick rejected the full 16,705-opportunity / 116,935-call overnight on one
14b GPU after a Community RTX 4090 `qwen2.5:14b` smoke of **~35.4 s/call**
(~48 days / ~$400 compute). A 20-opportunity / 140-call RunPod smoke passed
140/140 on 14b; that pod was terminated. The existing harness stays: native
Ollama `/api/chat`, the same Actor schema / arms / ledger / resume, hashed
identities, fail-closed authorization.

This section is the dual-Actor plan that replaces that implied default.

| Actor | Identity | Status | Default N | Arms | Authorize flag |
| --- | --- | --- | ---: | --- | --- |
| Volume | `configs/aat_v2_ollama_qwen_7b_volume_actor_identity_v1.json` (`qwen2.5:7b`) | `VOLUME_TRAINING_CANDIDATE` | 1,000 | full arms (B/C/D + E) first; thin-E optional | `--authorize-volume-training` |
| Gold | `configs/aat_v2_ollama_qwen_14b_runpod_actor_identity_v1.json` (`qwen2.5:14b`) | `RUNPOD_TRAINING_CANDIDATE` | 100, subset of volume | full arms including E | `--authorize-runpod-training` |

Neither flag authorizes Terra, desktop `qwen3.5:9b`, or the other Ollama
Actor. `execution_authority` stays `ABSENT`. Holdout stays unused. The
volume flag does **not** authorize the frozen 16,705-opportunity plan.

**E policy.** Volume may run full arms or thin-E (BCD only, `--no-include-deliberation`).
The default recommendation is **full arms for volume first**; thin-E is an
optional wall-clock lever on the same hashed 7b Actor, recorded on the
receipt as `include_deliberation: false`. Gold keeps E. Thin-E is not a
new identity and is not a protocol rewrite.

**Stratified subsample.** `configs/aat_v2_training_subsample_plan_v1.json`
pins seed `20260916`, symbol stratification, volume 1,000, gold 100, and
the frozen TRAINING `dataset_hash` `179e6f21…`. Opportunity IDs are drawn
offline from the frozen TRAINING index:

```
python scripts/draw_aat_v2_training_subsample.py \
  --opportunity-index <TRAINING opportunity JSONL> \
  --opportunity-receipt <receipt whose index_hash is 179e6f21…> \
  --output-dir artifacts/aat_v2_training_subsample
```

That writes `volume_1000.jsonl`, `gold_100.jsonl`, and hashed receipts.
Gold IDs are a subset of volume IDs. Holdout paths and holdout symbols fail
closed. Taking the first 1,000 JSONL rows is not this sample; the volume
runner requires the hashed receipt for the 1,000-opportunity plan.

### Wall-clock ballparks

**Measured (14b, not a hypothesis).** Community RTX 4090 `qwen2.5:14b` smoke:
~35.4 s/call. At RunPod Community ~$0.34/hr (pricing is dynamic):

| 14b workload | Calls | Hours at 35.4 s/call | Compute at $0.34/hr |
| --- | ---: | ---: | ---: |
| Gold 100, full arms | 700 | ~6.9 h | ~$2.30 |
| Full 16,705, full arms | 116,935 | ~1,150 h (~48 days) | ~$390 |

**Hypotheses (7b, unmeasured — do not treat as observed).** Same GPU, same
native `/api/chat`. Labelled hypotheses only:

| Hypothesis | Implied 7b s/call | Volume 1,000 full arms (7,000) | Volume 1,000 thin-E (3,000) |
| --- | ---: | ---: | ---: |
| A — ~2× 14b throughput | ~17.7 | ~34 h / ~$12 | ~15 h / ~$5 |
| B — ~3× 14b throughput | ~11.8 | ~23 h / ~$8 | ~10 h / ~$3 |
| C — conservative, same as 14b | 35.4 | ~69 h / ~$23 | ~30 h / ~$10 |

7b throughput is unknown until Nick runs the volume sample. These figures
exclude storage and setup. Compact E JSON still applies; a faster GPU does
not by itself fix E-arm schema misses.

### Bring-up checklist

No live pod is started from this repository. When Nick stands one up:

1. Start a Community RTX 4090 (or similar 24 GB) pod.
2. Install Ollama and pull the tags you will serve: `ollama pull qwen2.5:7b`
   for volume and `ollama pull qwen2.5:14b` for gold. A different tag is a
   different Actor.
3. Expose native Ollama on port 11434, **or** SSH-tunnel it to
   `http://127.0.0.1:11434`, **or** use the RunPod HTTPS proxy
   (`https://<id>-11434.proxy.runpod.net`) without appending `:11434`.
4. Draw the stratified subsample (offline; no GPU) with the command above.
5. Run volume 7b against the volume receipt (full arms first). Optional
   `--no-include-deliberation` only if wall-clock requires it.
6. Run gold 14b against the gold receipt, full arms including E.
7. Download `ledger.jsonl`, `checkpoint.json`, and `receipt.json` **before
   terminating the pod**. `--resume` replays the ledger.

The live transport always sends `User-Agent: athena-trading/0.1 ollama-training`.
RunPod's HTTPS proxy returns HTTP 403 for urllib's default `Python-urllib/3.x`.
Concurrency default is 1, max 4; Semaphore-64-style blasts are refused. Arm E
turns stay sequential inside each opportunity. OpenAI-compat `/v1` is refused.

### Exact volume commands (`qwen2.5:7b`)

Offline smoke (mocked transport; safe in this repo):

```
python scripts/run_aat_v2_ollama_local_training.py \
  --identity configs/aat_v2_ollama_qwen_7b_volume_actor_identity_v1.json \
  --authorization configs/aat_v2_ollama_volume_training_authorization_v1.json \
  --base-url http://<pod>:11434 \
  --output-dir artifacts/aat_v2_ollama_volume_7b_smoke
```

Live volume subsample (1,000 opportunities / 7,000 calls with E). Still ABSENT.
Terra stays `REGISTERED_NOT_AUTHORIZED`. Holdout untouched:

```
python scripts/run_aat_v2_ollama_local_training.py \
  --identity configs/aat_v2_ollama_qwen_7b_volume_actor_identity_v1.json \
  --authorization configs/aat_v2_ollama_volume_training_authorization_v1.json \
  --authorize-volume-training \
  --allow-live-ollama \
  --base-url http://<pod>:11434 \
  --opportunity-index <full frozen TRAINING JSONL> \
  --opportunity-receipt <matching frozen opportunity receipt> \
  --snapshot <macro snapshot JSONL> \
  --subsample-receipt artifacts/aat_v2_training_subsample/volume_1000.receipt.json \
  --output-dir artifacts/aat_v2_ollama_volume_7b
```

HTTPS proxy form (do **not** append `:11434`):

```
  --base-url https://<id>-11434.proxy.runpod.net
```

Optional thin-E (3,000 calls): same command plus `--no-include-deliberation`.

Resume after a hitch, same flags plus `--resume` and the same `--output-dir`.

Do not pass holdout paths. Do not use `--authorize-runpod-training` or
`--authorize-local-training` for this Actor. Do not run this in CI with
`--allow-live-ollama`.

### Exact gold commands (`qwen2.5:14b`)

Gold is the existing 14b RunPod identity on the **100-opportunity subset of
the volume sample**, full arms including E. It is not a new Actor.

```
python scripts/run_aat_v2_ollama_local_training.py \
  --identity configs/aat_v2_ollama_qwen_14b_runpod_actor_identity_v1.json \
  --authorization configs/aat_v2_ollama_runpod_training_authorization_v1.json \
  --authorize-runpod-training \
  --allow-live-ollama \
  --limit-opportunities 100 \
  --base-url http://<pod>:11434 \
  --opportunity-index <full frozen TRAINING JSONL> \
  --opportunity-receipt <matching frozen opportunity receipt> \
  --snapshot <macro snapshot JSONL> \
  --subsample-receipt artifacts/aat_v2_training_subsample/gold_100.receipt.json \
  --output-dir artifacts/aat_v2_ollama_gold_14b
```

Gold keeps `--include-deliberation` (the CLI default). Do not pass
`--no-include-deliberation` for gold. Do not use `--authorize-volume-training`
for this Actor. The frozen 16,705-opportunity 14b command remains in the
RunPod section below as plumbing; it is **not** the recommended next step.

## Observed local Qwen result

The installed local model is `qwen3-coder:30b` (approximately 19 GB). The
machine exposed approximately 33.8 GB RAM and an NVIDIA RTX 5060 with 8 GB
VRAM. Ollama allocated the model approximately 67% GPU / 33% CPU.

A 100-opportunity, 700-call pilot completed in 2,008.8 seconds:

- B/C/D: 300/300 responses accepted;
- E: 0/400 responses accepted;
- E failed because 64 tokens truncated the required five-field Actor JSON
  (`done_reason: length`);
- observed throughput: 0.348 calls/second;
- extrapolated full-run time: approximately 93.2 hours.

The local model was stopped after the pilot. Its ledger remains in disposable
ignored temp storage. That E configuration required unbounded
`horizon` / `invalidation` / `rationale` strings on every 64-token turn. A
non-authorizing compact-schema amendment now binds closed-enum E-arm turns
that fit the same 64-token budget. The registered protocol is not rewritten.
Tonight's local TRAINING runner uses that compact E schema on **`qwen3.5:9b`**,
a different hashed Actor from the 30b pilot tag. Re-benchmark accept rate
and wall-clock before treating the ~93h figure as current.

**Wall-clock warning.** The ~93 hour estimate is from `qwen3-coder:30b` at
0.348 calls/s. Nick bound `qwen3.5:9b` for tonight; that tag should be
faster on the same 8 GB GPU, but it is unmeasured. "Tonight" means *start*
tonight. A 2-opportunity live warmup (`14` calls) should precede the
overnight start so compact-E JSON and 9b throughput can be confirmed.

## DeepSeek V4.1 Flash API

DeepSeek's official pricing page identifies the API model as `deepseek-flash`.
At the time of measurement it listed:

- off-peak cache-miss input: $0.15 per million tokens;
- peak cache-miss input: $0.30 per million tokens;
- off-peak output: $0.60 per million tokens;
- peak output: $1.20 per million tokens.

Using the corrected workload and the repository's conservative input-size
proxy, the estimated full-run cost is approximately $32.68 off-peak or $65.35
peak. Actual billing depends on measured tokenization, cache behavior, retries,
and provider pricing changes.

DeepSeek source: <https://api-docs.deepseek.com/quick_start/pricing>

Changing from Terra to DeepSeek changes the Actor identity. DeepSeek Flash is
declared as its own provider-scoped candidate identity
(`configs/aat_v2_deepseek_flash_actor_identity_v1.json`, status
`CANDIDATE_PILOT`). It is not bound to the registered Terra protocol. A
bounded fixture pilot exists; that pilot is not TRAINING. Live spend for an
actual API run is separately unauthorized.

## RunPod-hosted Qwen

RunPod bills GPU compute by time; the official pricing page is dynamic. The
pricing observed during planning showed approximately $0.34/hour for a
Community RTX 4090 and approximately $0.74/hour for a Secure RTX 4090. RunPod
documents per-second compute billing and separate storage billing.

Sources:

- <https://www.runpod.io/pricing>
- <https://docs.runpod.io/pods/pricing>

A 24 GB RTX 4090 is a more suitable host for a 14b-class Qwen model than the
local 8 GB GPU. Actual throughput must be benchmarked on the selected image
and inference server. Illustrative compute-only costs for the
17,105,920-token output ceiling are:

| Measured output speed | Runtime | At $0.34/hr | At $0.74/hr |
| ---: | ---: | ---: | ---: |
| 50 tokens/sec | 95.0 hr | $32.31 | $70.32 |
| 100 tokens/sec | 47.5 hr | $16.16 | $35.16 |
| 200 tokens/sec | 23.8 hr | $8.08 | $17.58 |
| 500 tokens/sec | 9.5 hr | $3.23 | $7.03 |

These figures exclude storage and setup time. A faster GPU does not by itself
fix E-arm JSON truncation. The compact closed-enum schema in
`configs/aat_v2_e_arm_compact_schema_amendment_v1.json` is the E redesign:
worst-case valid turns fit the registered 64-token budget under the
conservative byte/4 proxy. It is a `NON_AUTHORIZING_PROTOCOL_NOTE`. It does
not raise TRAINING spend, does not rewrite the registered protocol, and does
not make E optional.

The RunPod path below is plumbing for Nick-directed remote Ollama TRAINING.
It is still `ABSENT`. It does not authorize Terra. Do not start the 116k run
from CI or an agent. Download `ledger.jsonl`, `checkpoint.json`, and
`receipt.json` before terminating the pod.

## DeepSeek Flash dry-run / preflight planner

`scripts/plan_aat_v2_deepseek_flash.py` turns the workload and prices in this
document into a fail-closed planning artifact. It is not TRAINING
authorization and it is not a provider switch.

- **Plan-only (default).** Reads `configs/aat_v2_training_plan_v2.json`, the
  frozen DeepSeek quote in `configs/deepseek_flash_pricing_2026-09-14.json`,
  and the registered V2 protocol. Emits off-peak / peak cache-miss estimates
  from the conservative input-byte proxy (~$32.68 / ~$65.35). No API key, no
  model call, no spend.
- **Fixture preflight (`--preflight`).** Requires `DEEPSEEK_API_KEY` and fails
  closed without it. Dry-runs at most seven calls (default three: arms B/C/D)
  against `configs/fixtures/deepseek_flash_preflight_v1.json`. Live HTTP is
  not implied; the CLI injects the fixture transport. The hard PREFLIGHT spend
  ceiling is $1.00 (Nick-authorized for preflight only; not TRAINING). CLI
  `--preflight` stays fixture/dry by default. Live library calls still need
  `allow_live=True` plus `DEEPSEEK_API_KEY`.
- **Structured Actor JSON.** Preflight payloads send `thinking: {type:
  disabled}` so Flash reasoning tokens cannot consume `max_tokens` and leave
  `content` empty. The system prompt requires exactly the Actor keys (`action`,
  `confidence`, `horizon`, `invalidation`, `rationale`) and legal actions
  (PASS / ENTER_REDUCED / ENTER_STANDARD / ENTER_HIGH_CONVICTION). Single-call
  preflight output is 512 tokens so complete JSON can land once thinking is
  off; the registered TRAINING protocol remains 256. `response_format:
  json_object` is set. Arm E does **not** reuse the five-field Actor schema
  on 64-token turns. Compact E-arm JSON is `turn` plus closed enums
  (`stance`/`claim` on BULL/BEAR/TRADER; scored `action` on RISK) with no
  free-text fields. Chat Completions cannot pin `json_schema`, so each E
  turn's system prompt includes an `EXAMPLE json OUTPUT` object. Fixture
  preflight `--include-deliberation` replays those compact turns from
  `configs/fixtures/deepseek_flash_preflight_v1.json` against
  `configs/aat_v2_e_arm_compact_schema_amendment_v1.json`. `execution_authority`
  stays `ABSENT`.
- **Hard refusals.** `execution_authority` stays `ABSENT`. The Terra protocol
  is consulted and not rewritten. DeepSeek Flash is a `CANDIDATE_PILOT`
  identity (`configs/aat_v2_deepseek_flash_actor_identity_v1.json`) and must
  not reuse the Terra identity. Holdout paths and the consumed AAT-V1
  registry are forbidden. The superseded 66,820-call v1 plan is refused.

Library entry points: `plan_deepseek_flash_dry_run` and
`run_deepseek_flash_preflight` in `src/athena_trading/aat_v2/deepseek_preflight.py`.
`allow_live=True` exists only as an explicit library opt-in on top of the same
tiny ceilings and still cannot flip authority or consume a holdout.

## DeepSeek Flash candidate identity and bounded pilot

Nick authorized a **bounded DeepSeek Flash pilot with a new provider-scoped
identity**. That is not TRAINING authorization and it does not freeze a new
claim contract.

The identity is declared in
`configs/aat_v2_deepseek_flash_actor_identity_v1.json`. Provider, model,
prompt, and inference are hashed separately from Terra. The five-field Actor
decision schema is shared (same `action_schema_hash`) because it is the arm
decision contract, not a vendor. Compact E turns bind `deliberation_hash`
from the non-authorizing amendment. V1 `registered_providers()` remains
`("openai",)`. The registered V2 protocol remains OpenAI / `gpt-5.6-terra`.

`scripts/run_aat_v2_deepseek_flash_pilot.py` is the fail-closed entrypoint.
The library function is `run_deepseek_flash_pilot` in
`src/athena_trading/aat_v2/deepseek_pilot.py`. Receipts carry
`PILOT_NOT_TRAINING` and `execution_authority: ABSENT`.

- **CLI default.** Fixture / dry. One synthetic opportunity, B/C/D Actor JSON
  plus four compact E turns (7 calls), `$1.00` invocation cap. Requires
  `DEEPSEEK_API_KEY` even for the fixture so a missing credential fails
  closed. Does not open a network transport.
- **Live.** Requires `--allow-live`, `DEEPSEEK_API_KEY`, and explicit
  `--call-ceiling` plus `--spend-ceiling-usd`. Hard caps fail closed above
  80 opportunities, 500 calls, or `$50.00`. CI must not pass `--allow-live`.
- **Payload rules.** Thinking disabled. B/C/D use the Actor JSON schema at
  512 output tokens. E uses compact closed-enum turns at 64 tokens with a
  per-turn `EXAMPLE json OUTPUT` in the system prompt. Chat Completions
  `response_format` stays `json_object` (`json_schema` is unavailable and
  would 400). Do not reintroduce five-field Actor JSON on E. Rejected
  records persist `raw_content_snippet` (512 characters) so a live miss is
  diagnosable offline.

### Nick-authorized bigger live knobs (not TRAINING)

Nick authorized a **bigger live pilot** at **about 500 calls** and
**$50.00 USD**. That is still not TRAINING, not a holdout sample, and not
a protocol switch. Dry CLI defaults stay small (1 opportunity / 7 calls /
`$1.00`). A live run still needs `--allow-live`, `DEEPSEEK_API_KEY`, and
explicit ceilings.

Math: B/C/D Actor JSON plus four compact E turns is **7 calls per
opportunity**. `71 × 7 = 497` calls, under the 500-call hard cap. The
opportunity hard cap is **80** so 71 is legal and TRAINING-sized N
(16,705) is still refused.

| Knob | Dry default | Nick-authorized bigger live | Hard ceiling |
| --- | ---: | ---: | ---: |
| Opportunity sample | 1 | 71 (71 × 7 = 497 with E) | 80 |
| Call ceiling | 7 | 500 | 500 |
| Spend ceiling (USD) | 1.00 | 50.00 | 50.00 |

Peak cache-miss worst case for the 71-opportunity / 497-call shape is
expected well under $50 given Flash prices and the conservative byte/4
input proxy. A TRAINING-sized ceiling is refused. The earlier first live
sample (7 opportunities / 49 calls / $5) remains historical, not the
current recommended live defaults.

### Live Flash pilot result (2026-09-14, not TRAINING)

Nick ran:

```
python scripts/run_aat_v2_deepseek_flash_pilot.py --allow-live --opportunities 7 --call-ceiling 50 --spend-ceiling-usd 5.00
```

That first sample used the old $5 / 50-call caps. Current Nick-authorized
bigger-pilot command is in Decision boundary below.

Receipt: `PILOT_NOT_TRAINING`, `execution_authority` `ABSENT`, holdout
untouched, cost about `$0.010`. B/C/D accepted **21/21**. E accepted
**3/28** (`24` `deliberation output schema mismatch`, `1` `OUTPUT_TRUNCATED`).
The three accepts were compact RISK `{action, confidence, turn}` and TRADER
`{claim, confidence, stance, turn}`. Many mismatch rows had output-token
counts well under 64, so the dominant failure was extra keys / wrong enums /
Actor-shaped payloads, not compact overflow. The 64-token E budget is kept:
raising it would break the equal-budget story (4 × 64 = 256). The one
truncation is treated as extra-key verbosity hitting the cap. This harden
adds per-turn example json, keeps the parser fail-closed, and stores a raw
snippet on rejected records. It is not TRAINING authorization.

## Local Ollama TRAINING (tonight's path)

Nick authorized a pivot after DeepSeek 503s blocked the bigger Flash sample.
This is **local in-sample TRAINING plumbing** on his desktop, not a Terra
protocol rewrite, not broker authority, and not holdout consumption.

Identity: `configs/aat_v2_ollama_qwen_actor_identity_v1.json`
(`LOCAL_TRAINING_CANDIDATE`). Provider `ollama`, default model
`qwen3.5:9b` (Nick bound this tag; the earlier local-pilot tag
`qwen3-coder:30b` is a different Actor). Configurable only by minting a new
hashed identity file; `--model-id` must match. The Terra protocol is
consulted and not reused. DeepSeek Flash is a different Actor.

Authorization: `configs/aat_v2_ollama_local_training_authorization_v1.json`.
It records Nick's direction and still requires `--authorize-local-training`.
`execution_authorized` on that artifact stays `false` so CI and agents cannot
silently start 116k calls. `execution_authority` stays `ABSENT`.

Transport: `http://127.0.0.1:11434/api/chat` only for this 9b identity
(loopback HTTP, including an SSH tunnel *to a 9b desktop process*). Thinking
disabled (`think: false`). `format: json`. B/C/D use the five-field Actor
schema at the registered **256** tokens. E uses the compact closed-enum
parser at **64** tokens with per-turn example json. Timeouts default to 180s
with three retries on local GPU hitch (408/429/5xx/connection). Non-loopback
hosts are refused for `qwen3.5:9b`; use the RunPod 14b identity for a pod IP.

**Token accounting.** Local GPU time is unpriced
(`configs/ollama_local_unpriced_v1.json`). When Ollama returns
`prompt_eval_count` / `eval_count`, rows are `OLLAMA_REPORTED`. When those
fields are missing, the runner records utf-8 bytes/4 as
`BYTE_PROXY_ESTIMATE` and says so on the receipt. Estimates are not vendor
billing.

Runner: `scripts/run_aat_v2_ollama_local_training.py`. Library:
`run_ollama_local_training` in `src/athena_trading/aat_v2/ollama_training.py`.
It reads `configs/aat_v2_training_plan_v2.json` and a TRAINING-only
opportunity index / macro snapshot (not the DeepSeek synthetic chat fixture).
Holdout paths and holdout symbols fail closed. Durable ledger / checkpoint /
receipt land under `--output-dir` (gitignored `artifacts/`). `--resume`
replays the JSONL ledger and continues. Status is
`LOCAL_TRAINING_SMOKE` (default) or `LOCAL_TRAINING_IN_SAMPLE` (Nick's flag).

V2 has no promoted lesson inventory yet. C/D/E packets carry empty memory.
The treatment remains the exogenous macro vector.

### Exact commands

Offline smoke (default; mocked Ollama; 1 opportunity / 7 calls):

```
python scripts/run_aat_v2_ollama_local_training.py
```

Live warmup on Nick's desktop (compact E re-benchmark; 2 opportunities / 14
calls). Point at the frozen TRAINING JSONL, not holdout:

```
python scripts/run_aat_v2_ollama_local_training.py \
  --allow-live-ollama \
  --limit-opportunities 2 \
  --opportunity-index <TRAINING opportunity JSONL> \
  --snapshot <macro snapshot JSONL> \
  --output-dir artifacts/aat_v2_ollama_local_training_warmup
```

Overnight full in-sample start (16,705 opportunities / 116,935 calls) remains
plumbing for the desktop 9b Actor. It is **not** the recommended next step;
see **7b volume + 14b gold** above. Prior local estimate ~93h:

```
python scripts/run_aat_v2_ollama_local_training.py \
  --authorize-local-training \
  --allow-live-ollama \
  --opportunity-index <TRAINING opportunity JSONL> \
  --snapshot <macro snapshot JSONL> \
  --opportunity-receipt <receipt whose index_hash is 179e6f21…> \
  --snapshot-receipt <receipt whose snapshot_hash is 3240a4fa…> \
  --output-dir artifacts/aat_v2_ollama_local_training
```

Resume after a hitch, same flags plus `--resume` and the same `--output-dir`.

Do not pass holdout paths. Do not omit `--authorize-local-training` for the
full desktop plan. Do not run this in CI with `--allow-live-ollama`.

## RunPod / remote Ollama TRAINING (`qwen2.5:14b`)

Nick authorized a **separate** remote-Ollama TRAINING path. This is not the
desktop 9b Actor, not Terra, not DeepSeek, and not a toy Instructor
name/role script. The real TRAINING index, snapshot, and receipt hash gates
still apply (`dataset_hash` `179e6f21…`, `snapshot_hash` `3240a4fa…`).

**Why `qwen2.5:14b` rather than `qwen3:14b`.** The committed RunPod tag is
`qwen2.5:14b`. It is the widely available 14b-class Ollama model that fits a
Community RTX 4090 (~Q4, well under 24 GB), and the string cannot be mistaken
for a runtime swap of desktop `qwen3.5:9b`. `qwen3:14b` would sit next to
`qwen3.5:9b` as if it were a typo, and it is a different generation from
Qwen 3.5 anyway. A different tag is a different hashed Actor: `--model-id`
must match `configs/aat_v2_ollama_qwen_14b_runpod_actor_identity_v1.json`.

Identity: `configs/aat_v2_ollama_qwen_14b_runpod_actor_identity_v1.json`
(`RUNPOD_TRAINING_CANDIDATE`). Provider `ollama`. Host is **not** an Actor
axis (`base_url_policy: explicit_cli`); the pod IP or SSH tunnel is a runtime
`--base-url`. Swapping to `qwen3.5:9b` or `qwen3:14b` without minting a
matching identity fails closed.

Authorization: `configs/aat_v2_ollama_runpod_training_authorization_v1.json`.
Full plan requires `--authorize-runpod-training`. That flag does **not**
authorize Terra and does **not** authorize desktop `qwen3.5:9b`.
`--authorize-local-training` does not authorize this 14b Actor.
`execution_authority` stays `ABSENT`.

Transport: native Ollama `/api/chat` (the same payload the desktop runner
already uses). OpenAI-compat `/v1/chat/completions` is refused so a toy
Instructor schema cannot sneak in. Live still needs `--allow-live-ollama`.
`--base-url` is the remote opt-in. Direct Ollama on the pod is
`http://<pod>:11434`. A RunPod HTTPS proxy
(`https://<id>-11434.proxy.runpod.net`) should be passed as that HTTPS
origin **without** appending `:11434` — the proxy terminates TLS on 443,
and the transport must not rewrite a port-less HTTPS URL onto Ollama's
native 11434. Explicit `:443` also works. An SSH tunnel to loopback is
also legal for this identity.

The live transport always sends a deliberate `User-Agent`
(`athena-trading/0.1 ollama-training`). RunPod's HTTPS proxy returns HTTP
403 for urllib's default `Python-urllib/3.x` (curl, `python-requests`,
Mozilla, and PowerShell `Invoke-WebRequest` succeed on the same origin).
Do not drop the custom UA or live warmup fail-closes with HTTP 403.

**Concurrency.** Default `--max-concurrent-calls 1`. Optional 2–4 is
opportunity-level only; arm E turns stay sequential inside each row. Ollama
on one GPU serializes inference. Semaphore-64-style blasts are refused.

**Durable artifacts.** Prefer the chunked `ledger.jsonl` over one giant JSON
dump. `--resume` replays the ledger. Download `ledger.jsonl`,
`checkpoint.json`, and `receipt.json` **before terminating the pod**.

### RunPod bring-up checklist

1. Start a Community RTX 4090 (or similar 24 GB) pod.
2. Install Ollama on the pod and pull the committed tag: `ollama pull qwen2.5:14b`.
3. Expose native Ollama on port 11434, **or** SSH-tunnel it to
   `http://127.0.0.1:11434` on the machine that runs the harness, **or**
   use the RunPod HTTPS proxy (`https://<id>-11434.proxy.runpod.net`)
   without appending `:11434`.
4. Confirm `qwen2.5:14b` is the serving tag. A different tag is a different Actor.
5. Point the existing runner at `--base-url http://<pod>:11434`, the HTTPS
   proxy origin, or the tunnel, with the 14b identity. Do not reuse the
   desktop 9b identity file.
6. Offline smoke (mocked transport; safe in this repo):

```
python scripts/run_aat_v2_ollama_local_training.py \
  --identity configs/aat_v2_ollama_qwen_14b_runpod_actor_identity_v1.json \
  --authorization configs/aat_v2_ollama_runpod_training_authorization_v1.json \
  --base-url http://<pod>:11434 \
  --output-dir artifacts/aat_v2_ollama_runpod_training_smoke
```

7. For 14b, the recommended live run is the **100-opportunity gold slice**
   (subset of the 7b volume sample), full arms including E. Exact gold
   command is in **7b volume + 14b gold** above. Do not start the 116k run
   from an agent. The frozen 16,705 command below is plumbing, not the
   recommended next step.

### Exact RunPod commands

Live warmup (2 opportunities / 14 calls):

```
python scripts/run_aat_v2_ollama_local_training.py \
  --identity configs/aat_v2_ollama_qwen_14b_runpod_actor_identity_v1.json \
  --authorization configs/aat_v2_ollama_runpod_training_authorization_v1.json \
  --allow-live-ollama \
  --limit-opportunities 2 \
  --base-url http://<pod>:11434 \
  --opportunity-index <TRAINING opportunity JSONL> \
  --snapshot <macro snapshot JSONL> \
  --output-dir artifacts/aat_v2_ollama_runpod_training_warmup
```

HTTPS RunPod proxy form (recommended; do **not** append `:11434`):

```
  --base-url https://<id>-11434.proxy.runpod.net
```

`--base-url https://<id>-11434.proxy.runpod.net:443` is equivalent. Direct
pod Ollama without the HTTPS proxy remains `--base-url http://<pod>:11434`.

Optional 100-opportunity live sample (700 calls). Prefer the hashed gold
subsample receipt from `draw_aat_v2_training_subsample.py` so this 100 is
the overlapping gold slice, not the first 100 JSONL rows:

```
python scripts/run_aat_v2_ollama_local_training.py \
  --identity configs/aat_v2_ollama_qwen_14b_runpod_actor_identity_v1.json \
  --authorization configs/aat_v2_ollama_runpod_training_authorization_v1.json \
  --allow-live-ollama \
  --limit-opportunities 100 \
  --base-url http://<pod>:11434 \
  --opportunity-index <TRAINING opportunity JSONL> \
  --snapshot <macro snapshot JSONL> \
  --output-dir artifacts/aat_v2_ollama_runpod_training_100
```

Full in-sample TRAINING (16,705 opportunities / 116,935 calls) remains
plumbing. It is **not** the recommended next step (measured ~48 days / ~$400
on Community 4090 14b). Still ABSENT. Terra stays
`REGISTERED_NOT_AUTHORIZED`. Holdout untouched:

```
python scripts/run_aat_v2_ollama_local_training.py \
  --identity configs/aat_v2_ollama_qwen_14b_runpod_actor_identity_v1.json \
  --authorization configs/aat_v2_ollama_runpod_training_authorization_v1.json \
  --authorize-runpod-training \
  --allow-live-ollama \
  --base-url http://<pod>:11434 \
  --opportunity-index <TRAINING opportunity JSONL> \
  --snapshot <macro snapshot JSONL> \
  --opportunity-receipt <receipt whose index_hash is 179e6f21…> \
  --snapshot-receipt <receipt whose snapshot_hash is 3240a4fa…> \
  --output-dir artifacts/aat_v2_ollama_runpod_training
```

Resume after a hitch, same flags plus `--resume` and the same `--output-dir`.
Optional `--max-concurrent-calls 2` (max 4) after the warmup proves the GPU
is not swapping. Leave the default at 1 if unsure.

Do not pass holdout paths. Do not use `--authorize-local-training` for this
Actor. Do not run this in CI with `--allow-live-ollama`. Do not terminate the
pod before copying the ledger.

## Decision boundary

The recommended TRAINING plan is **7b volume (1,000) + 14b gold (100)** on
the existing Ollama harness. Desktop `qwen3.5:9b` and the frozen 16,705 /
116,935 plumbing remain in-tree and still ABSENT. None of these paths flip
the registered Terra protocol to authorized, grant broker
`execution_authority`, or consume V1 or V2 holdout. DeepSeek Flash remains a
bounded candidate whose API is overloaded; the bigger live command (not
TRAINING) is still:

```
python scripts/run_aat_v2_deepseek_flash_pilot.py --allow-live --opportunities 71 --call-ceiling 500 --spend-ceiling-usd 50.00
```

Do not treat a 503 as a reason to rewrite Terra. Arm E stays at the
registered 4 x 64 compact budget. Volume may omit E via
`--no-include-deliberation`; gold keeps E. Astra Desk stays isolated.
Holdout stays unused. RunPod plumbing does not by itself start the 116k run.
