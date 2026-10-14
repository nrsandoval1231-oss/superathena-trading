# Implementation status

## Current architecture and implementation — 13 October 2026

**Target approved by Nick:** Astra 6 is the generative LLM for source-linked interpretation and structured theses/scenarios/plans; Jev is the bounded judge of underlying evidence plus proposal; deterministic code owns numbers, validated forecasts, freshness, sizing, shared portfolio risk, execution and APDE transitions. Critical protection and exits must not wait for either model. This supersedes Jev-only product direction, not the evidence of what earlier revisions implemented. See [canon v4.0](ATHENA_TRADING_CANON.md), [hybrid contract and diagram acceptance map](HYBRID_MODEL_CONTRACT.md) and [build plan](BUILD_PLAN.md).

**What this branch implements:** the intraday path is still the Jev-only ORB paper runner from main `5708946616afb675d1c78138990d8fa46057b6d5`. It also contains the Jev-only earnings book from PR #29 and, on this dependent branch, a partial shared gate, a fresh-bar fallback, and offline evaluation machinery. Astra 6 is not integrated. Its provider deployment, API model ID, account access and interface are unverified, and no substitute or deployment identifier is selected. This branch does not deploy, change credentials, or grant LIVE authority. Nick confirmed no overnight positions; both arms pursue same-session exits and preserve unresolved exposure for recovery.

| Capability | Verified repository scope / remaining work |
|---|---|
| Main entry path | Narrow ORB candidate → Jev-only judgment → deterministic pilot risk → Alpaca paper bracket/recovery; Astra 6 and hybrid entry are not implemented |
| Operational evidence | The 13 October held-bracket incident below records a first filled bracket and protective flatten. Earlier no-traded-session statements are historical. Current deployed host SHA, health and exposure were not checked by this repair |
| Earnings | The PR #29 dependency implements a narrow Jev-only paper book, not source intelligence or thesis/scenario generation. Lifecycle and no-overnight repair, including final durability follow-up `daedc2f5849d8468f1a002bd5f34b58b6e45c68c`, is described below. It is not merged and not deployed |
| Holding policy | Nick explicitly confirmed no overnight positions on 13 October 2026. New earnings brackets use DAY and begin closing 15 minutes before the actual session close, including early closes. Old journals remain recoverable; unknown or unexecuted exits stay visible and block new entries |
| Shared gate and evaluation | Account-coordinated durable symbol/buying-power reservations, read-only verified peer journals, fresh-bar fallback and offline comparison machinery. Not the complete hybrid portfolio gate or a performance result |
| Forecasting / APDE / portfolio risk | Comprehensive validated forecasts, full shared EXPLORE/PROTECT/HARVEST/DEFEND/EXIT management, hybrid management and complete cross-arm portfolio controls remain incomplete |
| Learning / Core | Current trading-specific outcome store, retrieval and prospective temporary veto study exist; general Core context/replay/validation/knowledge integration and measured performance improvement are not established |
| Authority | PAPER/ABSENT only; LIVE remains rejected. Aggressive valid opportunity capture and adaptive winners do not raise risk caps or grant overnight permission |

## Atomic shared-account reservations — 13 October 2026

Tested combined runtime and tests: `07fd623562931b2874d2957d143da9143a837e38`, tree `5382cfb1d5bb9c5f10b96d87957d7b92652c6c2c`. This stack retains PR #29 lifecycle, no-overnight and outcome-durability repair `daedc2f5849d8468f1a002bd5f34b58b6e45c68c` as an ancestor. The following documentation-only merge preserves those tested runtime/test blobs and records the final evidence.

| Review finding / safety invariant | Repair and observed synthetic proof |
|---|---|
| Concurrent check/reserve and same-symbol race | Both real entry methods acquire one account-specific nonblocking mutex before fresh reads, risk checks and durable intent. Separate spawned processes exercise both first-arm orderings and same/different symbols; at most one submits. A retry after the first process exits still sees the durable reservation |
| Crash-safe reservation | Process death after the SQLite intent commit, before or after the checkpoint, releases only the mutex. Restart retains capacity and symbol exclusion; no uncertain order is resent |
| Mixed-time buying-power evidence | `LivePaperAPI.snapshot` reads positions/orders before account. An acknowledged order cannot exempt its cost from a balance sampled earlier. The original insertion-between-account-and-orders scenario blocks; coherent reflected orders still avoid double charging |
| Pending/partial GTC and day transition | Working quantity includes unfilled shares plus held residual. `done_for_day` is nonterminal, including legacy GTC state across restart/day change. Genuine terminal cancellation releases only unfilled quantity; prior-session unresolved intraday journals stay in the peer view |
| Peer recovery integrity | Read-only SQLite snapshots validate both hash chain and durable checkpoint. Clean-prefix truncation, missing/mismatched anchors and a missing DB with surviving anchor fail closed; the one-row commit/checkpoint crash window remains recoverable |
| Service isolation and configuration | Both units add only `/var/lib/athena-risk` for shared write access, with existing own-directory write boundaries and `ProtectSystem=strict` intact. Required absolute `ATHENA_SHARED_RISK_DIR` is durably bound to account/path. Missing/unusable/mismatched coordination blocks entry. Unprivileged tests read mode-0555 peer directories and mode-0444 files without modifying them |
| Model-independent protection and no overnight authority | Both actual session-exit paths progress while another entry holds the mutex and no model is available. Both arms reject overnight proposals; accepted authority is `flat-by-close`. New DAY reservations are not described as overnight exposure. Legacy GTC risk remains recovery data |

