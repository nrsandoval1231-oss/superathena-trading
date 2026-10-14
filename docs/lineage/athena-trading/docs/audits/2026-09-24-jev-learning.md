# Repository audit and Jev/learning repair

Date: 24 September 2026. Baseline: remote PR #18 at `2476e6b5dee38f9ac7ce5b65c9a2e6d7a702362f`. Exact tested repair revision is recorded in [implementation status](../IMPLEMENTATION_STATUS.md). The deployment row below is this audit's finding. It is not the 10 October 2026 Hostinger paper-pilot install.

**Verdict:** the bounded paper path now has one model, broker-grounded experience feedback and a prospective learning gate. The local repository gate is repaired. On this date, cloud activation and a demonstrated trading edge were unverified; the complete dual-strategy product is not finished.

## Scope and method

Repository-wide inventory covered all 303 baseline tracked files; 205 tracked Python files parsed successfully. Reviewed product authority, active execution/data/risk/persistence/model boundaries, learning integration, deployment, tests and retained research interfaces. Ran the root and separately packaged Astra suites plus repo-wide Ruff. Compared 77 protected AAT source/config/data/history/diagram files byte-for-byte against the baseline; none changed.

The deep behavioral review focused on code that can submit/manage paper orders or influence future decisions. Historical findings were traced to retained components and labeled separately. This is not a claim that every possible execution path, external dependency or operating environment has been exhaustively proven.

## Findings and dispositions

| Finding | Evidence / consequence | Disposition |
|---|---|---|
| Two-model path no longer matches owner direction | Terra/Ollama add generation and credentials to a bounded candidate decision | Removed from active code, CLI and cloud secret template; Jev now decides directly |
| Recorded trades never inform later decisions | Previous context contained empty lessons; no active outcome-to-context path | Broker-reconciled experience store, context retrieval, nightly candidate/validation/promotion path implemented |
| Cleanup could use a different account | CLI error cleanup could call flatten outside the tick's account-binding check | flatten_step now checks the account/policy binding before any broker cleanup; regression test verifies zero calls |
| Journal hash chain accepts tail deletion | Removing the last valid row leaves a valid prefix | Durable sidecar checkpoint detects tail loss/missing anchor; crash-gap recovery tested |
| Stop coverage counts original quantity | A partially filled stop could appear to protect its full original size | Compare remaining stop quantity to confirmed position quantity |
| Account status can change during inference | Post-decision gate checked block flags but omitted ACTIVE status | Recheck status immediately before reservation/submission |
| Old demo can place broker orders outside current lifecycle | Synthetic/recorded walker can submit via --submit-demo | Broker submission retired in that CLI; fixtures and read-only preflight retained |
| Local repository gate broken/incomplete | Baseline 31 Ruff findings; Astra's workflow test refers to removed file | Unused code/import cleanup; both packages run in existing CI; 657 + 158 local tests pass |
| Broad product capabilities remain absent | Earnings integration, full APDE, full forecasting and general Core integration are incomplete | Explicitly retained as build gaps; no completion claim |
| Deployment evidence absent | No cloud/provider credentials; previous console access unavailable | Not deployed; no inference/order or performance result claimed |

The checkpoint is local, not tamper-proof against someone able to rewrite both artifacts. Old unanchored journals establish a checkpoint only on first verified migration read. The repair does not establish the integrity of earlier missing external datasets or old research snapshots.

## Learning review

A completed trade must reconcile broker entry/exit quantities and prices and bind to its decision receipt. No-fill/partial-fill episodes are kept, but do not train automatic rules. Net fees are unknown; gross paper P&L is explicitly labeled. Available broker position samples may produce sampled excursions; complete market-path MFE/MAE is not asserted.

Immediate retrieval uses already observed, matching account/symbol/direction/policy/question experience. A nightly candidate must pass a fixed 20-episode discovery screen; validation uses 20 separate entries strictly after candidate registration. Reusing a retrospective split fails the test. Failed hypotheses remain recorded. Promoted rules only veto a matching setup for 14 days. A fixture test verifies that promotion changes the actual pilot's next decision, with no broker submission or extra model call.

This is a bounded initial operating experiment, not proof of profitable self-improvement. Statistical dependence, fees, regime changes and selection effects remain limitations. Full counterfactual replay and model/code training are not implemented. See [LEARNING.md](../LEARNING.md) for prospective criteria and exact scope.

## Cleanup and preservation

Removed the two active generative model classes and their obsolete generation tests, simplified the runner/supervisor and credentials, deleted the unreferenced backtesting placeholder, refreshed the single canonical documentation path, repaired imported lint issues, and stopped the stale demo broker route. Added ignores for local trading databases and secret environment files.

Kept research files with imports, tests, receipts or provenance references. No bulk deletion or relocation of frozen evidence. Historical AT-01/02 research integrity and AT-04/05 Astra execution/persistence defects remain open before reuse; the active runner does not import those implementations. Historical library walker AT-03/07 is not repaired into a second runtime. This avoids multiplying competing execution stacks.

## Verification and operating limits

Local: 657 root tests; 158 Astra tests; repo-wide Ruff 0.15.8 clean; installer shell syntax and diff whitespace clean. Source/config provenance checks pass. On this date, remote CI success, systemd startup, broker authentication, model quality, backup restore, alert delivery and actual live paper outcomes had not been verified.

On this date, no cloud resources were provisioned, no provider inference was performed, no messages were sent, real-money authority stayed disabled, and no frozen experiment was rerun. The deliverable is the reviewed code/documentation candidate and its local verification evidence.
