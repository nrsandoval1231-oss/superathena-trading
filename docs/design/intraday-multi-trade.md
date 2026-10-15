# Intraday multi-trade paper proposal

Status: design only. This document does not change code, approved risk limits, the ORB constitution, overnight policy, promotion status, or the running paper service. It does not authorize LIVE. It does not place orders.

Nick's capacity target for the Predictive Intraday paper arm is about 20 to 50 trades in a regular session. The earnings arm is out of scope. It keeps its own entry and exit rules and its own service. Both arms stay flat by the regular close.

20 to 50 trades a day is a capacity target. It is not a forecast of profit. A day that prints that many fills is not a successful test. A day that prints fewer, because the daily-loss halt or a pre-registered evidence gate stopped new entries, can be a successful test.

The account equity cited below, about $98.9k, is the operator-reported paper equity. It is not a figure stored in this repository. The Oct 14 stop-out of -$1.62 and the Oct 15 unfilled signal are operator reports. The code paths those reports match are in this tree.

## What stays fixed

- `parse_authority("LIVE")` raises (`core/execution/execution/authority.py`, lines 21–25). Allowed authority remains `ABSENT` and `PAPER`.
- Protective exits do not call Jev or Astra. Halt and flatten in the intraday runner are deterministic (`strategies/custom/predictive-intraday/intraday/live.py`, `flatten_step` at lines 650–730). Astra 6 stays unwired. No provider or model id is substituted for it.
- No overnight position. Shared entry authorization refuses `overnight=True` (`core/portfolio/portfolio/shared_risk.py`, lines 411–412). Intraday `close_buffer_minutes` cannot be set below 15 (`live.py`, lines 228 and 248).
- Approved dollar caps in `PilotPolicy` stay at their current values unless a later change is explicitly marked for Nick and he chooses the numbers. This document does not choose them.
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

No family below has a measured edge in this repository. Fresh-bar fallback, Jev acceptance, and the one-share bracket show that a sequence can be executed. They do not show that the sequence makes money (`strategies/custom/predictive-intraday/hypothesis.md`). Each family, if Nick asks for it, lives in its own directory under `strategies/`, with `strategy.yaml`, a hypothesis, and a README. Import paths stay on `athena_trading` through a link in `src/athena_trading`, which is how `intraday` and `orb_m` are wired today. Signals are functions over bars. Orders, ids, halts, and the journal stay in `core/` and `operations/paper-trading`. A research directory may set `execution_enabled: false` until a gate below says otherwise, the same pattern as `strategies/athena-retention-geometry`.

Jev remains a veto and an abstention. A `TAKE_TRADE` label is not a probability of profit (`docs/architecture/README.md`). A new family that wants a model gate uses the same choice set (`TAKE_TRADE`, `NO_TRADE`, `INSUFFICIENT_EVIDENCE`) and its own instructions. Missing or malformed model output does not open a position. Calling Jev on every bar of a liquid universe is not evidence, and the current adjudication ceiling of 20 cannot cover 20 to 50 distinct setups without a change Nick approves.

### A. Opening-range breakout, as frozen

This is the only intraday signal the paper runner computes.

- **Data it already has.** One-minute bars from the configured feed (default `iex`), fifteen completed opening minutes, and at least fifteen prior daily bars for ATR (`average_true_range` requires `periods + 1` sessions, `strategies/momentum/orb-m/orb_m/market.py`, lines 62–65). Qualification inputs that the paper path actually enforces are `price_min` 5 and `atr14_min` 0.50 (`constitution.py`, lines 49–51; `live.py`, line 471). Average dollar volume and opening relative volume are constitution fields and quality-score inputs. The paper packet does not apply them.
- **What the frozen rules can emit.** One initial attempt and one re-entry per direction on one name, after a retracement test in the simulator (`entry.py`, `AttemptBudget`, lines 157–181; `session.py`, `_reentry_signal`, lines 113–139). The paper path emits none of the re-entries. It emits the latest bar's breakout, once.
- **Evidence before any paper change.** Replay of the existing simulator on a point-in-time universe (`strategies/momentum/orb-m/orb_m/universe.py`: the lookback must end before the campaign window, and a current listing snapshot is labeled `CURRENT_SNAPSHOT` so survivorship bias stays visible). Fills at the next bar's open, not at the signal close (`evaluation.py`, lines 42–44; `orb_m/execution.py`, lines 69–76). Intrabar conflicts resolved `ADVERSE_FIRST`. Report session-clustered uncertainty. Do not read holdouts.
- **Unproven.** The hypothesis file says the paper pilot is not evidence the hypothesis is true. Re-entry parameters (`reentry_enabled`, retracement bands) are on the adaptive surface, not the constitution, and the fixture lab's holdout is sealed. Promoting a re-entry setting from that lab is a separate decision and is not made here.
- **Count.** On one symbol the constitution cannot produce 20 trades. Across `rank_limit` of 20 names it can produce more episodes in simulation, still under the three-position and R-loss vetoes. Using those research ceilings as paper order authority is not approved. A paper universe is its own parameter, below.

