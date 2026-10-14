# TC Adaptive Trade Geometry — refined research proposal

Date: 2026-10-14. Status: proposed research revision, not a promoted paper policy.

## Objective and evidence boundary

Increase net economic value per earnings opportunity while controlling losses, execution costs and concentration. Increased trade frequency is a diagnostic, not the optimization target. A lower-quality extra fill can make a more active system worse.

Sources: the consolidated August 20–21 research record, Adaptive Trade Geometry v2, and the explicitly reconstructed PRV/runbook. Preserve those source documents as historical references. This proposal adds precision rather than claiming any new rule has an edge. The original local storage location is omitted from this public-safe archive.

The local TC source declares version `tc-33-dual-surprise-v4-2026-08-13`, a 33% retracement, fixed $2,000 notional, +/-1.5% exits, and 15:55 ET flatten. That is a local source observation; this task does not establish the currently deployed runtime. The historical probe has different data and missing eligibility evidence, so its fixed-exit arm is a proxy control, not a claimed reproduction of TC-BASELINE.

## 1. Confidence becomes a measurable estimate for a specific action

The existing consolidated research already requires calibration before capital allocation. Make that requirement executable:

- Store the raw model score separately from calibrated probability, expected net R, uncertainty, and sample support.
- Define the prediction target, decision time, execution policy and horizon. For example: under a specified resting limit, fixed stop/target and 15:55 cutoff, estimate fill probability and expected net R conditional on a fill. A 90-point narrative score is not a 90% win probability.
- Value an action per eligible opportunity: `P(fill | information available now, action) × E(net R | fill, information, action)`, with zero for an unfilled opportunity and explicit capital/time constraints in portfolio testing. Compare trade and skip under the same denominator.
- Calibrate using earlier events only. Score Brier/log loss only for a precisely defined binary label; separately evaluate expected-return calibration and loss tails. Fit calibration inside each training window, never across the final test.
- Until calibration is supported, use the score as a recorded research feature and compare equal-risk actions. Do not let an unvalidated score increase sizing, accelerate entry, permit re-entry and relax exits simultaneously.
- Shared evidence does not create independent votes: EPS headlines, transcript summaries and models consuming the same source require correlated-signal checks.

## 2. Size from a loss budget

The proposed $10k/$20k/$35k/$50k/$75k bands imply planned price-stop losses of $150/$300/$525/$750/$1,125 at a 1.5% stop. The 59-to-60 score boundary doubles notional. At 89-to-90 it rises 50%. Neither jump is justified by a one-point score change without calibration evidence.

For research, calculate:

`maximum notional = min(remaining symbol loss budget / (stop fraction + all-in adverse cost allowance), available buying power, symbol exposure cap, liquidity cap, portfolio risk allowance converted to notional)`

Round down to permitted shares. Compute the risk denominator from the actual entry and stop prices. Treat this as planned risk: gaps, halts and unavailable liquidity can exceed it.

Worked arithmetic, not a chosen allocation policy: a $250 remaining symbol budget and 1.5% stop allow about $15,822 notional at 8 bps costs, or $13,157 at 40 bps, before other caps and share rounding. Fix a common budget across experimental arms before testing confidence sizing.

After evidence supports scaling, compare a small, bounded monotone risk multiplier with the original buckets. Learn it only on training data and retain an equal-risk control. Smoothness alone does not establish better performance.

## 3. One loss budget across both legs

Use one event/symbol ledger for the opening and retracement legs. Track realized losses including costs, current worst-case planned loss, pending-order reservations, entries used and available buying power.

`remaining symbol budget = initial symbol budget − cumulative realized losses − open-position risk − pending-order reserved risk`

Do not replenish this budget automatically with an early winning leg. Release pending risk only after cancellation is acknowledged. Record partial fills and overlapping order states. For the first research version, allow no simultaneous legs and no more than two filled entry episodes. A same-day loss does not automatically reset on re-entry.

Two separate full $75,000 positions stopped at 1.5%, one after the other, would lose $2,370 including 8 bps costs per trade before gap losses. A shared event budget prevents the second leg from silently doubling the intended loss allocation.

Cooldown, reduced second-leg risk and a profitable-first-leg condition remain separate hypotheses. Predeclare each before testing; do not assume those restrictions improve returns.

## 4. Define each entry anchor at decision time