Observed exact-tree local checks used Python 3.12.14 under `env -i`, temporary state and a socket-denial guard. All broker/provider transports were synthetic:

```bash
python -m pytest -q                                      # 871 passed in 10.93s
python -m ruff check .                                   # clean, 0.15.8
bash -n deploy/install.sh                                 # clean
python -m compileall -q src tests                         # clean
git diff --check                                          # clean
python -m pip wheel --no-index --no-deps --no-build-isolation .
# isolated wheel install and shared_risk/live/earnings/ownership imports passed
```

No configured type checker exists. Root pytest excludes the separately extracted Astra Desk suite. Protected `research`, `configs` and `data` paths are unchanged from PR #31 head `5d0c5bb57f54b4ff82575314451a2d947346e30e`. Permission checks did not launch real systemd units. This is single-host file coordination and requires both services to use the reviewed code, the same shared path and the actual peer journals; it is not distributed coordination or proof of deployment, broker executions, account health or trading performance. See [operator setup and recovery constraints](CLOUD_DEPLOYMENT.md#shared-account-entry-coordination).

Comprehensive portfolio correlation/concentration/loss/drawdown thresholds and hybrid model integration remain incomplete. This repair does not claim complete opportunity attribution: POST-rejected/no-entry and fill-racing-timeout funnel coverage remain separate follow-ups. PAPER/ABSENT authority, existing risk caps and frozen evidence are unchanged. No service was activated, broker/provider called, credential changed or real-money order authorized.

## Shared risk, fresh-bar fallback, and evaluation machinery

The earnings review fixes stay on `cursor/earnings-adaptive-paper-a4c7`. This change does not reset that work. It adds the account gate, the opportunity funnel, and an offline comparison that does not read consumed holdouts.

**Implemented and covered by fixtures.** A remembered intraday TAKE_TRADE is submitted at the cutoff only when the fresh completed bar is still that setup. Setup identity is direction, opening range, price, and stop. A later minute of that same setup is not `SETUP_CHANGED`. A stale bar records `fallback_no_trade` and does not send the old order. A fresh bar in the other direction does not send the old order. Equivalent repeats of one opening-range setup use one reassessment and do not consume the 20-setup budget. `paper/shared_risk.py` refuses a second reservation of the same symbol, an overnight proposal from either arm, and combined notional above buying power. The account is sampled after positions and orders under the entry coordinator. Acknowledged exposure seen before that buying-power sample is not charged again; unreflected reservations still count. A working entry reserves its unfilled quantity plus shares still held. A terminal order releases the unfilled remainder. Malformed fill evidence fails closed. Each arm reads the other book without taking its writer lock, including when that directory is readable and not writable. An unreadable snapshot fails closed. `paper/evaluation.py` fills at the next open. A gap through the stop is an observed adverse move. A configured stop is a labeled bound, not an observed touch, when no price path is present. Drawdown follows time. Uncertainty resamples the same opportunity population as expectancy, with abstentions as zero returns and skipped sessions retained, and reports paired session differences. `compare_policies` reports deterministic, Jev without memory, and Jev with memory. Its performance field is `unverified`. An entry that times out and ends canceled with zero fills records one unfilled funnel outcome, including after restart. The research ORB-M re-entry scan continues after an excluded retracement. Earnings headlines that are a split, dividend, or distribution stay `news=unconfirmed`.

**Deployment boundary.** Nothing here was deployed. The current host revision, service state and exposure were not checked by this repair; dated operational observations below are historical.

**Empirically supported.** Not this change. The 13 October paper fill, flattened seconds later with `PROTECTION_MISSING`, is one observed broker event and the reason the held-stop check exists. It is not an edge. The 4–12% earnings screen remains a watchlist heuristic. Jev action probability is not a calibrated probability of profit. Fresh market data for the three-way comparison was not available, so the machinery runs on supplied opportunities and does not claim a result. Consumed holdouts and INVALID_EVIDENCE artifacts were not read or rewritten.

**Inactive until the owner sets a number.** Correlation, concentration, weekly loss, monthly loss, portfolio drawdown, and overnight stress. Neither arm has overnight entry authority. Legacy GTC reservations remain visible until genuine terminal reconciliation; retaining that risk is not permission to renew the hold. Live PROTECT, HARVEST, and DEFEND ratchets stay off the one-share pilot. Research `ManagementParameters` still drive only the ORB-M simulator. There is no earnings promotion protocol.

### Strategy contract

| Capability | Execution path | What a test shows | Standing |
|---|---|---|---|
| Intraday one-share ORB bracket, 2R, day order | `paper/live.py` | Active paper fixtures submit qty 1 and flatten the pilot's own symbol | Implemented. One broker fill observed and flattened. Not an edge |
| ORB-M qualification, trail, controlled re-entry | `orb_m/session.py` | An excluded retracement does not stop a later valid reset | Research simulator. Not the live order path |
| Earnings 4–12% screen | `plan_entry` | An out-of-band bar is temporary; a later in-band bar can be judged | Watchlist heuristic. Not a continuation result |
| Earnings post-entry bracket | DAY stop at half the gap, 2R, same-session exit | Long and short follow the sign of the gap under the same caps | Implemented paper rule. Not measured by side |
| Shared account gate | `paper/shared_risk.py` | Atomic symbol/capacity reservation, ordered buying-power sampling, working quantity, verified read-only peer book | Active for those checks. Portfolio numbers inactive |
| Fresh-evidence comparison | `paper/evaluation.py` | Next-open fill, observed excursion, common-session uncertainty | Machinery only. Performance unverified |
| Learning | `paper/learning.py` | Nested legs reconcile; fallback and earnings stay out of the intraday study | Intraday study implemented. Earnings stored, not promoted |

