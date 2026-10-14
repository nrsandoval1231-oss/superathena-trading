# Paper-readiness audit — 10 October 2026

> **Deployment note, later on 10 October 2026.** P0-1 below (no host and no server-side keys) describes this review, not the end of the day. Nick then installed the paper runner on a Hostinger VPS. `athena-paper.service` is enabled, Alpaca and TypeSafe keys live only in the host `paper.env`, and the service was last observed in `WAITING_FOR_MARKET` for Monday open. Pre-Monday fixture, preflight, and health checks passed. That install is not a traded session. **LIVE stays rejected.** Current deployment status is [IMPLEMENTATION_STATUS.md](../IMPLEMENTATION_STATUS.md). The findings below are the audit record.

**Verdict:** the bounded Alpaca **paper** pilot is implemented and is the right path onto a real paper account. At the time of this audit it was not launched. **LIVE stays rejected.** A first session can be attended only after Nick supplies a flat paper account, a TypeSafe key, and a host. It should not be left running until the day-ending halt bug below is fixed: a missing IEX minute, a stale bar, or a single startup error writes `halt` and the supervisor will not try again that day.

Audited repository: `nrsandoval1231-oss/athena-trading`. Exact main: `d36164ef7843d135dbfeea3684be598566abcf33` (merged PR #21, fixture self-improve lab). The paper runner, supervisor, journal, learning store, broker pin, and installer have not changed since `733a1c441dbed15799397192cf6470b46c370d45`. PR #21 added an offline lab only.

This audit did not deploy, did not call Alpaca or TypeSafe, and did not use real keys. GitHub Actions on the audited push succeeded: run `38073284465` (10 October 2026, about 41 seconds). Local checks on the audit commit, recorded in [IMPLEMENTATION_STATUS.md](../IMPLEMENTATION_STATUS.md), were 672 root tests passed, Ruff 0.15.8 clean, installer syntax clean, and a gapped opening window raising `opening window needs 15 bars, found 14`. Fixture results are not broker evidence and are not a trading edge.

## 1. What already works for paper

The active path is one process: `python scripts/run_athena_paper.py` under `athena_trading.paper.cloud`. Strategy code builds one opening-range candidate. Jev accepts or abstains. Deterministic checks size and refuse. Alpaca paper is the only order endpoint. Broker events, not the model, decide whether the account is flat.

| Piece | Where it lives | What it actually does |
|---|---|---|
| Jev decision | `src/athena_trading/athena_adapter/jev.py` | One call to `jev-1.13.0`. Answers are only `TAKE_TRADE`, `NO_TRADE`, or `INSUFFICIENT_EVIDENCE`. Take requires probability ≥ 0.8 and confidence ≥ 0.6. The receipt sets `execution_authorized` false. Malformed output raises `ModelError` and is not an approval. |
| Runner | `scripts/run_athena_paper.py` | `--authority` accepts only `PAPER`. `--preflight` reads the account and the model list and submits nothing. `--run` is the attended session. |
| Signal | `src/athena_trading/paper/live.py` `signal_packet` | Current Alpaca minute bars, IEX unless `ATHENA_FEED=sip`. Opening range from the existing ORB functions. One whole share. Bracket: day limit entry, stop, 2R target. No extended-hours flag enabled. |
| Risk bounds | `PilotPolicy` and the recheck in `ActivePaperPilot.tick` | Notional ≤ $1,000 and ≤ 1% of equity and ≤ buying power. Initial stop risk ≤ $10 and ≤ 0.1% of equity. New entries stop and a flatten starts at a 0.5% loss versus broker `last_equity`. At most 20 Jev calls a session. Bar age limit 90 seconds. Flatten starts 15 minutes before broker `next_close`. Price ≥ $5 and ATR ≥ $0.50 or the signal is dropped. |
| Broker pin | `src/athena_trading/paper/alpaca.py` | Base URL must be `https://paper-api.alpaca.markets`. Any other base, including `https://api.alpaca.markets`, raises. Market data uses `data.alpaca.markets`, which does not accept orders. |
| LIVE wall | `src/athena_trading/execution/authority.py` | `ExecutionAuthority` is only `ABSENT` and `PAPER`. `parse_authority("LIVE")` raises. The fixture lab repeats that check. |
| Recovery | `live.py` `flatten_step`, `cloud.py` `next_session` | Client order id is reserved before POST. A lost ack is looked up; it is not resent. An existing reservation recovers without Jev and without the TypeSafe key. Cleanup refuses orders or positions in any other symbol. Flat requires two empty broker reads plus a terminal parent order. |
| Journal | `src/athena_trading/paper/journal.py` | Single-writer SQLite, hash chain, sidecar checkpoint, `0600` file mode. |
| Learning | `src/athena_trading/paper/learning.py` | Reconciled closes become experience for the same account, symbol, direction, policy, and question. Nightly review after 20:15 America/New_York. The only automatic promotion is a 14-day `NO_TRADE` veto after a fixed 20-trade discovery sample and a separate 20-trade prospective sample. It cannot raise size, change stops, or turn on LIVE. |
| Cloud supervisor | `src/athena_trading/paper/cloud.py`, `deploy/athena-paper.service`, `deploy/install.sh` | One systemd service, dated journals under `/var/lib/athena`, recovery before a new day, service left stopped by the installer. Secrets are `/etc/athena/paper.env`, mode `0600`, read by systemd. |
| Old demo route | `scripts/run_orb_m_paper.py` | Fixtures and read-only preflight. It does not submit. |

A completed no-trade day is a successful run of this policy. Nothing in the code promises a fill.

## 2. What blocks a first attended paper session

Three things blocked it at the time of this audit, in this order. The host finding was superseded later the same day; see the deployment note above.

**At audit time, Nick did not yet have a running host or server-side keys.** [CLOUD_DEPLOYMENT.md](../CLOUD_DEPLOYMENT.md) and [LIVE_PAPER.md](../LIVE_PAPER.md) said that then. This audit found no Droplet, no `/etc/athena/paper.env`, and no launched journal. Code cannot supply those. Later on 10 October 2026 the Hostinger VPS install put the keys on the host and enabled `athena-paper.service`.

**The launch docs name the wrong install SHA.** They tell the operator to install "PR #18 or its eventual merge" and they quote 657 root tests plus 158 Astra tests. Astra Desk is no longer in this repo (PR #20). `deploy/install.sh` refuses a checkout whose `HEAD` is not the SHA argument. Cloning current main and passing the September SHA fails closed before any trade. The paper runtime at current main is the same code as `733a1c4`; the SHA to pass is the checkout you intend to run, which today is `d36164ef7843d135dbfeea3684be598566abcf33`.

**Ordinary data and startup failures end the day.** After the pilot object exists, any exception in `scripts/run_athena_paper.py` appends `halt` reason `RUNNER_ERROR`. `paper/cloud.py` treats a halt with no `entry_intent` as a finished session and will not open another entry journal for that date. Systemd restart does not clear the halt. The runbook says not to delete state to bypass a halt. The two market cases most likely to hit this on a real IEX session are below, and the tests never connect them to the supervisor.

## 3. Findings

### P0

| ID | Finding | Evidence | Consequence |
|---|---|---|---|
| P0-1 | At audit time: no paper host and no server-side Alpaca paper or TypeSafe credentials. Superseded later on 10 October 2026 by the Hostinger install in the note above. | Launch status in `docs/LIVE_PAPER.md` and `docs/CLOUD_DEPLOYMENT.md` as of this audit; `deploy/paper.env.example` is empty placeholders. | At audit time, nothing was running against a broker. This was owner work, not a code change. The later install is not a traded session. |
| P0-2 | A missing minute in the opening window aborts the day. | `signal_packet` returns quietly until `bars[-1].minute < 15`, then calls `freeze_opening_range` (`src/athena_trading/paper/live.py`). That function requires `len(window) == opening_minutes` (15) or raises (`src/athena_trading/orb_m/entry.py`). The runner's `except` writes `halt` / `RUNNER_ERROR` (`scripts/run_athena_paper.py`). `next_session` then sets `current_finished` when `halt` is set and there is no entry (`src/athena_trading/paper/cloud.py`). | IEX minute bars exist only when that venue prints. One silent minute in 09:30–09:45 makes the first later bar fatal. The account may be flat, but the dated journal will not trade again. Tests cover a complete fixture window, not a gap, and they do not run the supervisor afterward. |
| P0-3 | The same halt catches stale bars, a TypeSafe blip, a short ATR history, and a calendar mismatch. | Stale bar is an explicit `ValueError` once 15 minutes exist (`live.py`, test `test_stale_bar_is_not_replayed_as_current_signal` expects the raise). Model-list and `LearningStore` run after the pilot is constructed and before the loop (`run_athena_paper.py`). ATR needs 15 prior sessions (`average_true_range`). Daily dates must match the previous broker session or tick raises `prior daily data is stale`. | Any of these, once, finishes the day. There is no documented retry that keeps the safety rule "do not delete the journal." |

P0-2 and P0-3 are one defect with two faces: non-exposure errors use the exposure halt. Do not weaken the halt for an open order, a position, a daily-loss breach, or an unknown client-order id.

### P1

| ID | Finding | Evidence | Consequence |
|---|---|---|---|
| P1-1 | A rejected or never-created order becomes an infinite recovery loop. | `entry_intent` is appended before `POST /v2/orders` (`live.py`). Lookup is `GET /v2/orders:by_client_order_id`. HTTP errors become `ModelError` and do not include a clean "no such order" state (`jev.py` `request_json`). `flatten_step` cannot confirm flat without that parent. `next_session` keeps returning that journal as recovery, including outside market hours. | A 422 on the first bracket (price band, buying power, cash account versus short) prints `UNRESOLVED_PAPER_EXPOSURE` and the service retries forever. It does not resubmit, which is correct. It also never stops asking. The operator must look at the paper account. |
| P1-2 | Launch docs disagree with the tree Nick would clone. | `CLOUD_DEPLOYMENT.md` still says PR #18 and 657 + 158 Astra tests. `LIVE_PAPER.md` repeats the September test counts. `install.sh` compares `git rev-parse HEAD` to the argument. Astra extraction is PR #20; the lab is PR #21. | Following the September paragraph against current main fails the installer. This PR corrects those two sentences. |
| P1-3 | First-session expectations are easy to misread as a broken bot. | Policy table in `LIVE_PAPER.md`. Caps enforced again in `tick` (`NOTIONAL_BLOCKED`, `STOP_RISK_BLOCKED`, `JEV_VETO`, `LEARNED_VETO`, `SHORT_BLOCKED`). Status is printed only when it changes. | A liquid name can sit on `WAITING_FOR_SIGNAL` all day. A wide opening range or ATR above $10 returns `STOP_RISK_BLOCKED` and does not order. Jev can refuse every candidate. That is the pilot working. |
| P1-4 | The account must be dedicated and flat, or the first tick halts. | `_bind` raises if the first snapshot has any position or order (`live.py`). Cleanup raises `unowned exposure` if any other symbol appears. | An existing Alpaca paper account used for manual trades will not start. Use an empty paper account and do not place manual orders while the service runs. |
| P1-5 | Crash near the close can leave a paper position until the next session. | Flatten uses `DELETE /v2/positions/{symbol}` with no extended-hours flag. The supervisor retries recovery while the journal is unresolved, including when the market is closed. | Paper only, not live money. The position is still real inside the paper account. The bracket is not a guarantee. Watch the dashboard through the close on the first day. |
| P1-6 | No external alert, and `health.json` is not a pager. | `heartbeat` writes status text. `CLOUD_DEPLOYMENT.md` says journald and `health.json` are not external alerts. | Fine for an attended first hour. Not fine as the only watch once the P0 halt bug is fixed and the process is left up. |
| P1-7 | IEX is not the consolidated tape. | Default feed `iex` in `PilotPolicy` and `paper.env.example`. SIP is opt-in and fails if the account is not entitled. | The opening range is the IEX range. That can miss or invent a breakout relative to the primary tape. Keep `iex` until a SIP subscription exists. Do not switch feeds to "make it trade." |

### P2

| ID | Finding | Evidence |
|---|---|---|
| P2-1 | Live management is a static bracket, not APDE. | `live.py` places stop and 2R target and then only checks that a stop quantity covers the position. It does not import `ManagementParameters`. EXPLORE / PROTECT / HARVEST / DEFEND / EXIT are not driven on this path. Canon and `BUILD_PLAN.md` slice 7 still say so. |
| P2-2 | The fixture lab mutates knobs the pilot does not read. | `paper/self_improve.py` scores `run_symbol_session` under `ExecutionAuthority.ABSENT`. `promoted_to_paper_pilot` is hard-coded false. The cloud supervisor does not import the lab. |
| P2-3 | Pagination can return a short bar list. | `LivePaperAPI.bars` `break`s if `next_page_token` repeats, after at most 20 pages, and then returns what it has. A repeated token should fail closed the same way an exhausted page cap does. |
| P2-4 | `bars: null` is untested. | `raw["bars"].get(symbol, [])` assumes `bars` is a dict. A null would raise and, today, hit P0-3. |
| P2-5 | Learning does not know fees, and sampled MFE/MAE are position snapshots. | `learning.py` sets `costs` to `UNMEASURED` and `net_pnl` to null. |
| P2-6 | Weekly, monthly, and correlation limits are not in the pilot. | Stated in `BUILD_PLAN.md` slice 5. One share and one entry a day make this acceptable for the first session and unfinished for a larger book. |
| P2-7 | Earnings Adaptive is not on this runner. | Canon requirement; `BUILD_PLAN.md` slice 9. Not required to place the first paper order. |
| P2-8 | Backup and restore are a runbook, not a tested drill. | `CLOUD_DEPLOYMENT.md`. Two hosts against one account are forbidden. The checkpoint is not an off-host anchor. |
| P2-9 | Every 5-second tick stores a full broker snapshot. | `journal.append("broker_observation", ...)`. Disk grows for a full session. Not a first-day blocker. Watch disk on the small Droplet. |
| P2-10 | Older main CI runs failed in about 4 seconds. | Actions runs before PR #20, for example `36793182232`. Logs are no longer retained. The audited main push succeeded. Those old failures are not a regression in this audit. |

### Walls that must stay

Confirmed on `d36164e`, and not changed by this audit:

- `ExecutionAuthority` has no `LIVE` member. `parse_authority("LIVE")` raises.
- The CLI `choices` list is `["PAPER"]`.
- `AlpacaPaperBroker` rejects every base URL except `https://paper-api.alpaca.markets`.
- The fixture lab sets `EXECUTION_AUTHORITY = "ABSENT"`, refuses an `--authority` flag, and refuses the token `LIVE`.
- Learning promotion cannot increase size or enable live money.
- AAT-V1 remains consumed / `INVALID_EVIDENCE`. This audit did not read that holdout.

## 4. ASAP checklist

### Nick does these

Do these in order. Stop if a step fails. Do not paste keys into git, the command line, a PR, or chat.

1. Open or select a **dedicated Alpaca paper** account. In the Alpaca dashboard, confirm the account is paper, equity is funded, status is active, and there are **zero positions and zero open orders**. Do not create a live-money key for this service. Live keys are not a fallback; the code will not send them to the live trading host, and they will not authenticate as paper.
2. Create a TypeSafe key that can call `jev-1.13.0`. Set a provider spending limit. The pilot calls the model at most 20 times per session and does not retry a failed call.
3. Provision one Ubuntu 24.04 host with a persistent disk. The runbook's 1 vCPU / 2 GiB Droplet is enough to start. Restrict SSH to yourself. Do not open an application port. This audit did not provision one.
4. Clone `nrsandoval1231-oss/athena-trading` to `/opt/athena-trading` and check out the full SHA you intend to run. For this audit that SHA is `d36164ef7843d135dbfeea3684be598566abcf33`. As root: `bash /opt/athena-trading/deploy/install.sh d36164ef7843d135dbfeea3684be598566abcf33`. The installer leaves `athena-paper.service` stopped. If `HEAD` and the argument differ, it exits. That is correct.
5. Edit `/etc/athena/paper.env` (root, mode `0600`). Set `ALPACA_API_KEY`, `ALPACA_API_SECRET`, `TYPESAFE_API_KEY`, `ATHENA_SYMBOL` (one uppercase symbol; start with `SPY` or `AAPL`), and `ATHENA_FEED=iex`.
6. Run the preflight in [CLOUD_DEPLOYMENT.md](../CLOUD_DEPLOYMENT.md) under the `athena` user. Require JSON with `ok: true`, `decision_model` `jev-1.13.0`, `positions` 0, `open_orders` 0, and `orders_submitted` 0. Preflight does not write a session halt.
7. Enable the service only while you can watch `journalctl -u athena-paper.service -f` and the Alpaca paper dashboard. The first session is attended. A day with no order is allowed.
8. If the log shows `RUNNER_ERROR`, `UNRESOLVED_PAPER_EXPOSURE`, or a halt, run `systemctl stop athena-paper.service`. Inspect the paper account. Do not delete `/var/lib/athena/*.sqlite`. Do not start a second clone against the same account. Until P0-2/P0-3 is fixed, a no-entry halt means that calendar day is finished for the supervisor.
9. Leave the fixture lab on your laptop or in CI. Do not point it at `/var/lib/athena` and do not treat a PASS as permission to change the pilot.

### Code still has to do these

1. P0-2 / P0-3. Missing opening minutes and stale bars become a non-trading status, not an exception. Startup failures of the model list, learning store, or data fetch, **when no `entry_intent` exists**, are logged and retried. `halt` remains mandatory for exposure, daily loss, operator stop, missing protection, and an order id the broker cannot resolve.
2. P1-1. A client-order lookup that is a definite not-found, with a flat account and no working order, is recorded once and the recovery loop stops. The id is not reused and the order is not resent.
3. After those two, add an external alert for service failure, a stale `health.json`, and unresolved exposure before any unattended day.
4. Do not add a LIVE flag, a live base URL, or a lab-to-pilot promoter in those PRs.

## 5. Recommended next PRs

1. **Session errors must not finish a flat day.** Change the live signal path so an incomplete IEX opening window and a stale bar return a wait or no-trade status. Change the runner so `RUNNER_ERROR` is not appended when there is no reserved entry. Add tests: gapped 09:30–09:45 bars leave the journal unhalted and the supervisor willing to continue; a stale bar does not call the broker submit; an exception after `entry_intent` still halts and still does not resend. This is the PR that unblocks an attended session that can survive the open.
2. **Stop the 404 recovery storm.** Map a not-found client order id, with a flat snapshot, to a terminal journal fact. `next_session` must not relaunch that journal every minute. Still no automatic resubmit. Test a 422-style failed POST followed by 404.
3. **Operator card, only after 1 and 2.** One page: symbol choice, flat-account check, the status strings, and "stop the service if unresolved." Alerting and a backup drill belong here, still PAPER-only.
4. **Do not open a PR that connects the fixture lab to the pilot.** A later, separate design can propose one management knob for a new prospective paper protocol. That work starts only after the live path actually applies that knob. It is not the ASAP path.

Earnings, full APDE, weekly limits, and SIP are later build-plan slices. They are not why the first paper order cannot be attempted.

## 6. How the fixture lab relates to the paper pilot

PR #21 (`d36164e`) is an offline toy. It should stay that way during the paper pilot.

**Leave it connected only as a neighboring package.** It already imports the paper walker and runs it with `ExecutionAuthority.ABSENT`. `FixtureBroker` submissions must stay at zero. Receipts already say `promoted_to_paper_pilot: false`, `alpaca_called: false`, `typesafe_called: false`, and `live_enabled: false`. The holdout opens once, after search, and is not a search input. The AAT-V1 holdout is not read. The cloud service does not start the lab. The learning store does not import it. Keep those boundaries.

**Do not connect it in any of these ways:**

- Do not auto-promote a search or holdout PASS into `PilotPolicy`, `ManagementParameters` on the live runner, the learning protocol, or a `NO_TRADE` rule.
- Do not write lab receipts into `/var/lib/athena` or into `learning/events.sqlite`.
- Do not call Alpaca or TypeSafe from `scripts/run_fixture_self_improve.py`.
- Do not treat synthetic R as paper P&L. The lab's episode R comes from `run_symbol_session`, which ratchets through management parameters. The live pilot never reads those parameters; it sends one bracket and waits for the broker. A lab PASS would not change the next paper order even if someone copied the numbers by hand.
- Do not feed the holdout verdict back into the next generation. The lab already forbids that. A future "helpful" loop that picks the holdout winner as the next parent would break the seal.
- Do not describe a fixture PASS as evidence the pilot is profitable, calibrated, or ready for LIVE.

The lab is allowed to suggest a hypothesis a human might later register. Registration would be a new versioned paper study, prospective, and limited the way [LEARNING.md](../LEARNING.md) already limits learning: temporary abstention first, never a larger position, never LIVE. That study does not exist today, and this audit does not authorize it.

## What this audit did not do

No Droplet, no systemd start, no Alpaca request, no TypeSafe request, no order, no journal written on a broker account. LIVE was not added. Frozen research hashes and the consumed AAT-V1 holdout were not rerun. Root pytest excludes any Astra suite because that suite is no longer in this repository; Astra's own repo remains the place for those tests. Historical September commands that `cd research/astra-desk` are records of the pre-extraction tree, not the current gate.
