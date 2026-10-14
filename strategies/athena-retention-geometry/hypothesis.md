# Falsifiable hypothesis

## Claim

For the same eligible earnings-reaction entries, fills, quantity, initial -1.5% risk, and causal execution assumptions, a post-entry peak-retention stop activated at +1% will improve net expectancy per filled event after modeled execution costs versus the unchanged `TC-BASELINE` +1.5% target/-1.5% stop. `ARG-65` and `ARG-75` are separate candidates; neither is presumed superior.

The test is about exit mechanics only. Confidence admission, confidence-based sizing, opening-momentum capture, and retracement re-entry are separate hypotheses and are excluded from this comparison.

## Predeclared comparison

Freeze the candidate definitions before evaluation. Use paired events and identical entry eligibility, timing, price, quantity, initial risk, costs, trade/quote data, latency, quote-validity rules, queue assumptions, and flattening rule. Compare:

1. `TC-BASELINE`: fixed +1.5% target and -1.5% stop.
2. `ARG-65`: -1.5% initial stop; after +1% post-entry favorable return, retain 65% of the post-entry peak; no fixed target cap.
3. `ARG-75`: the same, retaining 75%.

Evaluate paired net-R difference, absolute net expectancy, outcome distributions, date-cluster uncertainty, long/short and gap strata, coverage/ambiguity counts, and sensitivity to declared execution latency and costs. Preserve exclusions and unresolved ordering in the denominator. Do not tune the retention fraction, activation threshold, or exit grid after viewing outcomes; do not claim an edge from the prior-bar proxy or from a non-held-out sample.

## Falsification and evidence boundary

The hypothesis is not supported if neither candidate improves the predeclared primary metric robustly across declared cost/path/period sensitivities, if the improvement depends on a small number of outliers, or if causal quote/fill coverage is insufficient. A stop trigger is not a guaranteed fill, and modeled costs are not observed costs. Gaps, halts, partial fills, cancellation races, and missing quotes can exceed planned risk.

No implementation, paper order, live order, or promotion is authorized by this document. Runtime tests remain pending implementation; no tests are claimed as passed for this specification.
