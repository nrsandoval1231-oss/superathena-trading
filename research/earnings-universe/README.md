> **RESEARCH REFERENCE — isolated component.** Governing product architecture: [Athena Trading Canon](../../docs/ATHENA_TRADING_CANON.md). This historical scaffold does not establish current product or broker readiness; see the repository implementation status and audit.

# Stock Universe Screener

Research tooling only — this project never executes trades. It builds a ranked
list of tickers most likely to have a **4–12% absolute next-day move after an
earnings report**, based on ~5 years of earnings history.

`universe_screener.py` is a single, self-contained, one-shot script. It does not
import from or modify any trading-bot files. The paper earnings arm does not
import this script either. An operator copies `logs/universe_75.txt` to the
path in `ATHENA_EARNINGS_UNIVERSE`. See [EARNINGS_PAPER.md](../../docs/EARNINGS_PAPER.md).

## What it does

1. **Seed pool** — scrapes current S&P 500 and S&P 400 constituents (ticker +
   GICS sector) from Wikipedia, adds any tickers in `logs/curated_tickers.txt`,
   dedupes, and normalizes symbols for yfinance (`BRK.B` → `BRK-B`).
2. **Per-ticker measurement** (via `yfinance`):
   - `get_earnings_dates()` for ~5 years of past reports (future/scheduled dates
     skipped).
   - ~5.5 years of daily OHLC.
   - For each past report, the reaction is the **percent change from the last
     daily close _before_ the report timestamp to the first daily close
     _after_ it**, absolute value. Daily closes are stamped at 16:00
     America/New_York, so before-open (BMO) and after-close (AMC) reports are
     handled correctly without classifying them.
   - A report is a **hit** if the absolute move is between 4% and 12% inclusive.
   - Tickers with fewer than 12 usable reports are skipped and logged.
3. **Filters** (applied before ranking):
   - Market cap in **[$2B, $75B]**.
   - Average daily dollar volume (`close × volume`, ~3-month average) **> $50M**.
   - Exclude GICS sectors **Utilities** and **Real Estate**.
   - Within **Financials**, exclude industries containing **"Banks"**.
   - Exclude industry **"Biotechnology"** unless TTM revenue **> $500M**.
   - Any ticker with missing required data is skipped and logged — never guessed.
4. **Scoring** — primary rank is `band_hit_rate = hits / usable_reports`;
   tiebreaker is the median absolute earnings move. Fully direction-agnostic
   (−6% counts the same as +6%).
5. **Selection** — sort survivors by score, then walk the list applying a
   **max 15 tickers per GICS sector** cap until **75** are selected.

## Outputs (written to `logs/`)

| File | Contents |
|------|----------|
| `universe_scored.csv` | **All** scored tickers: `ticker, sector, industry, market_cap, avg_dollar_volume, usable_reports, hits, band_hit_rate, median_abs_move, selected` |
| `universe_75.txt` | The 75 selected tickers, one per line, no header |
| `universe_skipped.txt` | Skipped tickers with one-line reasons |
| `screener_checkpoint.json` | Resume checkpoint (safe to delete to force a fresh run) |

## Running

Uses only `yfinance` and `pandas` (no API credentials — yfinance needs none).

```bash
# 1. Offline logic validation — no network required
python universe_screener.py --selftest

# 2. Verbose 5-ticker sanity check (prints every per-report move)
python universe_screener.py --smoke

# 3. Full run (~900 tickers, 30–60+ min; resume-safe, checkpoints every 25)
python universe_screener.py

# 3b. Full run on a datacenter/VPS IP — slower jittered pacing to dodge rate limits
python universe_screener.py --sleep 2 --jitter 1

# Rebuild the CSV/TXT outputs from an existing checkpoint without re-fetching
python universe_screener.py --rebuild-outputs
```

The full run is **resume-safe**: progress is checkpointed to
`logs/screener_checkpoint.json` every ~25 tickers, and a restart skips
already-processed tickers. When finished it prints the top-20 scored rows and
the sector breakdown of the selected 75.

### Pacing (`--sleep` / `--jitter`)

Between tickers the script waits `uniform[sleep, sleep+jitter]` seconds.
Defaults `--sleep 0.5 --jitter 0.5` (0.5–1s) are fine from a residential IP.
Yahoo throttles **datacenter/VPS IPs** more aggressively, so on a VPS raise the
pacing, e.g. `--sleep 2 --jitter 1` (2–3s). If you still hit
`Too Many Requests`, the script backs off ~30s and retries, and the checkpoint
lets you re-run to resume — but a higher `--sleep` avoids the bans up front.

### yfinance version note

The task environment pins an older yfinance where `fast_info.get()` fails
silently. This script therefore reads `fast_info` via **bracket access only**
(`fi["marketCap"]`), wrapped in a helper that treats any lookup failure as
"missing". It was developed/validated against yfinance 0.2.51 as well.

## Network requirement (important)

The screener needs outbound HTTPS to **`en.wikipedia.org`** (constituent lists)
and **`query1/query2.finance.yahoo.com` / `fc.yahoo.com`** (yfinance backend).

In a restricted/egress-filtered environment those hosts may be blocked (the
proxy returns `403`), in which case every ticker is skipped with
`no price history` and the outputs come back empty. Run in an environment whose
network policy allows Wikipedia and Yahoo Finance. The script's pure logic is
fully validated offline via `--selftest` (30 checks covering the reaction math,
BMO/AMC/16:00 boundaries, band edges, filters, scoring, and the sector cap).
