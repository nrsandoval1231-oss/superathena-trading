# Athena Retention Geometry

Working name for a public-safe research specification. This archive is not a runtime module, trading authorization, performance claim, or recovered journal/data package.

## Status and scope

- Manifest status: `research-specification-only`.
- Execution: disabled; no live or paper order entry is authorized by this archive.
- Entrypoint: `null`; implementation and deterministic runtime tests are pending.
- Variants: `ARG-65` and `ARG-75` (aliases `TCretain65` and `TCretain75`).
- `TC-BASELINE` remains a fixed control and must not be changed by an adaptive candidate.

The proposed comparison changes exits only while holding entry eligibility, entry timing, filled quantity, and initial risk constant. Costs and fills are execution assumptions pending evidence, not guarantees.

## Frozen control: TC-BASELINE

The complete baseline gates and mechanics are recorded here so an implementation can be checked against them:

- Earnings-reaction session with AMC previous-session or BMO today timing; US-tradable issuer.
- Prior close AND opening print each at least $10; mean `close * volume` over the 20 completed prior sessions at least $20 million; market capitalization at least $1 billion.
- Absolute gap at least 4%; 33% retracement; $2,000 raw-trigger notional quantity floor, with whole-share quantity calculated from the unrounded trigger.
- EPS and revenue surprise signs (`actual - estimate`) must both align with the gap; missing, nonfinite or zero surprises do not qualify. Shortability is required for a short; effective-date split and halt-at-open checks must pass.
- Entry uses the first eligible SIP daily-open-updating print before 09:31 ET, beginning at 09:30 ET. This is not necessarily the exchange auction price.
- Trigger and bracket prices use nearest-cent `ROUND_HALF_UP` arithmetic.
- Initial fixed exits are +1.5% target and -1.5% stop from fill. Partial fills receive protection, and remaining positions flatten at 15:55 ET.
- A 2-second acknowledgement flag is retained as a timing diagnostic; it is not a retrospective exclusion.

The frozen-control replay is a full-rules quote replay only when causal trades/quotes, queue and fill assumptions, and reconciliation are available. The current research status is not that: the prior-bar proxy replay has no held-out edge, and actual trade/quote access is blocked. No provider or account details are included here.

### Exact entry and control formulas

Let `P` be prior close, `O` the qualifying opening print, `d = sign(O - P)`, and `E` the actual average fill price. Require positive finite prices.

```text
gap = (O - P) / P
require abs(gap) >= 0.04
T = O - 0.33 * (O - P)          # 33%, not exactly one-third
Q = floor(2000 / T)             # before rounding T; reject Q < 1
entry_limit = round_cent_half_up(T)
control_target = round_cent_half_up(E * (1 + d * 0.015))
control_stop = round_cent_half_up(E * (1 - d * 0.015))
```

Place the resting retracement limit only after the opening decision. Protect broker-confirmed partial quantity and cancel the remaining entry quantity according to the frozen broker workflow; never assume an instantaneous full-size fill. The earlier minute-bar probe instead staged at 09:31 and used synthetic within-bar paths, so it is not an exact execution reproduction of this control.

The captured baseline's qualifying opening-trade condition rule is:

| Tape | Allowed conditions |
|---|---|
| A or B | Common set plus literal space and `E` |
| C | Common set plus `@`, `A`, `B`, `D`, `G`, `Y` |

Common set: `F`, `K`, `L`, `O`, `P`, `X`, `Z`, `4`, `5`, `6`, `9`. Every supplied condition must be allowed; empty conditions are accepted for known tapes. Unknown tapes are rejected. This archives the inspected source rule, not an independently revalidated exchange-standard claim. Use New York session time, including daylight saving; do not hardcode a UTC opening hour.

## Candidate exits

Both candidates retain the initial -1.5% stop. Once favorable post-entry return reaches 1%, the stop retains the declared fraction of the post-entry peak favorable return:

- `ARG-65` / `TCretain65`: retain 65% of peak.
- `ARG-75` / `TCretain75`: retain 75% of peak.

There is no fixed +1.5% target cap in either candidate. The stop ratchets only toward profit and cannot use a pre-entry high or future information. A protection level created by an event cannot execute retroactively on that event. The signed return is `g = direction * (trade_price / entry_price - 1)` for long and short legs; `peak` is the maximum eligible post-entry `g` observed so far.

```text
s = -0.015                                      if peak < 0.01
s = max(previous_stop_return, -0.015, k * peak)   otherwise
desired_stop_price = E * (1 + d * s)
k = 0.65 for ARG-65; k = 0.75 for ARG-75
```

Here `s` is signed return from entry, and `previous_stop_return` starts at -0.015. Retention is a fraction of the favorable move, not a fraction of the stock price or the amount surrendered. For a $100 long with a 2% post-entry peak, desired stops are $101.30 and $101.50; for a $100 short with a 2% favorable move, $98.70 and $98.50. These are arithmetic examples, not observed trades or guaranteed fills.

The screening simulation used fractional-price protective levels. Before an actual-tape implementation, freeze nearest-cent order rounding, replacement latency, valid-quote age, displayed-size handling and target-limit queue rules. Report those execution changes explicitly rather than claiming byte-identical execution to the bar probe. Triggered stops execute at the next available executable price under the declared model; gaps may cross the intended protection. Use bid for sell-exit scenarios and ask for buy-to-cover scenarios, with costs kept separate from measured spread. No fixed all-in cost scenario is a claim about observed execution.

## Broader adaptive paper map (not validated here)

The source paper distinguishes a broader adaptive arm from this exit-only comparison. Its starting research map is: `<45` skip; `45–59` selective, 50% retracement, $10,000 maximum paper allocation, no opening momentum or re-entry; `60–69` trade, 40%, $20,000, limited re-entry; `70–79` trade, 33%, $35,000, optional opening momentum and re-entry; `80–89` aggressive, 25%, $50,000, opening momentum and re-entry; `90–100` highest conviction, 15–20%, $75,000, opening momentum and re-entry. These are paper research limits, not allocations or recommendations.

Confidence-weighted admission, sizing, opening momentum, and retracement re-entry are distinct untested components. They must not be inferred from an exit-only result or used to replace the frozen control. Any future experiment requires a predeclared comparison, causal point-in-time features, an equal-risk control, and explicit human/risk approval.

## Evidence and invalidation

Required evidence includes point-in-time eligibility facts, timestamped trades and valid contemporaneous NBBO, execution/queue assumptions, partial-fill and cancellation timing, costs, reconciled fills, and an untouched forward period. A missing, ambiguous, or non-causal input invalidates the affected observation and remains in coverage reporting. Bar-only results are exploratory proxies, not full-TC validation.

## Preserved strategy lineage

- [Original adaptive paper design](references/TC_Paper_v2_Adaptive_Trade_Geometry.md): confidence map, momentum/re-entry concept, staircase and 65% retention, logging and promotion requirements. The historical paper approval is not runtime authorization for this archive.
- [October research refinement](references/TC_Adaptive_Trade_Geometry_Refinement_2026-10-14.md): calibrated action-specific confidence, loss-budget sizing, a shared two-leg risk budget, causal anchors, cost-aware protection and Athena evidence boundaries. These remain proposals, not baseline changes.
- [Provenance and explicit exclusions](PROVENANCE.md): source hashes, archival treatment and the data/code deliberately not uploaded.

This documents-only checkpoint does not yet satisfy the repository's deterministic runtime-test requirement for an implemented strategy. There is no executable entrypoint or broker connection to promote.