### B. Repeated ORB re-entries beyond the constitution

More than one initial attempt or more than one re-entry per direction is a different strategy. It does not belong in `orb_m/constitution.py`. If Nick wants the question studied, the directory is a new research specification, for example `strategies/momentum/orb-reentry-research`, execution disabled, delegating range and risk-frame math to `orb_m` without copying them.

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

Each name is a parameter. The semantics are what a later implementation must enforce. The value is the approved number where one exists. `NEEDS NICK` means this document refuses to pick it. Putting a number in the table without that mark would activate policy, which this proposal is not allowed to do.

Arithmetic on the existing caps is included so the trade-count target can be compared with the loss halt. It is not a new limit. At about $98.9k equity, 0.5% of last equity is on the order of $495. The approved per-trade stop cap is $10. A session of full-stop losses, with no offsetting gains, reaches the existing daily-loss halt after on the order of fifty such losses. Winners, smaller stops, and open risk change that. The point is narrower: raising the trade count without widening the loss halt is already how the book is supposed to fail closed. Widening the halt so the count can be reached is a proposed change and is not made here.

| Parameter | Semantics | Current approved value |
|---|---|---|
| `max_daily_loss_fraction` | New entries stop and the arm flattens when equity is at or below `last_equity * (1 - fraction)`. Compared in `tick` and again in `_commit_order_coordinated` (`live.py`, lines 1063–1067 and 974–977). | `0.005` (0.5%). Constructor rejects a looser fraction (lines 239–240). Earnings uses the same 0.005 and locks it (`earnings.py`, lines 306 and 329–337). |
| `max_daily_loss_r` | Research-simulator veto when realized R is at or below the negative ceiling (`session.py`, lines 223–224). Unit is R, not dollars. | `3.0` on the ORB constitution. Not the paper pilot's dollar halt. Not adopted for a multi-trade paper book by this document. |
| `max_drawdown_r` | Research veto on giveback from the session peak realized R (`session.py`, lines 217–226). | `5.0` on the ORB constitution. Paper pilot has no drawdown latch. A paper drawdown limit is `NEEDS NICK`. Until set, it stays inactive, listed beside `UNRESOLVED_SHARED_POLICY`. |
| `max_stop_risk` | Initial risk per share must be within `min(max_stop_risk, equity * 0.001)` or the order is not sent (`live.py`, lines 894 and 981). | `$10` and `0.1%` of equity, whichever is tighter. Constructor rejects a looser dollar cap (lines 237–238). |
| `max_notional` | One-share limit price must be within `min(max_notional, equity * 0.01, buying_power)` (lines 892 and 978–980). | `$1,000` and `1%` of equity, whichever is tighter, and buying power. |
| `quantity` | Share count on the intraday bracket. | `1`. Hardcoded (`live.py`, lines 328 and 491). A larger size is a proposed change requiring Nick's approval. No size is suggested. |
| `target_r` | Take-profit distance in units of the initial risk. | `2`, hardcoded as `price ± 2 * risk` (lines 332 and 495). Earnings locks `target_r` at 2.0 for its own book. Changing the intraday multiple is a different strategy and is `NEEDS NICK` before any edit. |
| `max_open_positions` (research) | Concurrent simulated positions across symbols. | `3` on the ORB constitution. |
| `max_concurrent_positions` (paper intraday) | How many intraday positions may be open at once. The pilot's effective value is 1, because the session halts after the first reservation. | `NEEDS NICK`. Adopting the research value 3 is an explicit approval, not an automatic copy. Earnings `max_positions` of 3 is that arm's cap (`earnings.py`, line 292) and is not reused. |
| `max_trades_per_day` | New intraday entries after this many submissions do not send. Open brackets stay protected. This is not the success metric. | `NEEDS NICK`. The stated 20–50 band is the capacity target to scale toward in the last gate, not a limit this document writes down as approved. The current behavior is 1. |
| `max_trades_per_strategy` | Same counter inside one strategy id, so one family cannot consume the whole day. | `NEEDS NICK`. |
| `max_adjudications` | Distinct setups that may be sent to Jev in one session. | `20`, and the constructor rejects more (lines 227 and 246–247). Covering a 20–50 trade day with one adjudication each requires a higher ceiling. That higher ceiling is `NEEDS NICK`. It is a model-call budget, not an edge. |
| `per_symbol_notional` | Gross reserved notional in one symbol across strategies, including working entries. | No approved aggregate. The per-trade `max_notional` still applies to each order. An aggregate is `NEEDS NICK`. |
| `per_symbol_stop_risk` | Sum of initial stop risk in one symbol. | No approved aggregate. Per-trade `max_stop_risk` still applies. An aggregate is `NEEDS NICK`. |
| `per_strategy_notional` | Reserved notional attributed to one strategy id. | `NEEDS NICK`. |
| `per_strategy_stop_risk` | Initial stop risk attributed to one strategy id. | `NEEDS NICK`. |
| `gross_exposure` | Sum of absolute reserved notionals on the intraday book. | Not computed. `authorize_entry` checks combined notional against buying power (`shared_risk.py`, lines 419–426). A tighter gross cap is `NEEDS NICK`. Until then the buying-power check remains, and it is not a gross-exposure policy. |
| `net_exposure` | Signed long minus short notional. | Not computed. Shorts are allowed only when the asset is `shortable` and `easy_to_borrow` (`live.py`, lines 910–911 and 1188–1189). A net cap is `NEEDS NICK` and stays inactive with the other unresolved checks. |
| `correlation_limit` | Constraint on how similarly names in the book move. | Inactive. Named in `UNRESOLVED_SHARED_POLICY` (`shared_risk.py`, lines 25–32). No number is approved. This document does not add one. |
| `concentration_limit` | Constraint on how much of the book one name, sector, or factor may be. | Inactive. Same tuple. `NEEDS NICK` before it does anything. |
| `weekly_loss_limit`, `monthly_loss_limit`, `portfolio_drawdown_limit`, `overnight_stress_limit` | Listed and inactive. | No approved number. Overnight stress stays inactive because overnight positions stay forbidden. |
| `symbol_reservation` | One symbol cannot be reserved by both arms. | Active. `SYMBOL_ALREADY_RESERVED` (`shared_risk.py`, lines 415–416). |
| `buying_power` | Combined reserved notional of unreflected exposure plus the new order must fit in the snapshot's buying power. | Active as a broker fact, not a tuned threshold (`shared_risk.py`, lines 419–426). |
| `loss_cooldown_count` | After this many consecutive losing closes, new entries pause. | Not implemented. `NEEDS NICK` for both the count and whether the pause lasts a number of minutes or the rest of the session. |
| `loss_cooldown_span` | How long that pause lasts. | `NEEDS NICK`. |
| `kill_switch` | Latch that stops new entries and flattens through the broker, without a model. | The existing halt reasons are the switch: `DAILY_LOSS_LIMIT`, `OPERATOR_STOP`, `SESSION_CLOSE`, `PROTECTION_MISSING`, `POSITION_MISMATCH`, `EXPOSURE_AFTER_FLAT`, `RUNNER_ERROR` when exposure exists, and `FLATTEN_REQUESTED`. They stay. A new reason string is not a new risk appetite. |
| `close_buffer_minutes` | No new risk once `now >= next_close - buffer`, and an open entry flattens (`live.py`, lines 1057–1062). | `15`. The constructor rejects a smaller buffer (line 248). Earnings uses the same 15. |
| `no_new_entries_before_flatten` | Optional earlier cutoff after which brackets may still be managed but no new entry is sent. | Not a separate parameter. Flatten and the entry cutoff are the same 15 minutes. An earlier cutoff is `NEEDS NICK`. The research deadline of minute 375 (15:45) and hard flat of minute 389 (15:59) stay constitution fields (`constitution.py`, lines 45–46). They are not silently copied onto the paper clock. |
| `ENTRY_TIMEOUT` | Working entry older than this is halted. | `60` seconds, literal in `tick` (line 1090), not a policy field. Whether a timed-out order releases the session or still ends it is the section 1 change. The duration itself stays 60 unless Nick approves a different duration. No duration is proposed. |
| `max_bar_age_seconds` | Completed bar older than this is a deferral, not a catch-up order. | `90` (lines 229 and 449–451). |
| `fallback_after_open_minutes` | After this many minutes, a remembered `TAKE_TRADE` may be sent only if the fresh bar is still that setup. | `120`, overridable by `ATHENA_FALLBACK_AFTER_OPEN_MINUTES` inside 1..300 (lines 226 and 243–245). A stale or changed setup records `fallback_no_trade` and does not send (lines 860–884). |