`LIVE` still raises. Approved dollar caps are unchanged.

Earlier shared-risk/fallback repair receipt (not the atomic repair above), Python 3.12. The pre-repair count on `ba032129b7900cafec2535fde0db902eae715b36` was 785 passed. That count did not include these review repairs. No pre-existing failures were present. Root pytest does not include `research/astra-desk/tests`.

```bash
python3 -m pytest -q                # 807 passed in 6.24s
python3 -m ruff check .             # clean, ruff 0.15.8
bash -n deploy/install.sh           # clean
git diff --check                    # clean
python3 -m pip install .            # imports shared_risk, evaluation, funnel, live, and earnings
```

No type checker is configured in `pyproject.toml` or `.github/workflows/ci.yml`. Tested revision of this repair: `19402ce3d100a5a28a83f3c23dadc2b17164aa5d`. The 785-passed result on `ba032129b7900cafec2535fde0db902eae715b36` is historical and is not this repair.

GitHub Actions on `ba032129b7900cafec2535fde0db902eae715b36` did not run the test job. Push run `38448610766` and pull-request run `38448676036` both failed in a few seconds with empty steps. The annotation says the job was not started because recent account payments have failed or the spending limit needs to be increased. That is a billing block, not a pytest or ruff failure. Later empty commits retriggered CI after the repository was public. Those runs are not a substitute for this repair.

Actions on `253900e0d51bba64aa6b697c1d364b42cfe63a06` did start. Ruff passed. Pytest failed three subprocess tests (`38461815469` push, `38461823625` pull request) because those tests set the child working directory to `/workspace`. That path is this checkout, not the Actions workspace. The child now uses the repository root. Local recheck after that path fix: `python3 -m pytest -q` passed 807 tests in 7.06s. Root pytest still does not include `research/astra-desk/tests`.

## Earnings close ownership and same-session policy — 13 October 2026

Tested runtime revision: `cdbf8b9b5223255803d33e142593f6d5a77f112b`, on prior PR #29 head `dd71add0170a03b7c9da92a31c31bbe49b2c732c`. The owner confirmed no overnight positions at 21:41 UTC. This resolves the earlier holding-policy conflict without granting deployment, provider calls, spending or LIVE authority.

| Finding / requirement | Implemented behavior and regression evidence |
|---|---|
| Unrelated close adoption / unowned residual | Match opposite side, exact requested quantity, non-reserved ID and creation/submission timing to the durable intent. Retry requires exact signed residual explained by owned fills. Quantity-bounded DELETE prevents a concurrent addition from expanding the close request. Fractional, opposite-side and unexplained shares halt rather than being liquidated |
| Historical earnings ownership | Account-bound exact entry, leg and close identities are rebuilt from the durable journal independently of active symbols. They remain after closure/restart. Intraday terminal learning no longer hides a manual order solely because its symbol is in the active earnings ledger |
| Terminal-before-restart lost acknowledgement | Search bounded complete terminal history and working observations, deduplicate consistent identities, reject conflicting/truncated/ambiguous evidence. A missing match remains visibly unresolved; no duplicate close or fabricated fill |
| Partial and terminal-zero attempts | Refresh working partial acknowledgements, validate immutable order identity, accept verified terminal zero-fill cancellations/rejections/expirations and aggregate later fills. Every attempt must be terminal before retry or publication |
| No overnight positions | DAY entry brackets; 15-minute pre-close exit using actual regular-session calendar and early closes; pending-entry cancellation and prior-day recovery without models. Default hold is one session; legacy 2..5 settings are readable for recovery but block new entries |
| Execution limitations | A market halt, outage or closed session can prevent flatness. `EXIT_UNRESOLVED`, `FLATTENING` and `POSITION_MISMATCH` remain visible and block new entries. Cancellation or acknowledgement alone is not a confirmed close |

Regression-first verification: all eight independently reported adverse cases failed on the starting head. Thirty-six new in-repository sequence cases cover those invariants and the subsequent same-session policy. Fixture updates supply actual broker-shaped timestamps, unique per-symbol IDs and signed short-close behavior; the old multiday expectations were replaced by the owner's new policy. Existing research, model-role boundaries, risk caps and broker pin were preserved.

Observed local checks used Python 3.12.14 with an empty inherited environment, temporary journals/learning stores and a Python socket-denial audit hook. No real broker/provider was called:

```bash
python -m pytest -p no:cacheprovider -q                 # 814 passed in 7.80s
python -m ruff check .                                 # clean, 0.15.8
bash -n deploy/install.sh                               # clean
git diff --check                                        # clean
python -m pip install --no-index --no-deps --no-build-isolation --target <isolated-package-dir> .
# local wheel built/installed; installed-package earnings/ownership imports passed
```