For the first experiment use the existing original-gap anchor: `open − fraction × (open − prior close)`. For a long gap from $100 to $105, 33% retracement gives $103.35.

An impulse-high retracement is a different action with a different denominator. Record the anchor price, observation timestamp, reference price, fraction and resulting order price. A high observed after order submission cannot rewrite the earlier entry. If an order is amended, journal a new decision and model amendment latency.

For opening-momentum research, choose a declared observation window and submit only after it completes. Information from minute eight cannot justify an entry in minute two. Starting with a fixed completed-bar signal makes the experiment reproducible; its optimal window remains untested.

## 5. Profit protection includes costs and execution

A stop at entry is gross price break-even. With 4 bps entry plus 4 bps exit on initial notional it loses 8 bps net: $60 on a $75,000 position. A +0.08% lock is modeled net break-even only under those cost assumptions and absent adverse execution.

Separate three quantities in every report:

1. Desired protective level.
2. Simulated or actual trigger time.
3. Actual or modeled fill and net result.

Never describe a protective level as guaranteed retained profit. A gap through a stop fills at the next executable price in a credible replay. The SEC describes this distinction in its [stop-order bulletin](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins-15).

For minute bars, compare explicitly declared within-bar paths and flag outcome changes. Replaying the minute's high before its low is an assumption; raising the stop using a pre-entry high is an error. If the conclusion depends on ordering, require prints/quotes or restrict the strategy to updates after completed bars and test that distinct policy.

## 6. Measure economic value and opportunity capture separately

- Primary for matched-entry exit tests: paired difference in mean net R per filled event.
- Primary for admission/entry tests: net R per eligible opportunity, including no-fills and skips, alongside mean net R per fill.
- Report daily account returns only after a portfolio simulation enforces capital, concurrent exposure and risk constraints. A sum of overlapping event returns is not an account equity curve.
- Report MFE while the position is open and a separately labeled common-horizon counterfactual MFE. Exit-dependent MFE alone can reward early exits by shrinking the denominator.
- Capture ratios are undefined when MFE is zero. Near-zero MFE can create unstable ratios; report the valid denominator count and robust distributions rather than maximizing a ratio.
- Record gap losses, missed fills, short availability, cancellation races, timing and costs. An ineligible or unexecutable trade has no realized-paper result.

## 7. Stage the experiments

| Stage | Change under test | Main evidence needed |
|---|---|---|
| Exit mechanics | Fixed vs staircase vs retention, identical entries and risk | Intraday sequence, fills, costs, ordering sensitivity |
| Confidence calibration | Raw score vs calibrated predictions | Archived point-in-time features, prompts, model versions and outcomes |
| Entry geometry | Original-gap depths or completed-window momentum | Fill-aware opportunity outcomes; frozen exits and risk |
| Admission | Existing eligibility vs wider earnings funnel | Known earnings timing, surprise data and tradability |
| Sizing | Equal risk vs bounded calibrated scaling | Reliable economic calibration and portfolio simulation |
| Re-entry | One leg vs two under one budget | Full order/state history, costs and conditional selection controls |
| Combined policy | Only previously supported components | Interaction tests and a genuinely untouched forward period |

Use date-based walk-forward development, log every attempted configuration, and freeze candidates before viewing an untouched period. The July 2023–June 2026 local cache has already been studied; subdividing it cannot make it a pristine holdout. Use cluster-aware uncertainty and mark exploratory intervals as unadjusted for trying multiple candidates. Broad parameter searches require explicit multiple-testing controls; see [Bailey et al., Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf).

## 8. Athena receives evidence with scope

Each lesson should include source hashes, event population, period, feature-availability cutoff, exact policy, comparator, costs, effect estimate, uncertainty, failure cases, all attempted alternatives and validation state. Keep historical simulation, counterfactual simulation and reconciled paper fills distinct.

A lesson supported only on a proxy population is tagged `exploratory_proxy`. It cannot become a global trading rule through retrieval. Quarantine ambiguous, non-reproducible or contradicted lessons. Candidate selection and policy promotion remain separate recorded decisions.

## Completion of this refinement

This proposal is accompanied by a predeclared experiment plan, synthetic correctness tests, a real-cache exploratory exit comparison, a per-event exclusion manifest and per-trade results. Historical results determine which exit ideas deserve further testing; they do not validate the untested confidence, opening-momentum or re-entry components.