Shared-book behavior that already exists and must keep working with more intraday orders:

- Earnings positions and `athe-` orders are removed from the intraday decision view and are not flattened by this arm (`live.py`, `_without_earnings`, lines 530–543).
- A symbol the earnings ledger owns cannot be entered by the intraday arm, and the reverse check runs through `other_arm_exposure`.
- Local reservations the broker snapshot does not yet show still count against buying power (`shared_risk.py`, lines 385–393).
- `OVERNIGHT_NOT_AUTHORIZED` stays a hard refuse.

`UNRESOLVED_SHARED_POLICY` is the right pattern for every `NEEDS NICK` portfolio check: name it, do not enforce a guessed threshold, and do not treat the absence of a number as permission to take the exposure. A multi-name book of one-share positions can still be one bet. Twenty longs in the same opening drive are within today's buying-power check and outside every correlation check, because that check is off.

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

The current loop sleeps five seconds (`run_athena_paper.py`, line 170) and reads one symbol. That is comfortably inside 200 requests per minute. A universe scan, a quote poll, and a status poll for many working brackets inside that same loop can exhaust the budget. Later work has to budget reads before it adds names. Jev's call timeout is 4 seconds (`jev.py`, line 194) and the state payload is capped at 24,000 bytes (line 185). Fifty model calls are a latency and a cost question, not a signal-quality upgrade. The adjudication ceiling is the control, and raising it is `NEEDS NICK`.

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