Final durability follow-up: `daedc2f5849d8468f1a002bd5f34b58b6e45c68c` also closes the verified event-publication crash window. The reconciled earnings receipt is persisted before `position_closed`, missing events are idempotently recovered, and old journals already containing `position_closed` without a receipt remain in recovery. Missing terminal fill evidence stays `FLATTENING` and never silently completes the episode. Six further tests cover crashes immediately before/after both durable appends, the legacy reversed-order state, and unavailable recovery evidence. Three new assertions reproduced failures before the fix; two append-boundary controls already passed. Final full suite: **820 passed in 7.39s**; Ruff, installer syntax, diff checks and fresh local package build/install/import all passed with the same empty-environment network guard. The total addition is 42 in-repository tests. This follow-up does not change authority, risk, strategy selection or deployment.

The close quantity parameter and bounded history query follow Alpaca's [close-position schema](https://docs.alpaca.markets/us/reference/deleteopenposition-1) and [order-history schema](https://docs.alpaca.markets/us/reference/getallorders-1). Schema review and synthetic fixtures are not broker-execution evidence. A timestamp-constrained recovery candidate still depends on complete trustworthy broker observations; unresolved identity requires operator reconciliation. Root pytest excludes Astra Desk. These local checks do not establish hosted CI, deployment, current account health or profitable strategy behavior. The shared reservation repair above is layered onto this dependency. Comprehensive portfolio correlation, concentration and loss/drawdown controls remain incomplete.

## Earlier Earnings Adaptive paper book evidence — 13 October 2026

The following section preserves the previous implementation and its 778-test receipt. Its GTC/multi-day behavior is superseded by the same-session policy above.

The earnings arm is a second PAPER book. It reads a free Nasdaq earnings calendar and an operator copy of the screener's `universe_75.txt`. It submits a GTC bracket only when the live gap is inside the screener's 4–12% band, Jev accepts it on the same floors as the intraday arm, and the dollar caps allow the share count. `parse_authority("LIVE")` still raises. Client order ids start with `athe-`. The book file is separate from the dated intraday journals. A restart reconciles those ids and does not resubmit them. SIGTERM does not flatten. The intraday runner ignores `athe-` orders and symbols in the earnings ledger, and it still refuses any other foreign symbol.

The calendar has no SLA, no surprise or guidance fields, and skips `time-not-supplied`. Options, multi-leg orders, Kelly sizing, and PROTECT/HARVEST/DEFEND ratchets are not in this slice. On `--run`, the TypeSafe model list is probed only when the book is about to seek a new entry. A restart still reconciles open brackets, replaces a missing stop, and exits at max hold while that probe is failing; the failure is journaled `JEV_UNAVAILABLE` and blocks new entries. `--preflight` still probes Jev and reports `decision_model`.

Closed earnings trades are copied into the shared learning store with `arm=earnings`, including fill quantity, gross P&L when entry and exit cashflows balance, the decision receipt, and source hashes. They are not eligible for the intraday negative-experience study, and that study's context, discovery, and validation ignore the earnings arm. Alpaca news headlines since the prior close are journaled and passed into the earnings Jev packet. A successful snapshot is reused for fifteen minutes and then refreshed through the entry window. A failed or rate-limited news read does not stop the book. An outcome whose close fill is still the zero-quantity acknowledgement is not stored; the book retries when the terminal fill reconciles. A 19-share entry at $104 closed at $106 is $38 gross.

A partial take-profit stays under management: the open quantity must match entry fills minus opposite-side fills, and a quantity the legs cannot explain still halts. A broker close id already stored in `close_ack` is waited on. A lost close response is reconciled only when one market close on that symbol matches the durable intent. It is not duplicated, canceled, or replaced by an unrelated order, and that uncertainty does not stop protection of another symbol. A tighter risk or notional cap is stored as `policy_tightened` and used for later entries; a looser cap or any other configuration change refuses startup. The entry window, market state, bar age, and risk are checked again after Jev returns, so a late answer does not submit. A daily-loss halt blocks only the session that recorded it. `--flatten-owned` records an operator halt even when an older daily-loss halt is already in the journal, and that halt still blocks a new entry after restart and session rollover. News snapshots refresh every fifteen minutes through the entry window and keep source and availability time. A gap outside the band is reconsidered on a later completed bar; asset, short, and intraday-symbol exclusions stay for the session, and a name is adjudicated once. A preview, a future report, or a negation is not `news=confirmed`. Earnings MFE/MAE uses samples from that trade's entry through the observation time. Intraday learning reads nested bracket legs and owned closes, and it does not treat a concurrent earnings fill as an intraday outcome. Unexplained account history still fails closed. A fallback entry is stored and is not eligible for the intraday study. Nothing here was deployed, and nothing here is a broker fill or a performance result. **LIVE remains rejected.**

Observed local checks on the lifecycle repair, Python 3.12. The prior count on this branch at `cd3034c63bd4303da51ae96f24f0f60299779251` was 771 passed. This change adds 7 tests. No pre-existing failures were present.

```bash
python3 -m pytest -q                # 778 passed in 6.12s on 5baae39; 778 passed in 5.74s after the docs merge
python3 -m ruff check .             # clean, ruff 0.15.8
bash -n deploy/install.sh           # clean
git diff --check                    # clean
```

Root pytest does not include `research/astra-desk/tests`; that suite is separate. Tested revision of the lifecycle repair: `5baae398e05c5a31b956280a002641694a4a4052`. The same 778 tests passed again after reconciling Astra 6 documentation from main `8e9062a182c25c3745e8fd03326a66235fde04ed`. That reconciliation does not change the runtime.

