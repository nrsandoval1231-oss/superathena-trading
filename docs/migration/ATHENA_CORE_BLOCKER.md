# Athena Core blocker

Requested source: https://github.com/nrsandoval1231-oss/Athena

Requested anchor: `adba694563751256f5f5e95ad47079b37c7697ec`

Observed on 14 October 2026:

```text
git ls-remote https://github.com/nrsandoval1231-oss/Athena.git HEAD
remote: Repository not found.
fatal: repository 'https://github.com/nrsandoval1231-oss/Athena.git/' not found
```

The GitHub API returned 404 for that repository. The same result was returned for the lowercase name `athena` and for `athena-core`. No commit, tree, or file list was available, so none was fabricated.

What still moved: the trading-specific adapter already stored in `athena-trading` at the trading anchor. That adapter documents that Core must not import market, broker, ticker, ORB, or PnL types from this repository, and it keeps a byte-compatible `canonical_hash` so trading does not take a private Core build dependency for one function.

What did not move: Arena, Gauntlet, policy genome, and any other Core module that exists only in the unreadable repository. Those remain an external dependency until the repository can be read at the anchor.
