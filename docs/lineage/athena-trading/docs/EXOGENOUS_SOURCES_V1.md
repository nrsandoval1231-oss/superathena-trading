# Exogenous Source Specification V1

Companion to `docs/AAT_V2_VISION.md` and `docs/AAT_V2_PLAN.md`. This resolves
the "which exogenous sources" open decision: **all six categories TradingAgents
uses**, tiered by what they are actually worth to an intraday ORB decision and
graded by whether their point-in-time provenance can be defended.

Status: EVIDENCE-GATED. The ALFRED macro adapter and GDELT GKG parser are
fixture-tested; see `docs/ALFRED_MACRO_SOURCE_PROVENANCE.md` and
`docs/GDELT_NEWS_SOURCE_PROVENANCE.md`. The 35-symbol TRAINING campaign has
an outcome-free opportunity index and macro snapshot. GDELT passed parser
validation but failed the bounded coverage study and is not adopted. No V2
claim contract is frozen for a macro-only surface; no protocol is registered
and no V2 claim is authorized.

## The decision moment shapes everything

TradingAgents evaluates daily-horizon decisions, so its data surface is built
for a daily cadence. ORB-M is not that. The decision moment is **09:45 ET**,
when the 15-minute opening range freezes and the first one-minute close can
trigger. Positions are flat by 15:45 ET and hard-flat by 15:59 ET.

That single fact re-ranks their entire source list:

- The relevant evidence window is **prior session close → 09:45 ET**. Overnight
  and pre-market catalysts are the whole game.
- A fundamentals *value* is nearly worthless at 09:45. The fundamentals *event*
  — "this name reported after yesterday's close" — is one of the strongest gap
  catalysts there is.
- Macro matters as a scheduled-event flag: an 08:30 ET print lands 75 minutes
  before the decision and sets the tone for the opening range.
- Sentiment matters as *velocity in the pre-market window*, not as a standing
  level.
- Polymarket, which they list, has essentially no single-name equity coverage.
  It is in this spec for completeness and lands in Tier 3.

## Correction to my earlier read

In the vision doc's open decisions I ranked social sentiment as the worst
point-in-time provenance of the set. That was wrong and it changes the build
order, so stating it plainly:

**Fundamentals is the worst provenance risk, not sentiment.** A Reddit or
StockTwits post has a real, immutable publication timestamp — `created_utc` is
genuinely the moment the content became observable, which is exactly the
`available_at` semantics we need. Social's problems are retrieval, coverage
bias and deletion survivorship: real, but tractable and measurable.

Fundamentals has a different and worse problem. Most affordable fundamentals
APIs serve a *current view* — the latest restated figures, silently
backfilled over the original filings. A backtest that reads them is looking at
numbers that did not exist on the decision date, and nothing in the response
tells you that. It is the one source here that leaks by default and looks fine
while doing it.

## Tiering

| Tier | Sources | Rationale |
| --- | --- | --- |
| 1 | News, Macro | High ORB relevance, defensible point-in-time, buildable now |
| 2 | StockTwits, Reddit, Fundamentals (event-only) | Real signal, real caveats, needs measurement before trust |
| 3 | Polymarket | Near-zero single-name coverage; included for breadth parity only |

Build Tier 1 first. Tier 2 enters only after its coverage and bias are measured
by the Phase 1 coverage script. Tier 3 is a stub that proves the contract
generalizes.

---

## Tier 1

### News

**What it is.** Headlines and story metadata for the 50-name frozen universe,
windowed prior close → 09:45 ET.

**Point-in-time mechanism.** Publication timestamp from the wire. The trap is
that many news APIs re-timestamp on backfill or serve the story's *update*
time. The ingest must capture first-seen publication time and reject records
whose timestamp changes between pulls.

**Candidate sources.** GDELT (free, real event timestamps, global, noisy);
a commercial wire archive if budget allows. Whichever is chosen, provenance
gets documented the way `docs/HISTORICAL_SOURCE_PROVENANCE.md` documents bars.

**Compressed features.** Item count in the overnight window; item count in the
pre-market window; scheduled-event flag; coverage density relative to the
symbol's own trailing baseline; time since most recent item, bucketed.

**Known biases.** Coverage is far denser for large caps and for names that
subsequently moved — the classic exogenous survivorship channel. Coverage
density is itself emitted as a feature so its effect stays measurable rather
than hidden.

**Grade: rejected for this run.** The bounded 2025 study retrieved 11 of 12
monthly slices and produced only 13 news-present opportunities out of 16,705
(0.0778%) under the frozen overnight/premarket compressor window. The exact
entity mapping covered only `microsoft → MSFT` and `nvidia → NVDA`; the full
archive is not justified without a source with stable historical entity IDs.

### Macro

**What it is.** Scheduled macro releases and their surprise, as a market-wide
(`symbol: None`) record.

**Point-in-time mechanism.** FRED's ALFRED vintage archive is the correct tool
and the best-solved provenance problem in this entire spec. ALFRED serves each
series *as it stood on a given date*, including the original print before
revision. Free, documented, and exactly the as-of semantics the contract wants.

**Compressed features.** Scheduled-release-today flag; minutes since the most
recent release at 09:45; surprise bucket against consensus where available;
release-category flag.

**Known biases.** Consensus expectations are not in ALFRED and must come from a
separate source with its own timestamp discipline. If a defensible consensus
series cannot be sourced, ship the release-event flags without the surprise
bucket rather than guessing.

**Grade: A.** Use ALFRED vintages, never the current-view FRED series. The
adapter is `alfred_adapter` in `src/athena_trading/exogenous/alfred.py`. The
training snapshot contains 16,705 rows with measured macro coverage of 1.0;
this remains evidence coverage, not a predictive claim.

