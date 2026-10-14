# GDELT News Source Provenance

Status: parser built and fixture-tested; bounded coverage study complete and
GDELT rejected for the current AAT-V2 run. Archive files and normalized pilot
records remain in disposable ignored temp storage only. No news-effect claim
has been made.

## Source and historical boundary

The selected source is the public GDELT 2.0 Global Knowledge Graph (GKG). The
official DOC API is useful for recent searches, but its precise date search is
limited to the recent rolling window described by the source documentation; it
is not treated as a complete 2024–2025 backfill mechanism.

Historical data is available as 15-minute GKG archive files under the official
GDELT data host. A 12-slice 2025 study requested one 14:30 UTC archive per
month, retrieved 11 slices, and recorded one HTTP 404 without substituting a
date. The retrieved slices contained 18,888 valid 27-field rows and zero
malformed rows.

Sources:

- https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/
- https://www.gdeltproject.org/data.html
- https://data.gdeltproject.org/gdeltv2/lastupdate.txt

## Parser contract

`src/athena_trading/exogenous/gdelt.py` maps one GKG row through
`parse_gkg_row(raw, symbol=...)`.

The caller must supply the symbol. The parser does **not** infer ticker identity
from free-text organizations, people, themes, or URLs. Entity matching is a
separate, reviewable step.

The parser preserves:

- GKG record id
- GKG timestamp
- source domain
- source URL
- themes
- people
- organizations
- tone vector

The GKG timestamp is parsed as UTC and used as both `event_at` and
`available_at`. This is deliberately conservative about the source contract:
it means the record was observed by GDELT at that timestamp. It does not claim
that the publisher's internal publication clock is known or that the article
was first seen by the market at exactly that instant.

The stable identity is:

```text
gdelt:{gkg_record_id}:{symbol}
```

Malformed field counts, timestamps, URLs, symbols, and tone values fail closed.

## Bounded coverage result

The study used only exact organization-token mappings:

```text
microsoft -> MSFT
nvidia -> NVDA
```

It produced 245 normalized news records. Against the 16,705-opportunity
TRAINING index, only 13 opportunities (6 MSFT and 7 NVDA) had `news_present`
within the frozen overnight/premarket compressor window: **0.0778% coverage**.
The record store remained outcome-free and carried `execution_authority:
ABSENT`.

This is a source-selection result, not a claim about GDELT's global quality.
The mapping is too narrow and the measured coverage is too thin to justify a
full 2024–2025 archive acquisition. GDELT is not adopted for the current run;
news must remain explicitly missing unless a future provider supplies stable
historical entity IDs and defensible point-in-time coverage.

## What this source does not establish

- It does not establish complete historical coverage.
- It does not establish first-publication time at the publisher.
- It does not establish entity identity from a ticker string alone.
- It does not justify downloading the full archive without a bounded extraction
  plan and storage/time review.
- It does not freeze an AAT-V2 claim contract or protocol.