## Dated implementation evidence

The remainder retains dated runtime history. Older statements about Jev-only architecture, waiting for market open, or no filled paper session apply to their recorded dates. The current summary above governs current capability. Fixture and local tests never establish a broker fill or improved trading performance. The documentation-only verification recorded on main for PR #30 (730 passed, runtime blobs identical to `5708946616afb675d1c78138990d8fa46057b6d5`) remains evidence for that docs revision, not for this earnings branch.

## Transient paper reads — 13 October 2026

Broker GET calls, including minute bars, retry twice with backoff and jitter after a timeout, HTTP 429, or a 5xx response. Order POSTs are not retried. A single transient tick failure no longer flattens an open paper trade. The runner halts `RUNNER_ERROR` only after 3 consecutive transient failures or 60 seconds. A DELETE that returns 404 or 422 for an already finished or canceled leg is a successful cancel. A take-profit or stop fill still halts `POSITION_EXITED` and is also journaled as `TAKE_PROFIT_FILLED` or `STOP_FILLED`. Flat confirmation reads order history with `nested=true`. `parse_authority("LIVE")` still raises. **LIVE remains rejected.** This is not a broker fill and not evidence of trading performance.

Observed local checks, Python 3.12. The baseline on `main` `46c0754016c62ab8f381b52b9862298fc119316e` was 716 passed and 0 failed. No pre-existing failures were present. This change adds 14 tests.

```bash
python -m pytest -q                 # 730 passed in 4.73s
python -m ruff check .              # clean, ruff 0.15.8
bash -n deploy/install.sh           # clean
git diff --check                    # clean
```

Root pytest does not include Astra Desk; that suite lives in its own repository. Tested revision: `59e8fff6333858f7f7940c3d54f512445cb8b4ae`. This sentence is a docs-only follow-up; the runner, tests, and the checks above are that commit.

## Held bracket stop — 13 October 2026

On 13 October 2026 the first filled bracket was flattened about five seconds after the fill with halt `PROTECTION_MISSING`. Alpaca keeps the bracket stop leg in status `held`, and `GET /v2/orders?status=open&nested=false` does not return that leg. The post-fill check treated the missing row as no protection and `flatten_step` canceled and market-closed the position.

A filled position stays open when the tracked parent order's legs include an opposite-side `stop` or `stop_limit` in `held`, `new`, `accepted`, or `pending_new`, with a stop price and remaining quantity covering the position. A missing, canceled, rejected, or expired stop leg still halts `PROTECTION_MISSING`. Open orders are requested with `nested=true`, and nested legs are included in the snapshot, flatten/cancel, and not-flat checks. Flatten cancels the working parent rather than each of its legs. The per-check status line includes `halt_reason` when a halt is recorded. `parse_authority("LIVE")` still raises. **LIVE remains rejected.** This is not a broker fill and not evidence of trading performance.

Observed local checks, Python 3.12. The baseline on `main` `3db8edca34a6c110086d0ff064a3fa9ea4b013eb` was 704 passed and 0 failed. No pre-existing failures were present. This change adds 12 tests.

```bash
python -m pytest -q                 # 716 passed in 4.53s
python -m ruff check .              # clean, ruff 0.15.8
bash -n deploy/install.sh           # clean
git diff --check                    # clean
```

Root pytest does not include Astra Desk; that suite lives in its own repository. Tested revision: `74a1017f7bde5f43715eaca93108566b2279c981`. This sentence is a docs-only follow-up; the runner, tests, and the checks above are that commit.

## Jev probability mass — 12 October 2026

On 12 October 2026 at 08:58 America/Chicago the paper runner raised `ModelError: Jev probabilities do not sum to one` from `JevDecisionEngine.decide`. The sum had to match 1 within `1e-6`. The process exited after `decision_started`, and the restart then returned `ALREADY_REVIEWED` for that setup.

A distribution that is finite, in [0, 1], labeled with the three choices, and within 0.02 of 1 is scaled to sum to exactly 1 before the gate and the fallback score. The receipt keeps the raw values and `probability_checks.entry_decision.renormalized`. The raw response is journaled as `jev_response` before validation. A sum outside that tolerance, a negative, a non-finite value, or a missing label is `jev_veto` with `accepted` false and a reason. That veto does not submit an order, does not halt a flat account, and does not remove other TAKE_TRADE labels from the daily fallback. A transport failure before a response still propagates. `parse_authority("LIVE")` still raises. **LIVE remains rejected.** This is not a broker fill and not evidence of trading performance.

Observed local checks, Python 3.12. The baseline on `main` `1c47639df662b26d48d25d949327a7e4f7a26471` was 689 passed and 0 failed. No pre-existing failures were present. This change adds 15 tests.

```bash
python -m pytest -q                 # 704 passed in 4.67s
python -m ruff check .              # clean, ruff 0.15.8
bash -n deploy/install.sh           # clean
git diff --check                    # clean
```

Root pytest does not include Astra Desk; that suite lives in its own repository. Tested revision: `fa37740f50d7a8572beef3cfd9e6d7307d1fc62d`. This sentence is a docs-only follow-up; the runner, tests, and the checks above are that commit.

## Paper daily entry — 12 October 2026

