# Strategy archive provenance

Archived October 14, 2026. Scope: strategy documents only, not a data archive or an executable trading integration. The working name is Athena Retention Geometry; original TC identifiers remain authoritative historical labels.

## Preserved documents

| Document | Source SHA-256 | Archived SHA-256 | Treatment |
|---|---|---|---|
| `references/TC_Paper_v2_Adaptive_Trade_Geometry.md` | `55ddc292522ce6357690e406150429dd5307f59cdc671c322baa88bbbb11b727` | `55ddc292522ce6357690e406150429dd5307f59cdc671c322baa88bbbb11b727` | Byte-identical historical paper design, dated August 21, 2026 |
| `references/TC_Adaptive_Trade_Geometry_Refinement_2026-10-14.md` | `6b6d7d2b157a37e66d741778b934f93e86b86af109d25908105eb98e049e8eaa` | `b7213d27c7aefa1bbe738864dfb8618c2ce0fcade1f187a917fe56810712937a` | Only the source-location paragraph was replaced with a location-free equivalent; strategy content preserved |

The historical paper's “Approved for PAPER implementation” status is an archived statement, not an approval of an implementation in this repository. Its allocation bands are conceptual paper limits, not live allocations. The October refinement is a proposal, not a promoted policy. Neither replaces the frozen baseline.

## Baseline source identity

The inspected source declares `tc-33-dual-surprise-v4-2026-08-13`. Hashes below identify the source files captured on October 14, not an independently established historical deployment commit. The source files themselves are not part of this documents-only commit.

| Source file | SHA-256 |
|---|---|
| `config.py` | `32112c7d7d17e518ea44cf581a310120c09eea69f3f195b31fb37160ca1114ea` |
| `core.py` | `4128998b6afb745dbd38d3e36011fd1247ad031aa6d4abac0cb19c21dfcdc074` |
| `data.py` | `c73fc8146b3351239ca980eb7586bf66cf7c704997173330ca84b9e418d1cb2a` |
| `runner.py` | `e4334b6d6a1d25c257987de2e13cf1d593776bef12c0b0383717a18a15723636` |

The frozen control uses the first qualifying SIP trade that updates the daily open, not necessarily the exchange auction print. The original paper's phrase “official gap” must be read with this implementation distinction. The current spec documents that distinction rather than editing historical evidence.

## What is deliberately not uploaded

- Raw provider minute bars, trades or quotes, and other datasets whose redistribution rights are not established.
- Research result datasets, per-event ledgers, raw or sanitized forward-session journals, and broker order/fill records.
- Credentials, environment files, API probes, machine/server identifiers, account IDs and private filesystem locations.
- A runnable broker adapter, production policy, Actions workflow, or trading authorization.

These exclusions apply to this commit only. Existing local research artifacts remain untouched. Private repository visibility would not itself grant data redistribution rights.

## Evidence status

65% and 75% retention remain hypotheses selected from exploratory minute-bar research. That research used assumed within-minute paths and lacked complete TC screening/execution evidence. Actual-tape replay is pending historical trade/quote access and broker reconciliation. No raw dataset or numerical performance claim is imported here, and no repository-runtime test success is asserted for this specification-only archive.

Future implementation must add deterministic strategy tests, pin its data and execution conventions, satisfy repository risk controls, and obtain the required independent review and explicit authorization before promotion. The detailed execution adapter remains to be frozen before a tick replay; unresolved spread, queue, latency and fill assumptions must not be silently chosen after results are viewed.