---

## Tier 2

### StockTwits

**What it is.** Per-message stream for the universe, with the platform's own
bullish/bearish tags where the author set one.

**Point-in-time mechanism.** Message `created_at`. Genuinely point-in-time —
the post existed at that instant and was visible from that instant.

**Compressed features.** Message volume in the pre-market window vs. the
symbol's trailing baseline; tagged bull/bear ratio; message velocity in the
final 15 minutes before 09:45; unique-author count, bucketed.

**Known biases.** Heavy small-cap and meme concentration; promotional and bot
accounts; deleted messages create survivorship in any archive rebuilt after the
fact. Author-level deduplication is required or a single prolific poster
becomes a signal.

**Grade: B.** Timestamps are sound. Signal quality is the question, not
provenance.

### Reddit

**What it is.** Submissions and comments mentioning universe tickers, from the
finance subreddits.

**Point-in-time mechanism.** `created_utc`, which is immutable and correct.

**Retrieval reality — this is the real constraint.** Pushshift no longer
operates a public API; it lost privileged ingestion after Reddit's 2023 API
changes and the dumps stopped. Historical access in 2026 runs through
Arctic Shift, Academic Torrents bulk archives, or Reddit's own researcher
program. All are frozen or bulk archives rather than live APIs, which is fine
for a backtest and useless for anything live later.

**Compressed features.** Mention count vs. trailing baseline; comment velocity;
unique-author count; subreddit-concentration flag. All bucketed.

**Known biases.** Deleted and removed content is missing from archives rebuilt
later, and removal correlates with exactly the promotional activity that
precedes a move — a genuine survivorship channel, and the strongest argument
for treating Reddit features as suspect until measured.

**Grade: B–.** Correct timestamps, awkward retrieval, real survivorship.

### Fundamentals — event only

**What it is.** Deliberately narrowed. Not the financial values: the **filing
event**. Did this name report after yesterday's close or before this morning's
open, and how far is it from its next scheduled report.

**Point-in-time mechanism.** Filing timestamp, not period end. The two are
weeks apart and conflating them is the leak. A provider that serves as-reported
figures time-indexed to their release date — Sharadar's as-reported dimensions,
Calcbench's as-filed capture with its revision history, LSEG's point-in-time
product at the expensive end — is required. A current-view REST API that leans
toward latest figures is disqualified regardless of price, because enforcing
the reporting lag becomes undetectable manual work bolted on afterward.

**Why event-only.** At 09:45 on an intraday breakout, the EPS number is not
what the tape is reacting to. "Reported 16 hours ago" is. Narrowing to the
event sidesteps the restatement problem almost entirely while keeping the part
that matters for this strategy.

**Compressed features.** Reported-since-last-close flag; hours since filing,
bucketed; days to next scheduled report, bucketed; guidance-issued flag.

**Known biases.** Scheduled report dates are themselves revised. Only the
schedule as known at the decision date may be used, which means capturing the
calendar's own vintage.

**Grade: C+ as values, B+ as events.** The narrowing is what makes it usable.

---

## Tier 3

### Polymarket

**What it is.** Prediction-market prices on macro and event outcomes.

**Point-in-time mechanism.** On-chain trades with real block timestamps.
Provenance is excellent.

**The problem.** Single-name equity coverage is close to nonexistent. Available
markets are macro, political and rate-path questions, which is at best a
duplicate of the macro source and at worst noise on an intraday horizon.

**Compressed features.** If built at all: implied probability on any active
macro market at 09:45, bucketed, as a market-wide record.

**Grade: A for provenance, D for relevance.** Implemented as a stub that
exercises the market-wide record path and proves the contract generalizes
beyond equities. Not expected to carry signal.

---

## What this changes in the plan

Phase 1 of `docs/AAT_V2_PLAN.md` gains a per-source ingest step, each
independently receipted, with compression staying pure and offline. The four
analyst compressors map to categories rather than one per vendor, so a source
swap inside a category does not change the feature key set.

The order is: **Macro and News (Tier 1) → coverage measurement → Tier 2 if
coverage clears the floor → Polymarket stub.** In the current run macro
cleared the evidence gate and GDELT news did not, so news remains explicitly
missing rather than being represented by a misleading thin panel.

Two things must exist before Phase 3 registers any protocol:

1. A provenance document per adopted source, to the standard of
   `docs/HISTORICAL_SOURCE_PROVENANCE.md`.
2. A measured coverage rate per source across the frozen 50-name universe, with
   the floor frozen into the V2 contract rather than discovered afterward.

## Sources consulted

- [How to Get Historical Reddit Data After Pushshift (2026)](https://www.xpoz.ai/blog/tutorials/how-to-get-historical-reddit-data-after-pushshift/)
- [Pushshift Alternative 2026 (PullPush, Arctic Shift)](https://think-pol.com/pushshift-alternative)
- [Reddit Data API in 2026: How to Get Access and Alternatives](https://www.redditapis.com/blogs/reddit-data-api-2026)
- [Calcbench — Point-In-Time Fundamental Data](https://www.calcbench.com/blog/post/153949139113/point-in-time-fundamental-data)
- [LSEG — Point in Time Fundamentals](https://www.lseg.com/en/data-analytics/financial-data/company-data/fundamentals-data/point-in-time-fundamentals)
- [Point-in-Time Fundamentals Are a Data Model, Not a CSV](https://theretailquant.cc/research-methods/point-in-time-fundamentals-are-a-data-model)
- [Financial Modeling Prep vs Sharadar for Quant Backtests](https://pickuma.com/for-dev/financial-modeling-prep-vs-sharadar-fundamental-data-api/)