New sessions admit a TAKE_TRADE label when p(TAKE_TRADE) is at least 0.6 and confidence is at least 0.5. `ATHENA_JEV_MIN_PTAKE` and `ATHENA_JEV_MIN_CONFIDENCE` override those floors. If no order is reserved by `ATHENA_FALLBACK_AFTER_OPEN_MINUTES` after the open (default 120), the runner submits the highest-scoring TAKE_TRADE label seen that day, once, and journals `fallback_entry` / `NO_ORDER_BY_CUTOFF`. The score is confidence times p(TAKE_TRADE). The same one-share bracket, notional, stop, buying-power, learned-veto, and one-position limits apply. `LIVE` still raises. A model error is not an approval. A bound journal keeps its saved floors; a missing fallback field resumes at 120 minutes. The 20-review cap waits for that fallback instead of ending the day.

The repository has no 2026-10-12 SPY bars or adjudication journal. That session was not replayed. The reported best label, confidence 0.61 and p(TAKE_TRADE) 0.74, is accepted by the new default gate and rejected by the previous 0.8 / 0.6 gate. That is a threshold check, not a broker fill and not evidence of trading performance. **LIVE remains rejected.**

Observed local checks, Python 3.12. The baseline on `main` `edd80a27a936b5724aba5ca6076d74e21ede7ebb` was 681 passed and 0 failed. No pre-existing failures were present.

```bash
python -m pytest -q                 # 689 passed in 10.10s
python -m ruff check .              # clean, ruff 0.15.8
bash -n deploy/install.sh           # clean
git diff --check                    # clean
```

Root pytest does not include Astra Desk; that suite lives in its own repository. Tested revision: `8f868bb16a203940b83d5534fa268c7b7e9d0152`. This sentence is a docs-only follow-up; the runner, tests, and the checks above are that commit.

## Hostinger paper pilot — 10 October 2026

Nick installed the paper runner on a Hostinger VPS. `athena-paper.service` is enabled. `/etc/athena/paper.env` on that host holds the Alpaca paper and TypeSafe keys. The file is not in git, and its contents are not recorded here. The service was last observed in `WAITING_FOR_MARKET` for Monday open. Pre-Monday fixture, preflight, and health checks passed that day. Those checks are not a broker fill. No broker session has traded, and improved trading performance is not established. **LIVE remains rejected.** The fixture lab is not paper evidence and must not auto-promote. DigitalOcean remains an optional host in [CLOUD_DEPLOYMENT.md](CLOUD_DEPLOYMENT.md). It is not the host of this install. External alerting and backup restore are still not verified. Pilot bounds in [LIVE_PAPER.md](LIVE_PAPER.md) are unchanged.

This section is a docs-only status correction. It does not change the runner, supervisor, journal, learning store, broker pin, or installer. The session-resilience behavior below is unchanged. Checked against runtime commit `5c574e53a1a417cefbd3735bcb071475dbf4999d`. `git diff --check` was clean. No Python or installer files changed, so pytest and Ruff were not re-run. Root pytest still excludes Astra Desk; that suite lives in its own repository.

## Paper session resilience — 10 October 2026

A flat account with no reserved order no longer gets a day-ending `RUNNER_ERROR` halt for a missing opening minute, a stale bar, or a TypeSafe/startup failure. The supervisor retries that journal. A reserved id that Alpaca answers with HTTP 404 twice, while the account stays flat and no `entry_ack` was stored, is journaled as `entry_not_created` / `BROKER_ORDER_NOT_FOUND` and is not submitted again. A 404 with a position or open order, or after an acknowledgement, stays unresolved. Halt remains for a reserved order, visible exposure, daily loss, and operator stop. LIVE remains rejected. The fixture lab is not on this path.

Local checks, Python 3.12, on `bcf3f446704a0a8f58a713bc86a723574c240e63`. This sentence is a docs-only follow-up; the runtime and tests are that commit.

```bash
python -m pytest -q                 # 681 passed in 11.57s
python -m ruff check .              # clean, ruff 0.15.8
bash -n deploy/install.sh           # clean
git diff --check                    # clean
```

Root pytest does not include Astra Desk; that suite lives in its own repository. These results are not a broker session.

## Paper-readiness audit — 10 October 2026

