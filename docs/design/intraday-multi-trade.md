# Intraday multi-trade paper proposal

Status: design only. This document does not change code, approved risk limits, the ORB constitution, overnight policy, promotion status, or the running paper service. It does not authorize LIVE. It does not place orders.

Nick's capacity target for the Predictive Intraday paper arm is about 20 to 50 trades in a regular session. The earnings arm is out of scope. It keeps its own entry and exit rules and its own service. Both arms stay flat by the regular close.

20 to 50 trades a day is a capacity target. It is not a forecast of profit. A day that prints that many fills is not a successful test. A day that prints fewer, because the daily-loss halt or a pre-registered evidence gate stopped new entries, can be a successful test.

The account equity cited below, about $98.9k, is the operator-reported paper equity. It is not a figure stored in this repository. The Oct 14 stop-out of -$1.62 and the Oct 15 unfilled signal are operator reports. The code paths those reports match are in this tree.

On 2026-10-15 Nick delegated the open choices in this note ("you decide the best route"). The defaults are in [Decisions (delegated by Nick, 2026-10-15)](#decisions-delegated-by-nick-2026-10-15). They are paper-only proposals. None of them is loaded into `PilotPolicy`, the ORB constitution, or the running service. Each one takes effect only when its stage gate is met. Nick can override any of them. Approved limits stay at the values in the section 3 table.

## What stays fixed

- `parse_authority("LIVE")` raises (`core/execution/execution/authority.py`, lines 21–25). Allowed authority remains `ABSENT` and `PAPER`.
- Protective exits do not call Jev or Astra. Halt and flatten in the intraday runner are deterministic (`strategies/custom/predictive-intraday/intraday/live.py`, `flatten_step` at lines 650–730). Astra 6 stays unwired. No provider or model id is substituted for it.
- No overnight position. Shared entry authorization refuses `overnight=True` (`core/portfolio/portfolio/shared_risk.py`, lines 411–412). Intraday `close_buffer_minutes` cannot be set below 15 (`live.py`, lines 228 and 248).
- Approved dollar caps in `PilotPolicy` stay at their current values. The Decisions section does not replace them. A delegated cap is a later gate, and Nick can override it.
- ORB-M constitution fields stay frozen. Changing one defines a different strategy (`strategies/momentum/orb-m/orb_m/constitution.py`, lines 1–9 and 38–41).
- APDE states exist (`core/portfolio/position_management/apde.py`). PROTECT, HARVEST, and DEFEND ratchets are not on the one-share pilot. This proposal does not turn them on and does not supply thresholds.
- Consumed holdouts and `INVALID_EVIDENCE` artifacts are not read or rewritten. `evaluation/backtesting/backtesting/evaluation.py` records `holdouts: not read` (line 227).
- Product code does not import `aat_v1` or `aat_v2`.
- Earnings confirmation, earnings brackets, and `athena-earnings.service` are untouched.
- This checkout is not deployed. `deploy/athena-paper.service` still describes `/opt/athena-trading`. Nothing here installs, restarts, or retargets it.

## Dependency, not a redesign

On Oct 15 the signal was valid and the entry did not fill. The runner submits a passive limit at the last completed bar's close (`live.py`, `signal_packet` lines 490–496 and `_order_from_packet` lines 327–333): `type: limit`, `limit_price` formatted from `latest_completed_close`, bracket, `time_in_force: day`, `extended_hours: false`. Alpaca's paper simulator fills a limit only once it is marketable against the quote. A limit sitting on a price the market has left does not fill. Sixty seconds later the runner halts `ENTRY_TIMEOUT` (line 1090) and does not try another order.

A separate change in `athena-trading` is replacing that passive limit with a capped marketable limit entry. This proposal treats that change as an input. It does not specify a new limit formula, offset, or cap. When that change is reviewed and ported, every new intraday entry uses it. Until then, the passive limit and the one-shot timeout remain the behavior, and a multi-trade session would repeat the Oct 15 miss on every signal.

The research paper intent is a different order. `OrderIntent` accepts only `order_type == "MARKET"` (`core/execution/execution/intent.py`, lines 52–53) and `AlpacaPaperBroker.submit` posts that simple market order with no bracket (`core/broker-adapters/broker_adapters/alpaca.py`, lines 109–120). `ActivePaperPilot` does not use `OrderIntent`. It posts the bracket itself. A later implementation has to put the capped marketable limit on the shared execution path. It must not add a third order builder inside a strategy directory.

## 1. Why one session is one trade

The cap is not a single constant named `max_trades`. Several paths each assume a single reservation, and any one of them ends the day.

### One symbol, one fresh bar, one opening-range candidate

`PilotPolicy.symbol` is one ticker (`live.py`, lines 217–218). `signal_packet` builds bars, freezes the 15-minute opening range, and calls `detect_breakout` on the latest bar only (lines 447–457). `detect_breakout` returns the first completed close outside the range (`strategies/momentum/orb-m/orb_m/entry.py`, lines 76–92). The packet's strategy label is fixed: `signal_component: opening_range_breakout` (`live.py`, line 474). News, sector context, and forecast probability are stored as unavailable or unvalidated (lines 485–486). There is no second signal family in this function.

A later minute of the same direction, range, close, and stop is the same setup (`setup_identity`, lines 500–513). The setup key is direction plus the frozen range (lines 1165–1169). Once two `decision_started` rows exist for that key, a further review returns `ALREADY_REVIEWED` (lines 1170–1176). The opening range does not move after 09:45, so one symbol has two setup keys in a day, long and short, and each is sent to Jev at most twice.

### One client order id per session

The id is `athp-` plus a hash of account id and session date, truncated to 40 characters (lines 1018–1020). Recovery queries that id and does not resubmit it (line 1026). A second entry on the same day would collide with the reservation, or would be treated as the same order. Idempotency is correct for one trade and blocking for a second.

### One journal slot

`_entry` is `journal.last("entry_intent")` (lines 569–570). `PaperJournal.last` returns the latest event of a kind (`core/accounting/accounting/journal.py`, lines 95–96). `tick` treats that one parent as the position state machine (lines 1068–1127):

| Broker state | What the runner does |
|---|---|
| `partially_filled`, or any fill that is not a full fill | Halt `PARTIAL_ENTRY` (lines 1082–1083). Quantity must be 1 (line 593). |
| `canceled`, `expired`, `rejected`, `replaced` | Halt `ENTRY_TERMINATED` (lines 1084–1089). |
| Still working after 60 seconds | Halt `ENTRY_TIMEOUT` (lines 1090–1091). |
| Filled, then flat | Halt `POSITION_EXITED` (lines 1100–1104). |
| Filled, quantity not exactly one share on the entry side | Halt `POSITION_MISMATCH` (lines 1108–1110). |
| Filled, no covering stop | Halt `PROTECTION_MISSING` (lines 1116–1124). |

`halt` writes once (lines 545–547). After any halt, `tick` only flattens (lines 1050–1051). It does not look for another signal. `flatten_step` cancels and closes that one symbol and confirms flat against that one parent (lines 650–730). The runner then appends `session_complete` and exits (`scripts/run_athena_paper.py`, lines 164–168).

So a stop-out, a target fill, a reject, a timeout, and a partial fill are the same kind of event for the session: the day is over. Oct 14's single stop-out and Oct 15's unfilled limit are the two outcomes this state machine can record. Neither path returns to `WAITING_FOR_SIGNAL`.

### Supervisor agrees the day is finished

`next_session` treats a halt with no `entry_intent` as a finished session (`strategies/custom/predictive-intraday/intraday/cloud.py`, lines 47–51). A halt that does have an entry stays in recovery until `flat_confirmed` or `entry_not_created` (lines 27–29 and 40–46). More than one unresolved journal raises and blocks new entries (lines 54–55). The supervisor runs one child and sleeps five seconds while that child is alive (`cloud.py`, line 127), then sleeps five seconds at a time before it looks for another session (line 137). It will not open a second intraday journal for a day that already halted.

### Adjudication budget cannot create 20 trades on this signal

`max_adjudications` defaults to 20, and the constructor rejects a larger value (lines 227 and 246–247). The counter limits distinct setup keys, not fills (lines 1177–1184). On one symbol the frozen range makes it irrelevant: long and short are the only keys, and each key stops after two reviews. Jev is asked only while there is no `entry_intent`. After the first submission, the model is not asked again.

Jev's receipt sets `execution_authorized` false (`core/contracts/athena_adapter/jev.py`, line 237). Acceptance still requires `TAKE_TRADE` with `p(TAKE_TRADE) >= 0.6` and `confidence >= 0.5` (lines 220–223), matching `PilotPolicy` (lines 224–225). A malformed answer vetoes the setup. It is not an approval. The question text is an opening-range question (`jev.py`, `questions`, lines 42–50). It is not a general intraday question.

### Learning and evaluation assume one owned fill

`outcome` requires one `entry_intent` and one `flat_confirmed`, and it rejects a fill quantity above 1 (`operations/paper-trading/paper/learning.py`, lines 75–89). Costs are stored as `UNMEASURED` (line 150). Eligibility for the intraday study further requires quantity 1, `accepted` true, not a fallback entry, the Jev model id, and the current question hash (lines 132–134). The protocol is registered by hash. A changed protocol raises `learning protocol drift requires a new versioned study` (lines 361–365). With a handful of closes, `discovery_n` of 20 is not met, so no candidate abstention rule is promoted (lines 440–446). The Oct 14 loss cannot legally become a rule under this protocol. That is the intended overfitting control.

`compare_policies` scores three labels on a shared opportunity list and resamples whole sessions (`evaluation.py`, lines 153–206). It has no per-strategy book, because the paper runner has one component.

### The research simulator is not the paper runner, and it is still not 20–50

ORB-M's full session allows one initial attempt and one re-entry per direction, and `run_full_session` stops at four episodes (`constitution.py`, lines 75–79; `session.py`, lines 142–153). The campaign path can run many symbols, but `SessionRiskState` vetoes at `max_open_positions` of 3, `max_daily_loss_r` of 3, and `max_drawdown_r` of 5 (`constitution.py`, lines 56–58; `session.py`, lines 220–227). Those ceilings belong to the research simulator. The risk policy states they are not the paper pilot's order size (`docs/risk-policy/README.md`). The paper pilot never calls `run_symbol_session`. Wiring it up unchanged would still be a few episodes per name under a three-position ledger, not a 20–50 order stream, and it would be a behavior change to the paper arm that this document does not approve.

### What has to change before a second trade is possible

All of the following are implementation work for later PRs. None of them is approved by this document.

1. **Session halt versus entry halt.** `ENTRY_TIMEOUT`, `ENTRY_TERMINATED`, `POSITION_EXITED`, and a no-fill cleanup must release that reservation and allow another signal when the account is flat and no loss latch is set. `DAILY_LOSS_LIMIT`, `OPERATOR_STOP`, `SESSION_CLOSE`, `PROTECTION_MISSING`, `POSITION_MISMATCH`, `EXPOSURE_AFTER_FLAT`, and unresolved exposure must still stop new entries and flatten. `DataDeferral` for a stale bar or an incomplete opening range already returns a wait status instead of halting (`live.py`, lines 61–66 and 450–455). That split stays: data gaps wait; exposure failures halt.
2. **Many reservations in one journal.** `entry_intent`, observations, and flat confirmation have to be keyed by `client_order_id`, the way earnings episodes already are. `journal.last("entry_intent")` cannot remain the book. One journal per session day stays the supervisor contract. Many sqlite files for one day would trip the "multiple unresolved sessions" raise in `cloud.py`.
3. **Per-entry idempotency.** The client id gains strategy id, symbol, and `setup_identity`, still prefixed `athp-`. A reserved id is still never resent. A lost POST is still resolved by lookup. Order POSTs stay single-attempt (`live.py`, lines 56 and 343–346).
4. **Protective state per position.** `protective_stop`, `bracket_exit_reason`, and `flatten_step` walk one parent. They have to walk every open intraday reservation and still ignore `athe-` orders (`operations/paper-trading/paper/ownership.py`). Flatten remains model-free.
5. **Learning ingest per close.** `outcome` must not require the journal to contain only one entry. New signal families must not join the existing intraday cohort: their question hash will differ, and editing `PROTOCOL` in place is a protocol-drift failure. A new study is a new versioned protocol, which is a Nick decision.
6. **Shared execution contract.** The capped marketable limit, once ported, is an `OrderIntent` (or a successor type in `core/execution`) submitted through the broker adapter under `require_paper`. Strategies do not grow a second broker client (`docs/strategy-standards/README.md`).

`RiskHaltGate` (`core/risk/risk/halt.py`) is the gate on the ORB paper-session walker. The live pilot does not call it. Later work should consult one halt decision before each send. It should not keep a private copy of the ceilings inside the strategy.

## 2. Signal families that could even approach the count

No family below has a measured edge in this repository. Fresh-bar fallback, Jev acceptance, and the one-share bracket show that a sequence can be executed. They do not show that the sequence makes money (`strategies/custom/predictive-intraday/hypothesis.md`). The delegated replay order is the frozen 1+1 re-entry study, then VWAP, then momentum, then mean reversion. Family B below, a larger attempt budget, is not on that list. A family that is replayed lives in its own directory under `strategies/`, with `strategy.yaml`, a hypothesis, and a README. Import paths stay on `athena_trading` through a link in `src/athena_trading`, which is how `intraday` and `orb_m` are wired today. Signals are functions over bars. Orders, ids, halts, and the journal stay in `core/` and `operations/paper-trading`. A research directory may set `execution_enabled: false` until a gate below says otherwise, the same pattern as `strategies/athena-retention-geometry`.

Jev remains a veto and an abstention. A `TAKE_TRADE` label is not a probability of profit (`docs/architecture/README.md`). A new family that wants a model gate uses the same choice set (`TAKE_TRADE`, `NO_TRADE`, `INSUFFICIENT_EVIDENCE`) and its own instructions. Missing or malformed model output does not open a position. Calling Jev on every bar of a liquid universe is not evidence. The adjudication ceiling stays 20. The count ladder does not depend on raising it.

### A. Opening-range breakout, as frozen

This is the only intraday signal the paper runner computes.

- **Data it already has.** One-minute bars from the configured feed (default `iex`), fifteen completed opening minutes, and at least fifteen prior daily bars for ATR (`average_true_range` requires `periods + 1` sessions, `strategies/momentum/orb-m/orb_m/market.py`, lines 62–65). Qualification inputs that the paper path actually enforces are `price_min` 5 and `atr14_min` 0.50 (`constitution.py`, lines 49–51; `live.py`, line 471). Average dollar volume and opening relative volume are constitution fields and quality-score inputs. The paper packet does not apply them.
- **What the frozen rules can emit.** One initial attempt and one re-entry per direction on one name, after a retracement test in the simulator (`entry.py`, `AttemptBudget`, lines 157–181; `session.py`, `_reentry_signal`, lines 113–139). The paper path emits none of the re-entries. It emits the latest bar's breakout, once.
- **Evidence before any paper change.** Replay of the existing simulator on a point-in-time universe (`strategies/momentum/orb-m/orb_m/universe.py`: the lookback must end before the campaign window, and a current listing snapshot is labeled `CURRENT_SNAPSHOT` so survivorship bias stays visible). Fills at the next bar's open, not at the signal close (`evaluation.py`, lines 42–44; `orb_m/execution.py`, lines 69–76). Intrabar conflicts resolved `ADVERSE_FIRST`. Report session-clustered uncertainty. Do not read holdouts.
- **Unproven.** The hypothesis file says the paper pilot is not evidence the hypothesis is true. Re-entry parameters (`reentry_enabled`, retracement bands) are on the adaptive surface, not the constitution, and the fixture lab's holdout is sealed. Promoting a re-entry setting from that lab is a separate decision and is not made here.
- **Count.** On one symbol the constitution cannot produce 20 trades. Across `rank_limit` of 20 names it can produce more episodes in simulation, still under the three-position and R-loss vetoes. Using those research ceilings as paper order authority is not approved. A paper universe is its own parameter, below.

### B. Repeated ORB re-entries beyond the constitution

More than one initial attempt or more than one re-entry per direction is a different strategy. It does not belong in `orb_m/constitution.py`. The delegated route does not study this family. The first offline report replays the frozen 1+1 budget in a separate specification and leaves this larger budget unstudied. A directory for a larger budget would be a new research specification, execution disabled, delegating range and risk-frame math to `orb_m` without copying them. That directory is not in the Stage 0 list.

- **Data.** The same bars as ORB-M, plus a declared attempt budget that is not the frozen 1 + 1.
- **Evidence.** The same replay standard as family A, on a budget Nick names. Results do not inherit ORB-M evidence. A whipsaw session is the failure mode the frozen budget was written to limit (`entry.py`, lines 157–162).
- **Unproven.** There is no result in this tree that says more retries improve anything. This family is the easiest way to manufacture trade count and the easiest way to manufacture correlated losses on one name.

### C. VWAP reclaim or pullback

`session_vwap` is a feature (`market.py`, lines 74–79). Breakout quality scores distance from VWAP (`orb_m/quality.py`). Deterioration can flag `vwap_loss` (`orb_m/deterioration.py`). None of these is an entry.

- **Data.** One-minute bars with volume for the names in a declared universe. Session VWAP from bars whose timestamps are already available, which is what `session_vwap` does. A reclaim rule also needs a definition of "lost" and "reclaimed" written down before any outcome is counted. The paper feed default is IEX. A paper-only Alpaca account is entitled to IEX. SIP is a policy choice already allowed by `PilotPolicy.feed` and is not assumed here.
- **Evidence.** An offline replay whose signal uses only completed bars, whose fill is the next open or the capped marketable limit once that dependency exists, and whose costs are a scenario (section 5). No paper order until the shadow gate.
- **Unproven.** VWAP distance is not a tested entry. Using the ORB quality weight as if it validated a VWAP strategy would launder one unscored idea into another.

### D. Intraday momentum

Deterioration already names `momentum_deceleration`, `failed_new_high`, and `lower_high` as exit pressure, not as entries (`orb_m/deterioration.py`). Relative volume exists as `relative_volume` (`market.py`, lines 120–123).

- **Data.** One-minute bars, a point-in-time liquid universe, and a trigger written in advance (for example a close through a declared lookback high after an opening-range filter). Market and sector alignment are optional inputs the ORB campaign path already threads through as numbers; the paper packet currently stores sector context as unavailable.
- **Evidence.** Same replay and cost standard. Momentum entries cluster on the same morning. The report has to show concentration across names, not only average R.
- **Unproven.** Nothing in the learning store or the evaluation module measures an intraday momentum entry. The ORB constitution is not that strategy.

### E. Mean reversion on a liquid universe

No module implements this. The ORB filters (`price_min` 5, `adv_min` 1_000_000, `atr14_min` 0.50, `rank_limit` 20) and `SelectionRule` (`universe_size` 50, `min_median_dollar_volume` 20_000_000, `universe.py`, lines 34–42) are liquidity screens for other jobs. They are not a mean-reversion model.

- **Data.** One-minute bars and a point-in-time universe manifest. A stretch definition (distance from session VWAP or from a declared mean, in ATR units) chosen before looking at outcomes. Spread data if the rule is supposed to fade moves inside the spread; IEX minute bars do not contain the NBBO.
- **Evidence.** Replay with `ADVERSE_FIRST` and next-open fills. Mean reversion is where the optimistic intrabar assumption flatters results (`orb_m/execution.py`, lines 1–9). A result that exists only under `FAVORABLE_FIRST` is not a result.
- **Unproven.** Entirely. This family can generate 20 to 50 signals on a liquid book by construction. Signal count is not expectancy.

### What this proposal does not add

A strategy directory is not created by this document. Nick picks at most one family for the first offline gate. The others stay descriptions. Earnings stays on its gap, its Jev question, its DAY brackets, and `run_athena_earnings.py`. Legacy experiments stay unpromoted.

## 3. Portfolio risk for many trades

Each name is a parameter. The semantics are what a later implementation must enforce. The value column is the approved number where one exists. A delegated proposal is named as a proposal and is not enforced. Correlation, concentration, and the other unresolved checks still have no number. Writing a proposal into this table does not activate it.

Arithmetic on the existing caps is included so the trade-count target can be compared with the loss halt. It is not a new limit. At about $98.9k equity, 0.5% of last equity is on the order of $495. The approved per-trade stop cap is $10. A session of full-stop losses, with no offsetting gains, reaches the existing daily-loss halt after on the order of fifty such losses. Winners, smaller stops, and open risk change that. The point is narrower: raising the trade count without widening the loss halt is already how the book is supposed to fail closed. Widening the halt so the count can be reached is a proposed change and is not made here.

| Parameter | Semantics | Current approved value |
|---|---|---|
| `max_daily_loss_fraction` | New entries stop and the arm flattens when equity is at or below `last_equity * (1 - fraction)`. Compared in `tick` and again in `_commit_order_coordinated` (`live.py`, lines 1063–1067 and 974–977). | `0.005` (0.5%). Constructor rejects a looser fraction (lines 239–240). Earnings uses the same 0.005 and locks it (`earnings.py`, lines 306 and 329–337). |
| `max_daily_loss_r` | Research-simulator veto when realized R is at or below the negative ceiling (`session.py`, lines 223–224). Unit is R, not dollars. | `3.0` on the ORB constitution. Not the paper pilot's dollar halt. Not adopted for a multi-trade paper book by this document. |
| `max_drawdown_r` | Research veto on giveback from the session peak realized R (`session.py`, lines 217–226). | `5.0` on the ORB constitution. Paper pilot has no drawdown latch. Not adopted. The offline pass line uses a separate 2.5% equity drawdown check. That check is a research gate, not a new halt. |
| `max_stop_risk` | Initial risk per share must be within `min(max_stop_risk, equity * 0.001)` or the order is not sent (`live.py`, lines 894 and 981). | `$10` and `0.1%` of equity, whichever is tighter. Constructor rejects a looser dollar cap (lines 237–238). |
| `max_notional` | One-share limit price must be within `min(max_notional, equity * 0.01, buying_power)` (lines 892 and 978–980). | `$1,000` and `1%` of equity, whichever is tighter, and buying power. |
| `quantity` | Share count on the intraday bracket. | `1`. Hardcoded (`live.py`, lines 328 and 491). A larger size is a proposed change requiring Nick's approval. No size is suggested. |
| `target_r` | Take-profit distance in units of the initial risk. | `2`, hardcoded as `price ± 2 * risk` (lines 332 and 495). Earnings locks `target_r` at 2.0 for its own book. Changing the intraday multiple is a different strategy and is `NEEDS NICK` before any edit. |
| `max_open_positions` (research) | Concurrent simulated positions across symbols. | `3` on the ORB constitution. |
| `max_concurrent_positions` (paper intraday) | How many intraday positions may be open at once. The pilot's effective value is 1, because the session halts after the first reservation. | Approved behavior remains 1. Delegated proposal, not activated: stay at 1 until the family has passed shadow, then at most 2. The research value 3 is not copied. Earnings `max_positions` of 3 (`earnings.py`, line 292) is not reused. |
| `max_trades_per_day` | New intraday entries after this many submissions do not send. Open brackets stay protected. This is not the success metric. | Approved behavior remains 1. Delegated ladder, not activated: 2, then 4, 8, 16, 20, then 50, one rung at a time after each gate. The 20–50 band is the top of that ladder, not the starting cap. |
| `max_trades_per_strategy` | Same counter inside one strategy id, so one family cannot consume the whole day. | Delegated proposal: equal to `max_trades_per_day` of the current rung, because one family is in paper at a time. Not activated. |
| `max_entries_per_symbol` | Submissions in one symbol per session. | Delegated proposal: 2, at every rung. That matches the frozen one-initial-plus-one-re-entry budget and does not rise when the day count rises. Not activated. |
| `max_adjudications` | Distinct setups that may be sent to Jev in one session. | `20`, and the constructor rejects more (lines 227 and 246–247). Delegated decision: keep 20. A higher ceiling is not proposed. The count ladder does not require more model calls. |
| `per_symbol_notional` | Gross reserved notional in one symbol across strategies, including working entries. | Delegated proposal: the existing per-trade `max_notional` ($1,000 and 1% of equity). One working order per symbol, so the aggregate does not stack above that cap. Not activated as a new code path. |
| `per_symbol_stop_risk` | Sum of initial stop risk in one symbol. | Delegated proposal: the existing `max_stop_risk` ($10 and 0.1% of equity). Not a looser cap. |
| `per_strategy_notional` | Reserved notional attributed to one strategy id. | Delegated proposal: `min(0.02 * equity, $2,000)`, which is two times the existing per-trade notional cap. Not activated. |
| `per_strategy_stop_risk` | Initial stop risk attributed to one strategy id. | Delegated proposal: $20, two times the $10 stop cap, and only while two positions are allowed. The 0.5% daily-loss halt is unchanged and is much tighter across a session. |
| `gross_exposure` | Sum of absolute reserved notionals on the intraday book. | Not computed in code. Delegated proposal, inactive until the concurrency-2 gate: `min(0.02 * equity, $2,000)`. Buying power remains the broker check (`shared_risk.py`, lines 419–426). The fraction does not replace that check and does not loosen `max_notional`. |
| `net_exposure` | Signed long minus short notional. | Not computed. Delegated proposal: the same `min(0.02 * equity, $2,000)` ceiling, so two positions cannot exceed the gross cap in either direction. Correlation stays inactive. Shorts still require `shortable` and `easy_to_borrow` (`live.py`, lines 910–911 and 1188–1189). |
| `correlation_limit` | Constraint on how similarly names in the book move. | Inactive. Named in `UNRESOLVED_SHARED_POLICY` (`shared_risk.py`, lines 25–32). No number is approved. This document does not add one. |
| `concentration_limit` | Constraint on how much of the book one name, sector, or factor may be. | Inactive. Same tuple. `NEEDS NICK` before it does anything. |
| `weekly_loss_limit`, `monthly_loss_limit`, `portfolio_drawdown_limit`, `overnight_stress_limit` | Listed and inactive. | No approved number. Overnight stress stays inactive because overnight positions stay forbidden. |
| `symbol_reservation` | One symbol cannot be reserved by both arms. | Active. `SYMBOL_ALREADY_RESERVED` (`shared_risk.py`, lines 415–416). |
| `buying_power` | Combined reserved notional of unreflected exposure plus the new order must fit in the snapshot's buying power. | Active as a broker fact, not a tuned threshold (`shared_risk.py`, lines 419–426). |
| `loss_cooldown_count` | After this many consecutive stop-outs, new entries pause. Open protection is not touched. | Not implemented. Delegated proposal, inactive until the first rung that allows a second entry: 2 consecutive stop-outs. One stop does not cool down, so a single re-entry can still be studied. |
| `loss_cooldown_span` | How long that pause lasts. | Delegated proposal: the rest of that regular session. It does not carry into the next session. The next session is still bound by the daily-loss halt and the rung's trade cap. |
| `kill_switch` | Latch that stops new entries and flattens through the broker, without a model. | The existing halt reasons are the switch: `DAILY_LOSS_LIMIT`, `OPERATOR_STOP`, `SESSION_CLOSE`, `PROTECTION_MISSING`, `POSITION_MISMATCH`, `EXPOSURE_AFTER_FLAT`, `RUNNER_ERROR` when exposure exists, and `FLATTEN_REQUESTED`. They stay. A new reason string is not a new risk appetite. |
| `close_buffer_minutes` | No new risk once `now >= next_close - buffer`, and an open entry flattens (`live.py`, lines 1057–1062). | `15`. The constructor rejects a smaller buffer (line 248). Earnings uses the same 15. |
| `no_new_entries_before_flatten` | Earlier cutoff after which brackets may still be managed but no new entry is sent. Flatten stays on `close_buffer_minutes`. | Approved flatten buffer remains 15. Delegated proposal, inactive until a family is allowed to send: no new entries at or after 30 minutes before `next_close`. On a 16:00 close that is 15:30 ET. This is not the constitution's minute-375 deadline (`constitution.py`, lines 45–46). |
| `ENTRY_TIMEOUT` | Working entry older than this is halted. | `60` seconds, literal in `tick` (line 1090), not a policy field. Whether a timed-out order releases the session or still ends it is the section 1 change. The duration itself stays 60 unless Nick approves a different duration. No duration is proposed. |
| `max_bar_age_seconds` | Completed bar older than this is a deferral, not a catch-up order. | `90` (lines 229 and 449–451). |
| `fallback_after_open_minutes` | After this many minutes, a remembered `TAKE_TRADE` may be sent only if the fresh bar is still that setup. | `120`, overridable by `ATHENA_FALLBACK_AFTER_OPEN_MINUTES` inside 1..300 (lines 226 and 243–245). A stale or changed setup records `fallback_no_trade` and does not send (lines 860–884). |

Shared-book behavior that already exists and must keep working with more intraday orders:

- Earnings positions and `athe-` orders are removed from the intraday decision view and are not flattened by this arm (`live.py`, `_without_earnings`, lines 530–543).
- A symbol the earnings ledger owns cannot be entered by the intraday arm, and the reverse check runs through `other_arm_exposure`.
- Local reservations the broker snapshot does not yet show still count against buying power (`shared_risk.py`, lines 385–393).
- `OVERNIGHT_NOT_AUTHORIZED` stays a hard refuse.

`UNRESOLVED_SHARED_POLICY` stays the pattern for correlation, concentration, weekly loss, monthly loss, portfolio drawdown, and overnight stress. Naming a delegated paper cap in the Decisions section does not turn those checks on, and it does not write the cap into the runner. A multi-name book of one-share positions can still be one bet. Correlation remains off on purpose. The gross cap and the concurrency cap are the controls that stand in for it until a later gate, which this note does not open.

## 4. Execution realism

### Order type

Today's intraday entry is a day bracket: passive limit at the signal close, stop at `risk_stop`, take-profit at two times that risk, one share, regular hours only. The stop and the target are broker-resident. They do not wait for the next `tick`, and they do not wait for Jev. That property stays.

The replacement entry is the capped marketable limit from the `athena-trading` dependency. This document does not restate its price. After it is ported, a non-marketable entry is a bug in the port, not a reason to invent a second formula. Alpaca's paper rule is the acceptance test for that port: a buy limit fills only when the limit is at or above the best ask, and a sell limit fills only when the limit is at or below the best bid (Alpaca paper trading documentation, "Rules and Assumptions"). The Oct 15 miss is that rule applied to a limit at the last close.

`OrderIntent`'s `MARKET`-only check is the research walker, not a reason to send uncapped market orders from the intraday arm. Uncapped market orders are not proposed.

### Partial fills, rejects, and the paper simulator's optimism

Alpaca's paper documentation states that eligible orders receive a partial fill of a random size about 10% of the time, and that quantity is not checked against NBBO size. A one-share order cannot split into a fractional share unless the account is trading fractions. The pilot does not send fractions. The `PARTIAL_ENTRY` halt is therefore latent at quantity 1 and immediate if a later approval ever raises quantity. Any implementation that allows a partial must protect the filled amount with a stop of at least that amount (`protective_stop`, lines 193–213, already requires remaining stop quantity to cover the position) and must not resubmit the remainder under the same client id.

Rejects and expirations currently halt the day (`ENTRY_TERMINATED`). After the section 1 change they release that id and leave a funnel row at stage `unfilled`. They still do not retry the POST.

Paper fills are not live fills. Alpaca states that paper trading does not account for market impact, information leakage, latency slippage, queue position, price improvement, regulatory fees, or dividends, and that a paper order can fill for more size than the quote shows. `evaluation.py` already records `paper_fill_limitation: broker paper fills are not this simulation` (line 224). Reports have to keep that sentence. A paper expectancy is not a live expectancy, and LIVE remains rejected.

### Rate limits and idempotency

Alpaca's published Trading API limit is 200 requests per minute per API key. The figure is from Alpaca's rate-limit documentation and a support note; it is the published limit, not a measurement of this account. The runner treats HTTP 429 and 5xx as transient on GET, with three attempts, and does not retry POST or DELETE (`live.py`, lines 56–58 and 106–113 and 343–346). That split stays. A 429 on submit is an unknown outcome: look up the client id, then either observe the order or record that it was not created. Never post it again.

The current loop sleeps five seconds (`run_athena_paper.py`, line 170) and reads one symbol. That is comfortably inside 200 requests per minute. A universe scan, a quote poll, and a status poll for many working brackets inside that same loop can exhaust the budget. Later work has to budget reads before it adds names. Jev's call timeout is 4 seconds (`jev.py`, line 194) and the state payload is capped at 24,000 bytes (line 185). The delegated decision keeps the adjudication ceiling at 20. The trade-count ladder is sequential fills under that ceiling, not 50 model calls.

Client ids stay unique per reservation, prefixed `athp-` for this arm and `athe-` for earnings. The journal remains single-writer. A second process on the same sqlite fails closed (`journal.py`, lines 14–22).

### Reconciliation

The runner already journals a full broker snapshot every tick, looks up the reserved id, and refuses to drop an acknowledged order that disappears (`live.py`, lines 585–588). Flat confirmation requires two consecutive flat observations and a nested order history under 500 rows (lines 706–729). Those checks generalize per reservation. They do not get weaker to make room for more trades.

`entry_coordination` holds a file lock across the two arms so two entries cannot reserve the same buying power (`shared_risk.py`). Multi-trade intraday sends take that same lock once per entry. They do not take it for protective cancels and closes. A lock that blocks a stop is a defect.

Earnings and intraday keep separate state directories and separate services. The intraday supervisor does not start the earnings process.

### Spread, slippage, and fees

The signal price is a completed trade close, not a quote. The paper decision feed defaults to IEX. Alpaca fills paper orders against the NBBO. Those are different prices. The capped marketable limit is what crosses the quote, inside a cap defined by the dependency PR. Measurement to add, without claiming a cost model is already true:

- Record, on the journaled order, the decision close, the limit, and the fill average. Slippage is fill minus decision close, signed against the position. The learning row already has `gross_pnl` and sets `costs` to `UNMEASURED`. Do not relabel gross as net.
- The constitution's `slippage_bps` of 2 and `commission_per_share` of 0 (`constitution.py`, lines 67–68) are research-simulator assumptions. They are not a measurement of this paper account.
- Alpaca equity commissions are not modeled here, and the paper simulator omits regulatory fees. A cost-adjusted report subtracts an explicit scenario, which `compare_policies` already accepts as `cost_per_share` (`evaluation.py`, line 154). The scenario is labeled as a scenario.
- Spread capture needs bid and ask at decision time. Minute bars do not contain them. Until a quote snapshot is journaled, the report says the spread was not observed.

### Pattern day trader rules and this paper account

As of 15 October 2026 the governing text is FINRA Rule 4210 as amended, described in Regulatory Notice 26-10 (effective 4 June 2026). FINRA replaced the pattern-day-trader designation, the count of four day trades in five business days, and the $25,000 pattern-day-trader minimum equity with an intraday margin standard. Firms may phase the new standard in until 20 October 2027. FINRA's investor summary states:

- There is no pattern-day-trader designation based on a trade count.
- There is no $25,000 minimum equity requirement attached to that designation.
- A margin account must maintain adequate equity against positions during the day. For long margin-eligible equities the maintenance level cited by FINRA is 25% of current market value, and a firm may set a higher house requirement.
- $2,000 is the minimum equity FINRA cites to use leverage. Below that, a margin account can still trade with its cash and cannot use leverage.
- An intraday margin deficit is expected to be covered promptly. A practice of failing to cover can restrict the account for up to 90 days.
- Cash accounts are outside that margin standard and remain subject to settlement. US equities settle T+1. Buying with unsettled proceeds can be a free-riding violation. This repository does not encode a cash-account settlement ledger.

Alpaca's notice of 4 June 2026 says it removed the pattern-day-trader designation, the $25,000 floor, and day-trade counting on the Trading API and the Broker API, replaced day-trade buying power with intraday buying power, and rejects orders that would create a margin deficit. It also says the minimum equity for 4× intraday buying power on a leverage-enabled account was lowered from $25,000 to $2,000. The retired fields (`pattern_day_trader`, `daytrade_count`, and the day-trade buying-power fields) were scheduled for removal from the API. This repository does not read them. It reads `equity`, `last_equity`, `buying_power`, and the block flags (`trading_blocked`, `account_blocked`, `trade_suspended_by_user`).

How the paper account behaves:

- The API base in this tree is pinned to `https://paper-api.alpaca.markets` (`alpaca.py`, line 23). The paper API spec matches the live spec. The order is not routed to an exchange. Fills are simulated, with the optimism listed above.
- Alpaca's paper documentation lists margin trading and short selling as available in paper, and borrow fees as not yet simulated.
- A default paper account is created with a $100k balance. The operator-reported equity is about $98.9k, which is consistent with a default account after a small loss and is not proof of the account's margin setting.
- At that equity, neither the retired $25,000 floor nor the $2,000 leverage minimum would, by themselves, forbid a 20–50 trade day. The binding broker constraint is buying power and house margin on the actual snapshot, plus `easy_to_borrow` for shorts. The binding Athena constraint is the 0.5% daily-loss halt and the one-share caps.
- Whether this account's `buying_power` is about equal to equity (cash or non-leveraged) or a multiple of equity is a fact in the journaled account object. This proposal does not assume 2× or 4×. Later reports quote the observed buying power. They do not invent it.
- Paper's willingness to accept the next order is not the live rule, and it is not permission to point this process at a live endpoint.

## 5. Evaluation

### Attribution

Every reservation carries `strategy_id`, `signal_component`, symbol, direction, client order id, and the verdict hash. The funnel already has stages `eligible`, `temporarily_ineligible`, `rejected`, `model_vetoed`, `budget_limited`, `unfilled`, `fallback`, and `executed` (`operations/paper-trading/paper/funnel.py`, lines 9–12). Later reports count those stages per strategy. A family that emits 40 signals and fills 4 is described that way. It is not described as "40 trades."

The learning store separates arms. Earnings episodes are stored beside intraday episodes and are marked ineligible for the intraday study (`learning.py`, `ingest_earnings`, lines 385–396). New intraday families need their own cohort key. They must not be appended to the opening-range cohort under the old question hash.

### What is reported

For each strategy, and for the intraday book:

- Trade count, fill count, reject count, timeout count. Count is not the hypothesis.
- Win rate, with a Wilson interval of the kind `evidence` already computes for the loss fraction (`learning.py`, lines 342–354, `loss_wilson_z` 1.96). Win rate without the interval is not a result.
- Expectancy per opportunity and per fill, gross, and again under a declared `cost_per_share` scenario.
- Drawdown in time order (`chronological_drawdown` in `evaluation.py`, lines 109–117), not sorted by hash.
- Uncertainty by resampling whole sessions (`session_uncertainty`, lines 120–140), because trades inside one morning are not independent samples. A 50-trade day can be one sample.
- Gap-through-stop count, using the next open when the bar record has no intrabar path.
- Direction splits, which `compare_policies` already computes.

`compare_policies` labels its output `performance: unverified` (line 226). New reports keep that label until a gate Nick defined is actually met. Jev confidence is not a calibrated probability of profit (line 225).

### Sample size

The only pre-committed sample sizes in the paper learning protocol are `discovery_n` 20 and `validation_n` 20 (`learning.py`, lines 23–28). They apply to a negative abstention rule: mean gross R at or below -0.1 and a Wilson lower bound on the loss fraction above 0.5, on a later sample that was not used to propose the rule, then a 14-day `NO_TRADE` rule. They do not authorize more risk. They are not a license to promote a strategy.

The numerical pass line for an offline family report is the delegated default in the Decisions section. It is a research gate. It does not promote a strategy, and it does not change `discovery_n` or `validation_n`.

The Oct 14 close is one loss of about $1.62. Under the protocol it cannot promote a rule, and it must not be used to tune a threshold that is then celebrated on the same point. Fallback entries are already excluded from the study (lines 130–134). That exclusion stays.

### Costs

Gross paper P&L is what the store computes. `net_pnl` is null because costs are `UNMEASURED` (the nightly report says "Gross paper outcomes; fees unmeasured; no guarantee of future improvement.", `learning.py`, line 476). Cost-adjusted results mean: show gross, show the scenario net, and say which one is which. Do not pick a fee schedule and call it observed.

### Overfitting controls that already exist

- One discovery look per cohort, and rejected candidates are retained (`learning.py`, lines 443–446).
- Validation uses only episodes opened after the candidate was recorded (lines 452–453).
- At most one candidate per cohort (`maximum_candidates_per_cohort` 1).
- Promoted action is only `NO_TRADE`.
- Protocol identity is hashed. Drift fails closed.
- The fixture self-improve lab seals its holdout and runs at authority `ABSENT` (`operations/paper-trading/paper/self_improve.py`). Its holdout is not an intraday paper result, and this work does not open it.
- Universe selection for a replay must be point-in-time, or the manifest must say `CURRENT_SNAPSHOT` (`universe.py`, lines 23–30). Ranking today's liquid names and then replaying them over a history is survivorship bias. The module's comment states that no later split removes it.

Controls this proposal adds: per-strategy cohorts, session-clustered intervals on every report, the delegated pass line, and a written refusal to treat trade count as the objective. Lowering `discovery_n` so that a handful of paper fills can create a rule is a protocol change and is not proposed. The present sizes are the protection against the empty store.

## 6. Rollout

Nick delegated the default numbers on 2026-10-15. A gate still opens only when its evidence exists. Delegation does not deploy, does not start the paper service, and does not load a new cap. He can override any default in writing. Hitting a trade count never skips a gate. PAPER only. The Hostinger service is not the place any gate is run.

### Gate 0 — Defaults recorded

Pass: this Decisions section is in the document. No code. The approved runner remains one opening-range candidate, one share, one bracket, and a halt.

### Gate 1 — Offline replay

Families run in the delegated order, one report at a time, authority `ABSENT`, no broker client. The frozen ORB baseline and `constitution.py` are not edited. Fills follow the next-open rule and `ADVERSE_FIRST`. Until the capped marketable limit formula has merged, the report says that column is absent. After it merges, the pass uses the worse of next-open and that limit. Costs are `paper-cost-scenario-v1` from the Decisions section. The universe manifest records provenance. Holdouts are not read.

Pass: every criterion in the delegated pass line, plus the sentence that no edge is claimed. A family that fails stays out of shadow. The next family in the order may still be replayed after the failed report is written. A pass opens shadow eligibility for that family only.

### Gate 2 — Shadow

Starts only after Gate 1 has passed for that family, and only after the capped marketable limit change has merged in `athena-trading` (Stage 1). The process logs signals and submits no orders for the new family. The existing one-share baseline is unchanged. Earnings is unchanged.

Pass: 10 full regular sessions, as specified in the Decisions section. Fewer than 10, a single order POST, a position held through the close, or a signal that does not match the offline rule fails the gate.

### Gate 3 — Paper rung 1

Size stays one share. `max_notional`, `max_stop_risk`, and `max_daily_loss_fraction` stay at the approved caps. The entry type is the ported capped marketable limit. The rung-1 caps (2 trades in the day, at most 2 open, per-symbol entries at most 2, gross `min(0.02 * equity, $2,000)`, cooldown after 2 stop-outs, no new entries inside 30 minutes of the close) apply only to the family that passed shadow. They are not a new default for the baseline runner on a day when that family is not enabled.

Pass: 10 paper sessions at rung 1 in which every fill or reject is journaled under its client id, every position is flat by the 15-minute close buffer, no overnight residual remains, shared-book conflicts with earnings refuse the entry, the learning protocol hash is unchanged, and the observed cost-adjusted result is reported beside the scenario. A single `PROTECTION_MISSING` or a position held through the close fails the gate. Passing rung 1 does not raise the count.

### Gate 4 — Later rungs toward 20–50

Each later rung (4, 8, 16, 20, then 50 trades in the day) requires another 10 paper sessions at the previous rung whose cost-adjusted, session-clustered result meets the same pass line on observed fills, without refitting on those fills. Gross exposure, per-trade notional, per-trade stop, quantity, and the 0.5% halt do not increase with the count. Concurrency stays at most 2. Per-symbol entries stay at most 2.

Pass is not "the session printed 20 to 50 fills." A book that reaches the count and whose session-level lower bound is negative fails. A book that the daily-loss halt stops early fails the count and can still be the correct risk outcome. The report prints both.

The target remains a target. Nothing in the ladder promises profit. Nothing in the current learning store, the one Oct 14 loss, or the Oct 15 miss is the start of an edge.

## 7. Work breakdown

Nothing in this list is started by publishing the document. Stage 0 may be written before the entry dependency merges. Stage 1 may not begin until that merge. Later rungs stay behind Gate 3 and Gate 4.

### Stage 0/1 work breakdown

| Chunk | Stage | What it contains | What it does not contain |
|---|---|---|---|
| S0-0, this document | 0 | The delegated defaults and the index link. | Production code, a new strategy directory, a limit change, a deploy. |
| S0-1, offline replay harness | 0 | A research harness under the existing evaluation path. Authority `ABSENT`. No broker client. Next-open fills, `ADVERSE_FIRST`, `paper-cost-scenario-v1`, five chronological folds, the pass line, and a check that the ORB constitution hash is unchanged. Fixture bars only until a point-in-time manifest is attached. | Orders. Edits to `constitution.py` or `PilotPolicy`. A claim that a fixture pass is market evidence. |
| S0-2, family (a) report | 0 | Replay of the frozen 1-initial-plus-1-re-entry rules, in a separate research specification with `execution_enabled: false`. The baseline one-trade paper path is the control and is not modified. | A larger attempt budget. A paper send. |
| S0-3, family (b) report | 0 | VWAP reclaim/pullback specification and replay, written only after the (a) report exists. | Using the ORB VWAP quality weight as if it validated the entry. |
| S0-4, family (c) report | 0 | Intraday momentum specification and replay, after the (b) report exists. | Editing deterioration into an entry inside `orb_m`. |
| S0-5, family (d) report | 0 | Liquid-universe mean reversion specification and replay, after the (c) report exists. | Treating `SelectionRule` liquidity floors as a model. |
| S0-6, buying-power measurement | 0 | A read-only `GET /v2/account` through the existing paper adapter, from a machine that is not the Hostinger VPS. Record `equity`, `last_equity`, `buying_power`, and `multiplier` when present. No order POST. If paper keys are absent, the PR ships the command and leaves the ratio blank. | SSH, a service restart, reading `/var/lib/athena`, assuming 2× or 4×. |
| S1-1, port the entry | 1 | Port the merged capped marketable limit onto the shared paper path. Behavior stays one share, one entry per session, approved caps. Recompute any Gate 1 pass with the worse of next-open and this limit before shadow. | A second limit formula. A second trade. A deploy. |
| S1-2, reservation identity, flag off | 1 | Per-setup `athp-` ids and a journal keyed by id. Timeout and reject still finish the day. Tests prove the flag that would release the session defaults off. | Turning that flag on. |
| S1-3, shadow | 1 | Log the first family that passed Gate 1. Ten sessions, no orders, quotes recorded, fill feasibility table filled in. `strategy.yaml` stays `execution_enabled: false` for that family. | A paper send for the new family. |
| S1-4, inactive names | 1 | The delegated cap names exist in configuration as unset. The loader refuses to enforce them until the shadow gate has passed and the rung-1 switch is explicit. Correlation and the other `UNRESOLVED_SHARED_POLICY` members stay unset. | Inventing a correlation number. Enabling rung 1 in the same PR as the names. |

Rung-1 paper (Gate 3) is a later PR after S1-3 passes. It is not part of Stage 1. It still does not deploy, and it still does not restart `athena-paper.service`.

### Tests each later PR has to add or keep

The current suite stays green. In particular `tests/test_active_paper.py`, `tests/test_cloud_paper.py`, `tests/test_paper_learning.py`, and `tests/test_shared_risk_and_evaluation.py` cover the one-share pilot. New tests, when the code exists:

- The harness refuses a run whose constitution hash differs from `Constitution().identity_hash`.
- The pass line fails a sample with a positive point expectancy and a negative session-level lower bound.
- A second setup does not reuse a client id, and a replay of the same id does not POST twice.
- `ENTRY_TIMEOUT` with the new flag off still finishes the day. With the flag on, and the account flat, a later signal may be considered. The flag's default in the PR that introduces it is off.
- `DAILY_LOSS_LIMIT` flattens every intraday reservation and does not send another.
- A partial or a missing stop still halts and still does not ask Jev how to exit.
- An `athe-` order and an earnings-owned symbol are invisible to intraday flatten and block that symbol.
- `parse_authority("LIVE")` still raises. The Alpaca adapter still rejects a non-paper base URL.
- Two journal writers on one file still fail closed.
- Learning protocol hash is unchanged by the PR. An earnings episode still cannot enter the intraday study.
- A data deferral still does not write `halt`. An exception after `entry_intent` still does.
- `OrderIntent` from a strategy test double goes through `send_gated`. The test broker is `FixtureBroker`, not the network.
- The account measurement test uses a fixture payload and does not open a socket.

### Tests each later PR has to add or keep

The current suite stays green. In particular `tests/test_active_paper.py`, `tests/test_cloud_paper.py`, `tests/test_paper_learning.py`, and `tests/test_shared_risk_and_evaluation.py` cover the one-share pilot. New tests, when the code exists:

- A second setup does not reuse a client id, and a replay of the same id does not POST twice.
- `ENTRY_TIMEOUT` with the new flag off still finishes the day. With the flag on, and the account flat, a later signal may be considered. The flag's default in the PR that introduces it is off.
- `DAILY_LOSS_LIMIT` flattens every intraday reservation and does not send another.
- A partial or a missing stop still halts and still does not ask Jev how to exit.
- An `athe-` order and an earnings-owned symbol are invisible to intraday flatten and block that symbol.
- `parse_authority("LIVE")` still raises. The Alpaca adapter still rejects a non-paper base URL.
- Two journal writers on one file still fail closed.
- Learning protocol hash is unchanged by the PR. An earnings episode still cannot enter the intraday study.
- A data deferral still does not write `halt`. An exception after `entry_intent` still does.
- `OrderIntent` from a strategy test double goes through `send_gated`. The test broker is `FixtureBroker`, not the network.

### Risks

- **Count pressure.** Tuning gates, Jev floors, or the attempt budget until the day fills 20 orders will manufacture activity. The daily-loss halt is the backstop only if nobody loosens it to fit the target.
- **One correlated bet.** With correlation inactive, two concurrent longs can stop out together. The delegated cap stays at one open position until shadow passes, then at most two, and the research ceiling of three is not copied.
- **Paper optimism.** Fills larger than the quote, no regulatory fees, and no queue will make Gate 3 look cleaner than a live book. The report has to say so. It is not a reason to open a live book.
- **Model load.** Raising adjudications toward 50 without a call budget will time out the 4-second Jev request and can 429 the broker. A model failure must remain a veto.
- **Constitution drift.** Implementing "more ORB trades" by editing `max_reentries_per_direction` invalidates old evidence. The new directory rule in section 2 is the prevention.
- **Learning on noise.** The store is nearly empty. Fitting a cooldown or a threshold to the -$1.62 close, then citing the store, is overfitting. The protocol forbids the promotion. Reviews should forbid the narrative too.
- **Shared account.** A bug that flattens `athe-` orders or double-reserves a symbol hits the earnings arm on the same paper account. The ownership tests are the mitigation.
- **Operational.** This migration checkout is not the Hostinger process. Running a multi-trade experiment from this tree against the same paper keys as the live service would race the single-writer journal and the real book. Later PRs say that in the test plan. They do not get deployed from this proposal.

## Decisions (delegated by Nick, 2026-10-15)

Nick delegated these choices on 2026-10-15. The route below is the conservative one. Every new value is a paper-only proposal. It is not loaded, not enforced, and not deployed. It takes effect only at the stage gate named with it. Approved limits are unchanged: one share, `max_notional` of $1,000 and 1% of equity, `max_stop_risk` of $10 and 0.1% of equity, `max_daily_loss_fraction` of 0.005, `close_buffer_minutes` of 15, `max_adjudications` of 20, the 2R bracket target, the 60-second entry timeout, no overnight position, and the frozen ORB constitution. Nick can override any row.

Correlation, concentration, weekly loss, monthly loss, portfolio drawdown, and overnight stress stay inactive. No number is proposed for them. APDE ratchets stay off. LIVE stays rejected. The earnings arm is untouched.

### Decision table

| # | Decision | Delegated default | When it could take effect |
|---|---|---|---|
| 1 | Replay order | (a) frozen ORB re-entry, constitution untouched, then (b) VWAP reclaim/pullback, then (c) intraday momentum, then (d) liquid-universe mean reversion. All unproven. The one-trade paper baseline is the control and is not edited. | Stage 0 reports. A fail blocks that family from shadow and does not block the next offline report. |
| 2 | Offline pass line | All of `paper-cost-scenario-v1` and the pass tests below. A pass does not claim an edge. | Gate 1, per family. |
| 3 | Shadow | 10 full regular sessions, signals logged, no orders, fill feasibility measured on real quotes. | Gate 2, and only in Stage 1 after the entry dependency merges. |
| 4 | Concurrency | 1 open intraday position until that family passes shadow. Then at most 2. The ORB research ceiling of 3 is not copied. A move to 3 would be a new gate, and none is proposed. | Gate 3 for the value 2. Until then the code stays at 1. |
| 5 | Counts and exposure | Rung 0 is today's 1 trade. Then 2, 4, 8, 16, 20, and only then 50. Per strategy equals the rung. Per symbol stays 2. Gross stays `min(0.02 * equity, $2,000)` at every rung. | Rung 1 at Gate 3. Each later rung only after Gate 4 on the previous rung. |
| 6 | Loss cooldown | After 2 consecutive stop-outs, no new entries for the rest of that session. One stop does not cool down. The pause does not carry overnight. | The first gate that allows a second entry (Gate 3). |
| 7 | Entry cutoff | Flatten stays at 15 minutes before `next_close`. No new entries at 30 minutes before `next_close`. | Gate 3. The 15-minute flatten is already approved and stays in force now. |
| 8 | Jev ceiling | Keep 20. Do not raise it to chase the trade count. | A later revision only, and only under the evidence rule below. |
| 9 | Buying power vs equity | Measure with a read-only paper account fetch. Do not assume a multiple. | Stage 0 task S0-6. Not this PR. Not the VPS. |
| 10 | Entry path | Wait for the capped marketable limit change in `athena-trading`. | Stage 1 is blocked until that change merges. |

### 1. Signal families

Replay offline, in this order, one report at a time:

1. **Frozen ORB re-entry.** The study is the constitution's existing budget: one initial attempt and one re-entry per direction (`constitution.py`, lines 75–79). It lives in a separate research specification so the report cannot be produced by editing `constitution.py`. The paper baseline keeps taking at most one trade.
2. **VWAP reclaim/pullback.** New specification. `session_vwap` is an input, not an entry.
3. **Intraday momentum.** New specification. Deterioration names stay exit signals inside `orb_m`.
4. **Liquid-universe mean reversion.** New specification. Liquidity floors are a screen, not a forecast.

Each starts unproven. The next report waits until the previous report is written, pass or fail. Only a family that meets the pass line may be nominated for shadow, and only one family is in paper at a time.

### 2. Offline pass line

`paper-cost-scenario-v1` is a labeled scenario. It is not a measured fee schedule and it does not change `costs: UNMEASURED` in the learning store.

- Slippage: 2 bps adverse on entry and 2 bps adverse on exit, the same haircut `fill_price` applies from `slippage_bps` (`constitution.py`, line 67; `orb_m/execution.py`, lines 22–31), with a floor of $0.01 per share per side.
- Unobserved spread: an extra `max($0.01, 5 bps of the decision price)` charged once on entry. Minute bars have no NBBO. Five basis points is wider than the 2 bps research haircut, so a strategy that only clears the constitution's slippage does not pass.
- Regulatory-fee scenario: $0.01 per share per side. Commission in the scenario stays $0, matching `commission_per_share` of 0. The extra cent exists so scenario-net is not a rename of gross.
- Fill: next bar's open. `ADVERSE_FIRST`. The decision close is not a fill (`evaluation.py`, lines 42–44). After the capped marketable limit formula exists, score that fill too and pass on the worse column.

A family passes Gate 1 only when every test below is true on the out-of-sample folds:

- Cost-adjusted expectancy per closed trade is greater than zero.
- The session-clustered 95% lower bound of mean cost-adjusted dollars per session is greater than zero. Sessions are resampled whole, as `session_uncertainty` already does (`evaluation.py`, lines 120–140), at `confidence` 0.95. A positive point estimate with a negative lower bound fails. That is the conservative reading of a confidence bound above zero, and it is why a short sample cannot pass.
- At least **100 closed out-of-sample trades** and at least **60 distinct out-of-sample sessions**. Training rows do not count. One hundred trades is five times the learning protocol's `validation_n` of 20, so this gate is a higher bar than a temporary abstention rule. Sixty sessions gives the bootstrap more than a handful of clusters. A pretty handful fails.
- The replay enforces the approved 0.5% daily-loss halt and then still fails the family if that halt trips on **more than 5% of out-of-sample sessions**.
- Chronological peak-to-trough drawdown is at most **2.5% of replay equity**, five times the approved daily halt. One halt-day is the operating budget. Five stacked halt-days rejects the path. This check does not change the live halt.
- Walk-forward uses **5 chronological folds**, earliest session to latest, no shuffle. Anything fit inside the family is fit on that fold's training slice only. Cost-adjusted expectancy is greater than zero in **at least 4 of the 5** test folds. Three of five is a bare majority and is not accepted. Four of five is the conservative majority.
- The constitution identity hash in the report equals the current `Constitution`. The universe manifest is point-in-time, or it is labeled `CURRENT_SNAPSHOT`. Holdouts are not read. The report says that no edge is claimed.

Replay equity for the halt and the 2.5% drawdown is the Stage 0 measured equity once S0-6 has recorded it. Until then the report uses the operator-reported $98.9k and says so.

### 3. Shadow

Ten full regular sessions for that family. A session counts only when:

- Every logged signal matches the offline rule on the same bars.
- The order POST count for the family is zero.
- The account is flat by the close, and the earnings book has no new `athp-` ids.
- Bid and ask were recorded at the decision time. A session with no quotes does not count. A bar-close proxy is the Oct 15 failure mode, and it is not fill feasibility.
- The feasibility table says, for each signal, whether the capped marketable limit would have been marketable against that quote inside 60 seconds.

The family advances only if those ten sessions exist and **at least half** of the logged signals would have been marketable inside 60 seconds. Measuring a 0% fill rate and then sending orders repeats Oct 15 on purpose. The half threshold is a feasibility screen, not an edge test.

### 4. Concurrency

Stay at one open intraday position through shadow. After shadow, the cap is two. Family (a) still holds one position at a time in its paper trial, because the second trade is a re-entry after flat. The cap of two is a maximum for later families, not a target to fill. The constitution's `max_open_positions` of 3 and the earnings book's 3 are different controls and are not copied.

### 5. Exposure and the count ladder

The 20–50 band is the top of the ladder. The starting paper cap after shadow is 2 trades in the day.

| Rung | `max_trades_per_day` | Gate |
|---|---|---|
| 0 | 1 | Now. This is the approved behavior. |
| 1 | 2 | Gate 3, after shadow and the entry port. |
| 2 | 4 | Gate 4 on 10 paper sessions at rung 1. |
| 3 | 8 | Gate 4 on 10 paper sessions at rung 2. |
| 4 | 16 | Gate 4 on 10 paper sessions at rung 3. |
| 5 | 20 | Gate 4 on 10 paper sessions at rung 4. Bottom of the target band. |
| 6 | 50 | Gate 4 on 10 paper sessions at rung 5. Top of the target band. Not a promise to get there. |

At every rung:

- `max_trades_per_strategy` equals `max_trades_per_day`, because one family is in paper.
- `max_entries_per_symbol` stays **2**. Extra trades are other symbols. Raising the day count does not authorize more than one re-entry on a name. That keeps the frozen budget intact and is why 50 trades, if they ever happen, are sequential across names rather than a loop on one ticker.
- `max_concurrent_positions` stays **2** after rung 1, including at rung 6. The count goes up by trading more often while flat, not by holding a larger book.
- Per-symbol notional and per-symbol stop stay the approved per-trade caps ($1,000 / 1% and $10 / 0.1%).
- Gross exposure stays `min(0.02 * equity, $2,000)`. Two times 1% of equity is the whole book, and $2,000 is two times the $1,000 notional cap. At about $98.9k, 2% is about $1,978, so the fraction binds. This does not loosen the per-trade cap.
- Per-strategy stop risk stays **$20** while two positions are allowed. The session is still stopped by the 0.5% halt, on the order of $495 at the reported equity, which is the tighter control.
- Net exposure uses the same `min(0.02 * equity, $2,000)` ceiling. No correlation number is added.

Rationale for doubling, then stepping onto 20 and 50: each rung is large enough to observe, and small enough that a bad rung loses the right to continue. Skipping from 2 to 50 would spend the daily halt learning that the count was early.

### 6. Loss cooldown

`loss_cooldown_count` is **2** consecutive stop-outs (`STOP_FILLED`, or a loss flatten). `loss_cooldown_span` is the **rest of that regular session**. New entries stop. A working protective stop is left alone. One stop-out does not cool down, so the frozen re-entry can still be the second trade. A third attempt the same day is the whipsaw the 1+1 budget was written to limit. The cooldown does not extend to the next session. The next session still has the daily-loss halt and the rung cap.

### 7. No-new-entries cutoff

`close_buffer_minutes` stays **15**. Flatten still begins at `next_close` minus 15 minutes (`live.py`, lines 1057–1062).

`no_new_entries_minutes` is **30**. No new entry is sent once `now` is within 30 minutes of `next_close`. On a 16:00 close that is 15:30 ET. The fifteen minutes between the cutoff and the flatten are longer than the 60-second entry timeout, so a last entry can fill or time out before the flatten. Early closes follow the broker's `next_close`, which is what the 15-minute buffer already does. This cutoff is not constitution minute 375.

### 8. Jev adjudication ceiling

The hardcoded ceiling stays **20** (`live.py`, lines 227 and 246–247). Reaching 20–50 trades does not justify 20–50 model calls. Deterministic rules can log signals with no extra Jev traffic. A model failure remains a veto.

Evidence that would justify a later proposal to raise the ceiling, which this decision does not do:

- The family has already passed Gate 1 and the 10-session shadow.
- On at least 10 of those sessions the 20-key cap refused further setups.
- Those refused setups, scored with `paper-cost-scenario-v1` and the same pass line, move the pooled out-of-sample lower bound, and the added calls fit inside the published 200 requests per minute and the 4-second Jev timeout.
- A separate revision then names the new ceiling. Until that revision, the constructor's rejection of a larger value stays correct.

### 9. Buying power versus equity

Stage 0 task S0-6 measures the paper account. It is a read-only account fetch. The code for that fetch belongs in a later PR. This PR does not add it. The VPS is not contacted, and `athena-paper.service` is not restarted.

The report records `equity`, `last_equity`, `buying_power`, and `multiplier` if the payload includes it, plus the ratio `buying_power / equity`. Gross caps in this note are fractions of equity. `authorize_entry` still refuses an order that does not fit the snapshot's buying power. No design text may assume 2× or 4×. If the measured ratio shows a cash-like account, the count ladder still does not rise, and the T+1 settlement caution in section 4 becomes a blocker for rung 2 and above until Nick overrides it.

### 10. Entry dependency

Stage 1 does not start before the capped marketable limit change has merged in `athena-trading`. Stage 0 replays use the next open and say the limit column is absent. Shadow and every paper rung use the merged formula. This document still does not restate that formula.

The approved paper behavior, until Gate 3 is actually met for a named family, remains one opening-range candidate, one share, one bracket, and a halt.
