> **RESEARCH REFERENCE — product direction restored 24 September 2026.** This document retains its experiment/component history and restrictions. Its product-level next-step instructions are superseded by [Athena Trading Canon](ATHENA_TRADING_CANON.md) and [Build Plan](BUILD_PLAN.md). Read [Implementation Status](IMPLEMENTATION_STATUS.md) for current capability.

# Athena ORB-Momentum Strategy v1.0

Status: **FROZEN BASELINE FOR FIRST REGISTERED CAMPAIGN**

## Objective
Capture the high-velocity portion of a qualified opening breakout, monetize part of that edge early, retain a runner for exceptional trends, and allow separately risked continuation/reversal opportunities under deterministic risk authority.

## 1. Opening range
- U.S. regular session.
- Opening range is 09:30–09:45 ET.
- Freeze ORH and ORL at 09:45; never move them afterward.

## 2. Breakout trigger — FROZEN
A wick/trade through ORH/ORL is **not** an entry trigger.

- Long candidate: first completed 1-minute bar after 09:45 whose close is strictly above ORH.
- Short candidate: first completed 1-minute bar after 09:45 whose close is strictly below ORL.
- Decision information becomes available only after that bar closes; simulated execution must occur causally after confirmation under the registered fill model.
- Opening-candle color is removed as a directional gate. It may be retained only as a logged feature for later prospective research.

Reason: the baseline should reject wick-only excursions and use a reproducible confirmation event. Signal count is secondary to cleaner causal definition.

## 3. Qualification
A confirmed breakout is only a candidate. Breakout quality may use point-in-time structure, relative/expanding volume, momentum/acceleration, VWAP relationship, gap/premarket context, market/sector alignment, volatility quality, extension risk and false-breakout risk.

Frozen starting action bands:
- confidence < 0.55: PASS
- 0.55–0.70: ENTER_REDUCED
- 0.70–0.85: ENTER_STANDARD
- > 0.85: ENTER_HIGH_CONVICTION

## 4. Both sides / session trade budget — FROZEN
Both sides remain live.

A stopped long does not invalidate a later confirmed short breakdown, and vice versa. A reversal is a new Decision Episode with new qualification and a new risk budget.

For V1:
- maximum one initial long episode and one initial short episode per symbol/session;
- continuation re-entry is separate from the opposite-side reversal;
- maximum one continuation re-entry per side;
- all entries remain subordinate to portfolio/daily risk halts.

This lets the system learn failed-breakout/reversal behavior without unlimited whipsaw retries.

## 5. Initial stop / definition of R — FROZEN
Use a volatility-capped structural stop, not the proposed `min(opposite range side, entry − 1×ATR)` formulation, because that expression chooses the farther/wider stop for longs in common cases.

For a long:
- `structural_stop = ORL`
- `atr_stop = entry - 1.0 * ATR`
- `raw_stop = max(structural_stop, atr_stop)`

For a short:
- `structural_stop = ORH`
- `atr_stop = entry + 1.0 * ATR`
- `raw_stop = min(structural_stop, atr_stop)`

Then enforce a registered minimum stop distance large enough to avoid zero/tick-noise risk. ATR definition and minimum-distance rule must be frozen before the campaign and computed only from point-in-time data.

`R = abs(entry - initial_stop)` after the minimum-distance rule. The initial R denominator never changes after entry even when the protective stop ratchets.

## 6. Adaptive Position Defense Engine
Canonical post-entry states:

`EXPLORE → PROTECT → HARVEST → DEFEND → EXIT`

Risk halt, session deadline and thesis invalidation take precedence. Athena/LLM may advise but deterministic risk authority has final control.

## 7. Early momentum capture
The first approximately 8 minutes after confirmed entry are the opening-impulse observation/harvest window.

Track MFE, MAE, acceleration/deceleration, volume expansion/collapse, VWAP separation, breakout distance, continuation persistence and market/sector confirmation.

Frozen starting behavior:
- around +0.5R: transition toward PROTECT when structure permits;
- around +1.0R: first 20–30% partial harvest;
- exceptional early velocity may trigger an additional 20–30% harvest.

## 8. Dynamic staircase runner
The remainder becomes a runner:
1. RISK — original structural/ATR invalidation.
2. PROTECT — reduce open risk after meaningful favorable excursion.
3. FREE TRADE — near +1R, protect near breakeven/valid structure.
4. PROFIT LOCK — lock meaningful profit after stronger excursion.
5. TREND RIDE — trail with structure + volatility/ATR + VWAP/trend context.

The protective boundary may ratchet toward profit but may not loosen merely to avoid an exit.

## 9. Peak-profit retention
Historical research target: approximately **65% retention of peak favorable R** after sufficient profitability. This is an input to the structure-aware staircase, not a rigid tick-by-tick 65% trailing stop.

## 10. Deterioration
Exit pressure may rise from failed continuation, adverse structure, VWAP loss/reclaim against the trade, momentum deceleration, volume collapse, sector divergence, broad-market reversal, abnormal adverse bars, volatility/regime shift or failed breakout retest. Multiple independent signals carry more weight than one noisy indicator.

## 11. Retracement re-entry — FROZEN REFERENCE
Retracement is measured from the **actual breakout-entry price to the post-entry peak MFE price**, not from ORH/ORL.

For a long impulse:
`impulse = peak_price - entry_price`

For a short impulse:
`impulse = entry_price - trough_price`

Retracement fraction is adverse movement from that favorable extreme divided by that impulse. The historical 15–20% shallow-retracement concept therefore refers to retracement of realized post-entry impulse.

Sequence:
`IMPULSE → HARVEST → CONTROLLED RETRACEMENT → REQUALIFY → MOMENTUM RE-EXPANSION → NEW ENTRY`

Every re-entry is a new episode with a new risk budget.

## 12. First campaign — FROZEN SCOPE
Use **50 liquid U.S. equities × approximately 2 years** of point-in-time intraday data, targeting roughly 25,000 symbol-days before qualification.

- Freeze the 50-name universe construction rule before inspecting strategy outcomes.
- Preserve delisted/corporate-action semantics where relevant; avoid survivorship contamination.
- Create immutable, non-overlapping training/validation/sealed-holdout partitions before tuning.
- Do not consume the sealed holdout until the registered promotion gate is met.
- Target at least 300 valid paired episodes for any promotion claim; if qualification yields fewer, report insufficient evidence rather than weakening gates after seeing results.

## 13. Hard boundaries
- no overnight position
- no look-ahead data
- deterministic risk veto
- explicit costs/slippage
- causal fill timing
- no sealed-holdout retuning
- immutable/versioned baseline within each registered experiment

## 14. Athena adaptation surface
Athena may prospectively learn bounded changes to breakout-quality weighting, confidence calibration, bounded sizing, harvest timing/fraction, re-entry qualification, trail aggressiveness, deterioration weighting, regime behavior and setup abandonment. Hard capital/risk authority is outside the same learning loop.

## 15. Primary research question
Given the same strong deterministic ORB constitution and repeated unseen market episodes, can Athena produce a prospectively validated improvement in risk-adjusted realized value without violating hard risk constraints or overfitting protected evidence?