Audited main `d36164ef7843d135dbfeea3684be598566abcf33` (PR #21). The paper runner, supervisor, journal, learning store, broker pin, and installer are unchanged since `733a1c441dbed15799397192cf6470b46c370d45`. The audit recorded that the pilot was not deployed and that server-side credentials were unavailable. That deployment claim is superseded by the Hostinger install above. LIVE remains rejected. The fixture lab is not paper evidence and must not auto-promote. Full findings and the owner checklist: [paper-readiness audit](audits/2026-10-10-paper-readiness.md).

GitHub Actions on that main push succeeded (run `38073284465`). This documentation revision does not change runtime behavior.

Local checks on audit commit `4a75582617cf4e1ee1a801507f7cefc794632de6`, Python 3.12. Runtime files are that commit. This follow-up only records the commands and points the audit at them.

```bash
python -m pytest -q                 # 672 passed in 11.49s
python -m ruff check .              # clean, ruff 0.15.8
bash -n deploy/install.sh           # clean
git diff --check                    # clean
```

A one-off on that tree removed one opening-range minute from the active-paper fixture. `signal_packet` raised `ValueError: opening window needs 15 bars, found 14`. `parse_authority("LIVE")` raised `AuthorityError`. `ExecutionAuthority` was `ABSENT` and `PAPER` only. Root pytest does not include Astra Desk; that suite lives in its own repository.

## Fixture self-improve lab — 10 October 2026

Offline evolutionary toy in `paper/self_improve.py` and `scripts/run_fixture_self_improve.py`. Sol's role is a `MutationScope` over scalar `ManagementParameters` fields. A local mutator applies one field through `evolve()`. The default command runs three generations. Each generation seeds from the best search survivor and reuses the sealed search partition. An Astra-style PASS/FAIL/UNKNOWN gate uses a precommitted policy on the walk-forward selection fold. The paper walker runs only under `ExecutionAuthority.ABSENT`; simulated episode R comes from `run_symbol_session`. The frozen holdout is hashed before search and opened once after the last generation. Its verdicts are not fed back. `report.md` is the skim; the JSON receipts stay the machine record. Nothing is promoted into the paper pilot. See [FIXTURE_SELF_IMPROVE.md](FIXTURE_SELF_IMPROVE.md).

This is not broker evidence, LIVE authority, or trading-performance evidence. The lab does not call Alpaca or TypeSafe.

Tested revision: `99bf935cf4a594758726229ecacde25ab5fdc7ef`. This paragraph is a docs-only follow-up; the lab, script, and tests are that revision.

Observed local checks, Python 3.12:

```bash
python -m ruff check .    # clean, ruff 0.15.8
python -m pytest -q       # 672 passed
git diff --check          # clean
```

The previous recorded root gate on this branch was 671 passed. The additional test covers the default three-generation seed, the sealed holdout opening once, and the readable report. Root pytest does not include Astra Desk; that suite lives in its own repository. A clean local gate is not deployment or trading-performance evidence. A default CLI run (`--generations` 3) was also executed offline; stdout is the markdown report and stderr was empty.

## Repository split — 7 October 2026

Astra Desk has been independently extracted to private [`nrsandoval1231-oss/astra-desk`](https://github.com/nrsandoval1231-oss/astra-desk) through its [merged PR #1](https://github.com/nrsandoval1231-oss/astra-desk/pull/1). The migration reconstructed 64 tracked files and all three source-directory snapshots with exact Git tree SHA matches. Standalone GitHub Actions passed 158 tests and Ruff on Python 3.11 and 3.12. This repository no longer contains `research/astra-desk/` or installs its test dependencies; Athena has its own CI gate. See [extraction receipt](ASTRA_DESK_EXTRACTION.md).

**Historical note:** The dated September verification commands and bundled-Astra descriptions below document the pre-extraction repository. Run the present CI/README commands instead; historical research audits are retained unchanged.


Status date: 24 September 2026. Product authority: [Athena Trading Canon v3.0](ATHENA_TRADING_CANON.md). Nick directed Jev-only decisions, cloud paper operation, repository cleanup and outcome learning.

**Status as of 24 September 2026:** implemented and locally verified, and not deployed on that date. Cloud access and server-side Alpaca/TypeSafe credentials were unavailable then. Deployment status after 10 October 2026 is the Hostinger section above. No broker session has traded, and improved trading performance has not been observed.

## Canon-to-code map — September baseline (historical)

| Capability | Current implementation | Remaining boundary |
|---|---|---|
| Jev decision model | athena_adapter/jev.py: one typed TAKE_TRADE / NO_TRADE / INSUFFICIENT_EVIDENCE decision; active threshold gate | Semantic trading quality unmeasured; no generated thesis |
| Predictive Intraday | Existing ORB trigger/risk frame feeds paper/live.py | Bounded opening-range component, not full multi-source forecasting |
| Earnings Adaptive | paper/earnings.py: Nasdaq calendar, screener universe file, 4–12% post-earnings GTC bracket, Jev gate, Alpaca headlines as context, shared learning store tagged arm=earnings, separate paper service | Options, guidance/sentiment models, Kelly, and full APDE ratchet remain incomplete. Not deployed |
| Risk and execution | Dedicated paper account; one share/entry/day; rechecked limits; bracket, partial fills, cancellation and broker reconciliation | Full portfolio weekly/monthly/correlation policy remains incomplete |
| APDE | Shared vocabulary and historical strategy management; broker protection/cleanup in active pilot | Full EXPLORE/PROTECT/HARVEST/DEFEND ratcheting not integrated |
| Persistence | Single-writer SQLite events, verified chain and separate durable checkpoint | Privileged rewrites of both DB/anchor or lost disk require independent recovery evidence |
| Outcome feedback | paper/learning.py reconciles fills, stores gross outcomes/provenance and retrieves prior experience with a temporal boundary | Net fees and complete market-path excursions unmeasured |
| Learning validation | Fixed discovery sample, prospectively registered candidate, fresh validation sample, recorded rejection/promotion, expiring NO_TRADE rule | Narrow initial paper policy; no demonstrated future improvement or model training |
| Cloud scheduling | paper/cloud.py starts sessions, prioritizes recovery and reviews after 20:15 Eastern; Hostinger VPS service enabled 10 October 2026, last observed `WAITING_FOR_MARKET` | External alerting and backup restore not verified; LIVE remains rejected; no traded session observed |
| Athena Core | Shared adapter identity contracts reused; trading-specific experience policy implemented | General Core service/context/replay/promotion integration remains incomplete |

## Active documentation sources

- [LIVE_PAPER.md](LIVE_PAPER.md): the current main broker runner and operating bounds, with separate hybrid integration gates.
- [CLOUD_DEPLOYMENT.md](CLOUD_DEPLOYMENT.md): host setup, persistent service, preflight and activation.
- [LEARNING.md](LEARNING.md): exact learning schedule, evidence, validation and adaptive limits.
- [BUILD_PLAN.md](BUILD_PLAN.md): the single product build sequence.
- [Paper-readiness audit, 10 October 2026](audits/2026-10-10-paper-readiness.md): findings from that review, including how the fixture lab stays off the paper path. The host and credential finding in that audit is superseded by the Hostinger install above.
- [Jev and learning audit, 24 September 2026](audits/2026-09-24-jev-learning.md): scope, repairs, retained defects and cleanup decisions.
- [Research index](../research/README.md): retained historical experiments, not product entry points.

## Repository map

Strategy/market components remain in strategies/, orb_m/, market_data/ and exogenous/. Trading integration belongs in athena_adapter/, risk/, execution/, position_management/ and paper/. The active path is run_athena_paper.py under the cloud supervisor. Terra/Ollama classes and related active CLI/environment configuration were removed. The unused backtesting placeholder was deleted after a reference check.

AAT-V1/V2 source, frozen config/data identities, original source illustration and historical entry-point snapshots remain byte-identical to the prior candidate (77 protected files checked). Astra received lint-only maintenance and its test now targets the consolidated workflow. Its execution/persistence defects remain isolated; no Astra broker code is adopted into the active path. The old ORB demo CLI retains fixtures and broker preflight but refuses broker submission.

## Verification

The baseline for this update is remote PR #18 commit `2476e6b5dee38f9ac7ce5b65c9a2e6d7a702362f`. Initial repository inventory: 303 tracked files, 205 Python files parsed. New learning/runtime tests are added in this revision.

Tested revision: `733a1c441dbed15799397192cf6470b46c370d45`, tree `017e42988162fe612e98572901052c08e474e4a9`. The publication follow-up changes only this evidence line; tested runtime, deployment, research maintenance and test files are identical.

Observed local checks:

```bash
# Repository root, Python 3.12 with both packages' dependencies
python -m pytest -q                              # 657 passed
uv tool run --from ruff==0.15.8 ruff check .      # clean
bash -n deploy/install.sh                       # clean

git diff --check                               # clean
# Separately packaged Astra suite
cd research/astra-desk
python -m pytest -o addopts='' -q                # 158 passed
```

The existing root workflow now installs both packages and runs both suites. No new self-hosted runner is required. The three UP042 modernization warnings are narrowly suppressed for Astra enums because replacing Enum with StrEnum changes historical string rendering; the rest of the prior lint findings are repaired. A clean local gate is not evidence that the remote CI platform or target cloud host ran successfully.

Tests cover Jev-only decisions, malformed output, risk changes during inference, account-safe cleanup, remaining stop coverage, recovery without models, deleted journal tails, checkpoint interruption, reconciled outcomes, duplicate imports, future-data exclusion, discovery/validation separation, rule rejection/expiry, DST scheduling and a promoted rule changing the real pilot's decision path.

## Safe cleanup verification

Status addition: 30 September 2026. Safe cleanup only: deleted unreferenced `configs/orb_m_smoke_pool.txt` and unused `demo_bar_session()`, `bar_session_to_payload()`, and its private helper `_bar_to_payload()`. Stale docs were edited in place. Review-only configs and unused Alpaca corporate-action helpers were left for the owner. No dependency was removed; the supplied audit did not name one.

Tested revision: `ac4a4212a80ebd8258f46a1bf4c3d5a51708f97b`, tree `1b1478a20eb5ec5a07efd84b759229a7bc2bce24`. This evidence paragraph is a docs-only follow-up; the tested runtime files are that revision.

Observed local checks, Python 3.12:

```bash
python -m pip install pytest ruff==0.15.8 . './research/astra-desk[dev]'
python -m pytest -q                              # 657 passed
python -m ruff check .                           # clean, ruff 0.15.8
bash -n deploy/install.sh                        # clean
git diff --check                                 # clean
cd research/astra-desk
python -m pytest -o addopts='' -q                # 158 passed
```

Root pytest still excludes `research/astra-desk/tests`. A clean local gate is not cloud deployment or trading-performance evidence.

## Historical evidence and remaining defects

Earlier first integration: `9d83069e9ae53b01aee688aa68960eb8cc89ace6`, tree `aac92fd779c110c10836ddd6c0636d79f9945666`, 620 root tests. Cloud extension: `ca7a1ace2513af52474527bb7203dac9a2104ac9`, tree `3948f1e6048f468de3ac235ef45d6f3605808528`, 648 root tests. Those versions used an Actor; they are not the current runtime.

The original [audit](audits/2026-09-24.md) of `15fe4938241931078680cff79010ca09ce70feab` recorded 574 main tests, 31 lint findings, and 157/158 Astra tests. AT-06 (local gate) is now repaired. AT-01/02 (historical research receipt/resume integrity) and AT-04/05 (Astra execution/snapshots) remain open before those components can be adopted. AT-03/07 remain limitations of the historical library walker; its broker-submit CLI route is retired, and the active runner uses broker state and dated IDs. AT-08 was addressed by the canonical documentation reset.

AAT-V1 remains consumed / INVALID_EVIDENCE. The registered V2 protocol remains REGISTERED_NOT_AUTHORIZED; no holdout was rerun or reclassified. Real-money LIVE remains disabled. The current paper learning study has its own versioned policy and does not consume those research outcomes.
