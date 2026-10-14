# TC Paper v2 — Adaptive Trade Geometry
**Status:** Approved for PAPER implementation
**Date:** 2026-08-21
**Scope:** Paper trading only. No live-money trading.

## Objective
Increase TC trade frequency without discarding discipline by replacing binary hard-gate behavior with adaptive trade geometry.

## Architecture
Run two paper arms in parallel:

1. **TC-BASELINE** — frozen control
   - >=4% official gap
   - 33% retracement
   - +1.5% target / -1.5% stop
   - current EPS/revenue alignment rules
   - existing sizing and execution logic

2. **TC-ADAPTIVE-v2** — experimental execution arm
   - broader candidate admission
   - confidence-weighted entry depth
   - confidence-weighted sizing
   - opening-momentum capture
   - retracement re-entry
   - dynamic trailing exits
   - richer decision/execution logging

The baseline must remain unchanged so every adaptive result has a valid same-day control.

## 1. Candidate Admission

### Hard gates
Keep only genuinely structural hard gates:
- earnings event exists
- symbol is tradeable
- sufficient liquidity
- acceptable spread
- shortability when a short is required
- valid market data
- no stale/corrupt quote state
- intraday only; flatten before close

### Soft evidence, not binary vetoes
The following become confidence inputs rather than automatic rejection rules:
- gap magnitude
- EPS beat/miss
- revenue beat/miss
- EPS/revenue agreement
- guidance
- transcript tone
- market reaction alignment
- premarket trend/volume
- opening behavior

### Gap admission
- >=4%: normal TC candidate
- 2% to <4%: adaptive candidate if evidence/confidence is sufficient
- <2%: normally skip unless confidence is exceptional and opening momentum confirms

The purpose is to stop throwing away valid earnings reactions solely because a single threshold missed by a few basis points.

## 2. Confidence Engine

Final confidence is decomposable and logged.

Components:
- fundamental/earnings evidence
- guidance/outlook
- transcript/management language
- market reaction
- premarket trend and volume
- opening liquidity and spread
- structural quality
- mechanical score
- independent-signal agreement
- contradiction penalty

Contradictions reduce confidence; they do not automatically veto the setup.

## 3. Confidence → Trade Geometry

Starting PAPER map:

| Confidence | Action | Retracement | Max Paper Allocation | Opening Momentum | Re-entry |
|---|---|---:|---:|---|---|
| <45 | Skip | — | $0 | No | No |
| 45–59 | Selective | 50% | $10,000 | No | No |
| 60–69 | Trade | 40% | $20,000 | No | Limited |
| 70–79 | Trade | 33% | $35,000 | Optional | Yes |
| 80–89 | Aggressive | 25% | $50,000 | Yes | Yes |
| 90–100 | Highest conviction | 15–20% | $75,000 | Yes | Yes |

Notes:
- These are PAPER research limits.
- No single position may exceed available paper buying power.
- Initial planned stop remains -1.5% unless a specific shadow experiment changes it.
- Confidence does not override liquidity, spread, or data-integrity controls.
- Full $100,000 deployment is not enabled yet.

## 4. Opening Momentum Leg

For confidence >=80:
- allow an opening-momentum entry during the first ~8 minutes when price action confirms the thesis
- use only a fraction of the symbol's maximum allocation for this first leg
- do not chase disorderly/wide-spread prints
- manage the opening leg independently
- after exit, preserve eligibility for a retracement re-entry

For confidence 70–79:
- opening momentum is optional only when multiple independent signals agree strongly

Below 70:
- no opening-momentum leg

## 5. Retracement Re-entry

After an opening-momentum exit, a second entry is allowed if:
- the original thesis remains intact
- no material contradictory news appears
- liquidity remains acceptable
- the price retraces to the confidence-mapped level
- total symbol-level risk remains within the paper allocation/risk budget

Maximum two entries per symbol in v2:
1. opening-momentum leg
2. retracement leg

Every re-entry must be labeled separately in the ledger.

## 6. Dynamic Exit Shadowing

For every adaptive fill, calculate and log three exit paths:

### A. Frozen baseline
- +1.5% target
- -1.5% initial stop

### B. Dynamic Staircase
- +0.75% reached -> protect break-even
- +1.00% -> protect +0.25%
- +1.50% -> protect +0.75%
- +2.00% -> protect +1.25%
- +3.00% -> protect +2.00%
- above +3.00% -> trail 1.00 percentage point behind peak

### C. 65% Peak-Profit Retention
- initial stop -1.5%
- activate after +1.0%
- protected profit = 65% of maximum favorable excursion
- stop may tighten but never loosen

Until enough PAPER evidence exists, one configured adaptive exit may control the actual paper order while all other exits run as shadow calculations. The report must compare all three on identical entries.

## 7. Logging — Mandatory

Persist every stage, including zero-trade days.

For every scanned event:
- timestamp
- symbol
- earnings date/time
- gap
- EPS surprise
- revenue surprise
- guidance features
- transcript features
- premarket features
- liquidity/spread
- mechanical score
- LLM score
- component confidence scores
- final calibrated/raw confidence
- contradictions
- candidate/skip decision
- exact reason
- strategy version

For every order:
- arm: BASELINE or ADAPTIVE
- leg: opening or retracement
- intended entry
- actual fill
- slippage
- stop
- exit method
- high-water mark
- MFE
- MAE
- exit
- realized P&L
- capture ratio
- cancellation/rejection/error details

## 8. Nightly Reconciliation

Every trading day must create a canonical daily artifact even if there are zero trades.

Required sections:
- events scanned
- candidates
- baseline trades/P&L
- adaptive trades/P&L
- candidate funnel by rejection/penalty reason
- actual fills
- missed fills
- opening-leg results
- re-entry results
- baseline vs staircase vs 65%-retention counterfactual
- best achievable result under approved replay assumptions
- execution errors
- strategy lessons
- cumulative confidence calibration

A zero-row or missing report is a system failure and must alert explicitly.

## 9. Observability Watchdogs

Fail loudly if any of these are missing:
- morning readiness artifact
- event scan record
- decision ledger
- broker/order reconciliation
- end-of-day daily review

Do not report "0 trades" when telemetry is absent. Report "INCOMPLETE / OBSERVABILITY FAILURE."

## 10. Research Discipline

The adaptive arm is intentionally more permissive, but the baseline remains frozen.

Promotion criteria:
- improved out-of-sample expectancy
- acceptable drawdown
- robustness to slippage/spread
- stable parameter neighborhoods
- no dependence on a few outliers
- performance by confidence bucket is monotonic enough to justify confidence control
- successful live PAPER shadow period

## Immediate implementation priority
1. Preserve TC-BASELINE untouched.
2. Add TC-ADAPTIVE-v2 as a separate paper arm.
3. Convert gap/alignment vetoes into confidence features in adaptive arm.
4. Add confidence-weighted retracement and paper allocation.
5. Add opening-momentum + retracement re-entry.
6. Add dynamic-exit shadow calculations.
7. Make the immutable execution journal mandatory.
8. Make nightly reconciliation mandatory and fail loudly on missing telemetry.