A new family's numerical pass line (how many sessions, how negative the session-level lower bound may be) is `NEEDS NICK`. This document does not substitute 30 sessions, 100 trades, or any other threshold. If he does not set one, an offline report is informational. It does not pass a gate.

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

Controls this proposal adds, still without new numbers: per-strategy cohorts, session-clustered intervals on every report, and a written refusal to treat trade count as the objective. Lowering `discovery_n` so that a handful of paper fills can create a rule is a protocol change and is `NEEDS NICK`. It is not recommended. The present sizes are the protection against the empty store.

## 6. Rollout

Each gate requires Nick's explicit approval before the next one starts. Evidence that fails a gate stops the ladder. Hitting a trade count never skips a gate. PAPER only. The Hostinger service is not the place any gate is run.

### Gate 0 — This document

Pass: Nick accepts the document, names at most one signal family for Gate 1, and either sets the `NEEDS NICK` pass line for that offline report or accepts that the report cannot pass on its own. No code.

### Gate 1 — Offline replay

One family, on recorded bars, authority `ABSENT`, no broker client. Fills follow the next-open rule and `ADVERSE_FIRST`. The capped marketable limit is included in the replay only after its formula exists in the dependency PR; until then the replay states that it is using the next open and not that limit. Costs are a labeled scenario. The universe manifest records provenance. Holdouts are not read.

Pass: a report with those fields, the session-level lower bound, and the sentence that no edge is claimed. The report passes the numerical line only if Nick set one at Gate 0. Otherwise Gate 1 cannot open Gate 2.

### Gate 2 — Shadow

The paper process logs the family's signals into the journal and submits no orders. Existing one-share ORB behavior is unchanged unless Nick has separately approved a change. Earnings is unchanged. Halt and flatten code is not rewritten in this gate.

Pass: a number of sessions Nick sets (`NEEDS NICK`; no default is implied) in which every logged signal matches the offline rule on the same bars, the order POST count for the new family is zero, the account is flat at the close, and the earnings book shows no intraday client ids. A mismatch stops the gate.

### Gate 3 — Paper, current tiny size

Size stays one share. `max_notional`, `max_stop_risk`, and `max_daily_loss_fraction` stay at the approved caps. The entry type is the ported capped marketable limit. Concurrent positions and trades per day are whatever Nick set; if he set nothing, the runner still takes at most one intraday entry, because that is the approved behavior. Shadow evidence is not a substitute for his numbers.

Pass: for the sessions he sets, every fill or reject is journaled under its client id, every position is flat by the close buffer, no overnight residual remains, shared-book conflicts with earnings refuse the entry instead of doubling the symbol, costs are either measured from fill versus decision price or still marked `UNMEASURED`, and the learning protocol hash is unchanged. A single `PROTECTION_MISSING` or a position held through the close fails the gate.

### Gate 4 — Scale the count toward 20–50

This gate exists only after Gates 1–3 have passed and Nick has set `max_trades_per_day`, `max_trades_per_strategy`, `max_concurrent_positions`, and any gross, net, per-symbol, and cooldown numbers he wants enforced. Unset correlation and concentration limits stay inactive and are named as such in the report.

Pass is not "the session printed 20 to 50 fills." Pass is the cost-adjusted, session-clustered result meeting the line he set, on a sample at least as large as the existing validation rule's 20 prospective closes, without refitting on those closes. A book that reaches the count by taking correlated one-share signals, and whose session-level lower bound is negative, fails. A book that the daily-loss halt stops at a handful of trades also fails the count and can still be the correct risk outcome. Those are different sentences, and the report prints both.

The target remains a target. Nothing in the ladder promises profit. Nothing in the current learning store, the one Oct 14 loss, or the Oct 15 miss is the start of an edge.

## 7. Work breakdown

Later PRs are listed so the work has a shape. This document does not start them.

| Chunk | What it contains | What it does not contain |
|---|---|---|
| PR-A, this document | `docs/design/intraday-multi-trade.md` and one index link. | Any production code, any new strategy directory, any limit change. |
| PR-B, port the entry | Port the reviewed capped marketable limit from `athena-trading` onto the shared paper path. One share, one entry per day, existing caps. | A second formula. A multi-trade session. A deploy. |
| PR-C, many reservations, still one send | Client ids per setup. Journal keyed by id. Timeout and reject release the session only behind a flag that defaults to today's halt. Tests prove the default is unchanged. | Turning the flag on. A second strategy. |
| PR-D, inactive portfolio names | Extend `UNRESOLVED_SHARED_POLICY` (or a sibling tuple) with the `NEEDS NICK` names from section 3. Enforcement stays off until a value is present, and the loader rejects a value this repo invented. | Choosing the values. |
| PR-E, shadow log | One family Nick named, journaled, no orders, execution disabled in `strategy.yaml`. | Paper sends for that family. |
| PR-F, attribution report | Offline report over journals and replays: per-strategy funnel, expectancy, session intervals, cost scenario. | A promotion. A holdout read. |
| PR-G, paper multi-trade | Enabled only after Gate 3's conditions and Nick's numbers. Size remains the approved one share until a separate approval says otherwise. | LIVE. A restart of `athena-paper.service`. Earnings rule changes. APDE ratchet thresholds. |

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
- **One correlated bet.** With correlation inactive, a multi-name ORB morning can stop out together and consume the 0.5% halt in one drive. That is allowed by current policy and is a reason to keep concurrency at 1 until Nick sets a number.
- **Paper optimism.** Fills larger than the quote, no regulatory fees, and no queue will make Gate 3 look cleaner than a live book. The report has to say so. It is not a reason to open a live book.
- **Model load.** Raising adjudications toward 50 without a call budget will time out the 4-second Jev request and can 429 the broker. A model failure must remain a veto.
- **Constitution drift.** Implementing "more ORB trades" by editing `max_reentries_per_direction` invalidates old evidence. The new directory rule in section 2 is the prevention.
- **Learning on noise.** The store is nearly empty. Fitting a cooldown or a threshold to the -$1.62 close, then citing the store, is overfitting. The protocol forbids the promotion. Reviews should forbid the narrative too.
- **Shared account.** A bug that flattens `athe-` orders or double-reserves a symbol hits the earnings arm on the same paper account. The ownership tests are the mitigation.
- **Operational.** This migration checkout is not the Hostinger process. Running a multi-trade experiment from this tree against the same paper keys as the live service would race the single-writer journal and the real book. Later PRs say that in the test plan. They do not get deployed from this proposal.

### Open questions for Nick

1. Which one family, if any, is allowed into Gate 1? The choices in section 2 are A through E. "All of them" is a different, larger project.
2. What numerical line, if any, makes an offline report a pass? If none, Gate 2 stays closed.
3. How many shadow sessions are required before a paper send of a new family?
4. Does the paper concurrent-position cap stay at 1 until further notice? If not, what number replaces it?
5. What values, if any, should be enforced for `max_trades_per_day`, `max_trades_per_strategy`, per-symbol and per-strategy notional and stop risk, gross exposure, and net exposure? Unanswered items stay inactive.
6. Is a loss cooldown wanted, and if so after how many losing closes and for how long?
7. Should new entries stop earlier than the approved 15-minute flatten buffer? If so, how many minutes before the close?
8. Is the Jev adjudication ceiling allowed to move above 20, and to what? This document does not require a model call on every signal. A deterministic family can be shadow-logged with Jev left as a later veto.
9. Confirm the paper account's observed `buying_power` relative to equity, and whether the account is margin-enabled. The design will not assume a buying-power multiple.
10. Confirm that the capped marketable limit PR in `athena-trading` is the entry this design should wait for, and name the revision once it exists.

Until those answers exist, the approved paper behavior remains one opening-range candidate, one share, one bracket, and a halt.
