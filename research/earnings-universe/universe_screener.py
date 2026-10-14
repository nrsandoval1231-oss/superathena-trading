#!/usr/bin/env python3
"""
universe_screener.py — one-shot stock universe screener (research tooling only).

Goal
----
Produce a ranked list of 75 tickers most likely to have a 4-12% ABSOLUTE
next-day move after an earnings report, based on ~5 years of earnings history.

This script never trades. It only reads public data (S&P constituents from
Wikipedia, prices/earnings from yfinance) and writes CSV/TXT reports.

Seed pool
---------
  * S&P 500 constituents (Wikipedia "List of S&P 500 companies")
  * S&P 400 constituents (Wikipedia "List of S&P 400 companies")
  * Extra tickers from logs/curated_tickers.txt
Deduped and normalized for yfinance (BRK.B -> BRK-B).

Per-ticker measurement
----------------------
  1. get_earnings_dates() -> ~5y of past reports (future/scheduled dates skipped).
  2. ~5.5y of daily OHLC.
  3. For each past report, reaction = pct change from the LAST daily close BEFORE
     the report timestamp to the FIRST daily close AFTER it (absolute value).
     Daily closes are stamped at 16:00 America/New_York so BMO/AMC reports are
     handled without explicit classification.
  4. "hit" = 4% <= abs move <= 12%.
  5. Require >= 12 usable reports, else skip and log.

Scoring
-------
  primary : band_hit_rate = hits / usable_reports   (higher better)
  tiebreak: median absolute earnings move            (higher better)

Filters (before ranking)
------------------------
  * market cap in [$2B, $75B]
  * avg daily dollar volume (~3mo, close*volume) > $50M
  * exclude GICS sectors Utilities, Real Estate
  * exclude Financials whose industry contains "Banks"
  * exclude industry "Biotechnology" unless TTM revenue > $500M
  * any ticker with missing required data is skipped and logged (never guessed)

Final selection
---------------
  Sort survivors by score, then walk the list applying a sector cap of 15 per
  GICS sector until 75 tickers are selected.

Outputs (under logs/)
---------------------
  universe_scored.csv   all scored tickers + `selected` flag
  universe_75.txt       the 75 selected tickers, one per line
  universe_skipped.txt  skipped tickers, one-line reasons

Run
---
  python universe_screener.py --selftest   # offline logic checks, no network
  python universe_screener.py --smoke       # verbose 5-ticker sanity check
  python universe_screener.py               # full run (resume-safe)

yfinance note: fast_info requires bracket access (fi["marketCap"]); .get() can
fail silently on some versions, so this script never uses fast_info.get().
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
from io import StringIO
from statistics import median

import pandas as pd

# ----------------------------------------------------------------------------
# Paths / constants
# ----------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(BASE_DIR, "logs")

CURATED_FILE = os.path.join(LOGS_DIR, "curated_tickers.txt")
CHECKPOINT_FILE = os.path.join(LOGS_DIR, "screener_checkpoint.json")
SCORED_CSV = os.path.join(LOGS_DIR, "universe_scored.csv")
SELECTED_TXT = os.path.join(LOGS_DIR, "universe_75.txt")
SKIPPED_TXT = os.path.join(LOGS_DIR, "universe_skipped.txt")

SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
SP400_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies"
WIKI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) universe_screener/1.0 "
        "(research tooling; contact: local user)"
    )
}

# Measurement / filter parameters
MOVE_LOW = 4.0                 # % — inclusive lower band
MOVE_HIGH = 12.0               # % — inclusive upper band
_BAND_EPS = 1e-9               # tolerance so exact 4.0/12.0 boundaries count
MIN_USABLE_REPORTS = 12
PRICE_PERIOD = "6y"            # ~5.5y+ of daily bars
EARNINGS_LIMIT = 24           # ~6y of quarterly reports
DOLLAR_VOL_WINDOW = 63        # ~3 trading months
MIN_DOLLAR_VOL = 50_000_000.0
MKTCAP_MIN = 2_000_000_000.0
MKTCAP_MAX = 75_000_000_000.0
BIOTECH_MIN_REVENUE = 500_000_000.0
EXCLUDED_SECTORS = {"Utilities", "Real Estate"}
MARKET_TZ = "America/New_York"

SECTOR_CAP = 15
TARGET_COUNT = 75
CHECKPOINT_EVERY = 25
SMOKE_TICKERS = ["NVDA", "DECK", "CMG", "ETSY", "WSM"]

# lazy import so --selftest works without yfinance/network installed
yf = None


def _lazy_yf():
    global yf
    if yf is None:
        import yfinance as _yf  # noqa: WPS433
        yf = _yf
    return yf


# ----------------------------------------------------------------------------
# Small utilities
# ----------------------------------------------------------------------------
def log(msg: str) -> None:
    print(msg, flush=True)


def normalize_ticker(sym: str) -> str:
    """Normalize a raw symbol for yfinance (e.g. BRK.B -> BRK-B)."""
    return str(sym).strip().upper().replace(".", "-")


def fast_info_value(fast_info, key):
    """Read a fast_info field via bracket access only.

    yfinance's fast_info .get() can fail silently on some versions, so we use
    __getitem__ and treat any lookup failure as "missing" (returns None).
    """
    try:
        val = fast_info[key]
    except Exception:  # KeyError, and version-specific quirks
        return None
    if val is None:
        return None
    try:
        if isinstance(val, float) and math.isnan(val):
            return None
    except Exception:
        pass
    return val


def _retry(fn, tries=3, base_delay=1.5, what=""):
    """Call fn() with a few retries on transient errors. Returns fn() or raises."""
    last = None
    for attempt in range(1, tries + 1):
        try:
            return fn()
        except Exception as exc:  # network / rate-limit / parse
            last = exc
            msg = str(exc).lower()
            rate_limited = "too many requests" in msg or "429" in msg
            if attempt < tries:
                delay = base_delay * (2 ** (attempt - 1))
                if rate_limited:
                    delay = max(delay, 30.0)
                log(f"    retry {attempt}/{tries} for {what}: {type(exc).__name__} "
                    f"(sleeping {delay:.0f}s)")
                time.sleep(delay)
    raise last


# ----------------------------------------------------------------------------
# Seed pool
# ----------------------------------------------------------------------------
def _read_wiki_constituents(url: str, label: str) -> dict:
    """Return {normalized_ticker: gics_sector} scraped from a Wikipedia list."""
    import requests  # local import; not needed for --selftest

    def _fetch():
        resp = requests.get(url, headers=WIKI_HEADERS, timeout=30)
        resp.raise_for_status()
        return resp.text

    html = _retry(_fetch, what=f"{label} wiki fetch")
    tables = pd.read_html(StringIO(html))

    out = {}
    for tbl in tables:
        cols = {str(c).strip().lower(): c for c in tbl.columns}
        sym_col = None
        for key in ("symbol", "ticker symbol", "ticker"):
            if key in cols:
                sym_col = cols[key]
                break
        sec_col = None
        for key in ("gics sector", "gics  sector", "sector"):
            if key in cols:
                sec_col = cols[key]
                break
        if sym_col is None:
            continue
        for _, row in tbl.iterrows():
            raw = row[sym_col]
            if pd.isna(raw):
                continue
            tkr = normalize_ticker(raw)
            if not tkr or tkr in out:
                continue
            sector = None
            if sec_col is not None and not pd.isna(row[sec_col]):
                sector = str(row[sec_col]).strip()
            out[tkr] = sector
        if out:
            break  # first table with a symbol column is the constituents table
    log(f"  {label}: {len(out)} tickers")
    return out


def build_seed_pool() -> dict:
    """Return {ticker: sector_or_None} for the full deduped seed pool."""
    log("Building seed pool ...")
    pool: dict[str, str | None] = {}

    for url, label in ((SP500_URL, "S&P 500"), (SP400_URL, "S&P 400")):
        try:
            part = _read_wiki_constituents(url, label)
        except Exception as exc:
            log(f"  WARNING: failed to scrape {label}: {type(exc).__name__}: {exc}")
            part = {}
        for tkr, sector in part.items():
            if tkr not in pool or pool[tkr] is None:
                pool[tkr] = sector

    # curated tickers
    if os.path.exists(CURATED_FILE):
        n = 0
        with open(CURATED_FILE) as fh:
            for line in fh:
                sym = line.strip()
                if not sym or sym.startswith("#"):
                    continue
                tkr = normalize_ticker(sym)
                pool.setdefault(tkr, None)  # sector filled from yfinance later
                n += 1
        log(f"  curated_tickers.txt: {n} lines")
    else:
        log(f"  curated_tickers.txt: not found at {CURATED_FILE} (skipping)")

    log(f"Seed pool: {len(pool)} unique tickers")
    return pool


# ----------------------------------------------------------------------------
# Earnings reaction math (pure, unit-testable)
# ----------------------------------------------------------------------------
def _daily_close_times_utc(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Stamp each daily bar at 16:00 America/New_York and return UTC timestamps."""
    idx = pd.DatetimeIndex(index)
    if idx.tz is None:
        idx = idx.tz_localize(MARKET_TZ)
    else:
        idx = idx.tz_convert(MARKET_TZ)
    close = idx.normalize() + pd.Timedelta(hours=16)
    return close.tz_convert("UTC")


def _to_utc(ts) -> pd.Timestamp:
    ts = pd.Timestamp(ts)
    if ts.tz is None:
        ts = ts.tz_localize(MARKET_TZ)
    return ts.tz_convert("UTC")


def compute_earnings_moves(close: pd.Series, report_times, now_utc=None):
    """Compute absolute next-close reaction (%) for each past report.

    Parameters
    ----------
    close : pd.Series
        Daily close prices indexed by a DatetimeIndex (tz-aware or naive).
    report_times : iterable of timestamps
        Earnings report timestamps (any tz; naive assumed America/New_York).
    now_utc : pd.Timestamp, optional
        "Now" cutoff; reports at/after this are treated as future and skipped.

    Returns
    -------
    list of dict: {report_ts, pre_ts, post_ts, pre, post, move_pct, hit}
        One entry per USABLE report (both a prior and following close exist).
    """
    close = close.dropna()
    if close.empty:
        return []
    close_utc = _daily_close_times_utc(close.index)
    prices = close.to_numpy(dtype="float64")

    results = []
    for raw_ts in report_times:
        try:
            rts = _to_utc(raw_ts)
        except Exception:
            continue
        if now_utc is not None and rts >= now_utc:
            continue  # future / scheduled

        # last bar whose close happened at or before the report,
        # first bar whose close happened strictly after it.
        before = (close_utc <= rts).to_numpy() if hasattr(close_utc <= rts, "to_numpy") \
            else (close_utc <= rts)
        after = (close_utc > rts).to_numpy() if hasattr(close_utc > rts, "to_numpy") \
            else (close_utc > rts)
        if not before.any() or not after.any():
            continue
        pre_i = int(before.nonzero()[0][-1])
        post_i = int(after.nonzero()[0][0])
        pre = prices[pre_i]
        post = prices[post_i]
        if not (pre > 0) or not (post > 0) or math.isnan(pre) or math.isnan(post):
            continue
        move = abs(post / pre - 1.0) * 100.0
        results.append({
            "report_ts": rts,
            "pre_ts": close_utc[pre_i],
            "post_ts": close_utc[post_i],
            "pre": float(pre),
            "post": float(post),
            "move_pct": float(move),
            "hit": bool(MOVE_LOW - _BAND_EPS <= move <= MOVE_HIGH + _BAND_EPS),
        })
    return results


def score_from_moves(moves):
    """Return (usable, hits, band_hit_rate, median_abs_move) from move dicts."""
    usable = len(moves)
    if usable == 0:
        return 0, 0, 0.0, 0.0
    hits = sum(1 for m in moves if m["hit"])
    vals = [m["move_pct"] for m in moves]
    return usable, hits, hits / usable, float(median(vals))


# ----------------------------------------------------------------------------
# Filters (pure)
# ----------------------------------------------------------------------------
def passes_hard_filters(sector, industry, market_cap, dollar_vol, ttm_revenue):
    """Return (ok: bool, reason: str). reason is '' when ok."""
    if market_cap is None:
        return False, "missing market_cap"
    if not (MKTCAP_MIN <= market_cap <= MKTCAP_MAX):
        return False, f"market_cap ${market_cap/1e9:.2f}B outside [2B,75B]"
    if dollar_vol is None:
        return False, "missing dollar_volume"
    if dollar_vol <= MIN_DOLLAR_VOL:
        return False, f"avg $vol ${dollar_vol/1e6:.1f}M <= 50M"
    if sector in EXCLUDED_SECTORS:
        return False, f"excluded sector {sector}"

    ind = (industry or "").strip()
    sec = (sector or "").strip()
    if sec == "Financials" and "banks" in ind.lower():
        return False, f"big-bank industry '{ind}'"
    if ind.lower() == "biotechnology":
        if ttm_revenue is None:
            return False, "biotech w/ missing revenue"
        if ttm_revenue <= BIOTECH_MIN_REVENUE:
            return False, (f"clinical-stage biotech "
                           f"(rev ${ttm_revenue/1e6:.0f}M <= 500M)")
    return True, ""


# ----------------------------------------------------------------------------
# Final selection with sector cap (pure)
# ----------------------------------------------------------------------------
def select_with_sector_cap(scored, cap=SECTOR_CAP, target=TARGET_COUNT):
    """scored: list of dicts already sorted best-first. Returns set of tickers."""
    counts: dict[str, int] = {}
    selected = []
    for rec in scored:
        if len(selected) >= target:
            break
        sec = rec.get("sector") or "Unknown"
        if counts.get(sec, 0) >= cap:
            continue
        counts[sec] = counts.get(sec, 0) + 1
        selected.append(rec["ticker"])
    return selected


def sort_key(rec):
    # higher band_hit_rate first, then higher median_abs_move
    return (-rec["band_hit_rate"], -rec["median_abs_move"])


# ----------------------------------------------------------------------------
# Checkpointing
# ----------------------------------------------------------------------------
def load_checkpoint() -> dict:
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE) as fh:
                data = json.load(fh)
            log(f"Resuming: {len(data)} tickers already processed "
                f"(from {CHECKPOINT_FILE})")
            return data
        except Exception as exc:
            log(f"WARNING: could not read checkpoint ({exc}); starting fresh")
    return {}


def save_checkpoint(state: dict) -> None:
    tmp = CHECKPOINT_FILE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(state, fh, indent=0)
    os.replace(tmp, CHECKPOINT_FILE)


# ----------------------------------------------------------------------------
# Per-ticker processing (network)
# ----------------------------------------------------------------------------
def process_ticker(ticker: str, seed_sector, verbose=False) -> dict:
    """Process one ticker. Returns a record dict with status 'scored'|'skipped'.

    A 'scored' record has all fields required for the CSV. A 'skipped' record
    has a 'reason'. Network errors bubble up as skipped(reason).
    """
    yfin = _lazy_yf()
    rec = {"ticker": ticker, "status": "skipped", "reason": "", "sector": seed_sector}

    try:
        tk = yfin.Ticker(ticker)

        # --- price history (needed for dollar volume + reactions) ---
        hist = _retry(
            lambda: tk.history(period=PRICE_PERIOD, interval="1d", auto_adjust=True),
            what=f"{ticker} history",
        )
        if hist is None or hist.empty or "Close" not in hist:
            rec["reason"] = "no price history"
            return rec
        close = hist["Close"].dropna()
        if close.empty:
            rec["reason"] = "empty close series"
            return rec

        # --- avg daily dollar volume (~3 months) ---
        dollar_vol = None
        if "Volume" in hist:
            dv = (hist["Close"] * hist["Volume"]).dropna()
            if len(dv) >= 5:
                dollar_vol = float(dv.tail(DOLLAR_VOL_WINDOW).mean())

        # --- market cap via fast_info bracket access ---
        market_cap = None
        try:
            fi = tk.fast_info
            market_cap = fast_info_value(fi, "marketCap")
            if market_cap is not None:
                market_cap = float(market_cap)
        except Exception:
            market_cap = None

        # --- sector / industry / revenue via .info (dict .get is fine here) ---
        info = {}
        try:
            info = _retry(lambda: tk.info, tries=2, what=f"{ticker} info") or {}
        except Exception:
            info = {}
        sector = seed_sector or info.get("sector")
        industry = info.get("industry")
        ttm_revenue = info.get("totalRevenue")
        if ttm_revenue is not None:
            try:
                ttm_revenue = float(ttm_revenue)
            except Exception:
                ttm_revenue = None
        rec["sector"] = sector
        rec["industry"] = industry
        rec["market_cap"] = market_cap
        rec["avg_dollar_volume"] = dollar_vol

        # --- hard filters (fail fast, before the earnings call) ---
        ok, reason = passes_hard_filters(sector, industry, market_cap,
                                         dollar_vol, ttm_revenue)
        if not ok:
            rec["reason"] = reason
            return rec

        # --- earnings dates ---
        edf = _retry(
            lambda: tk.get_earnings_dates(limit=EARNINGS_LIMIT),
            what=f"{ticker} earnings_dates",
        )
        if edf is None or len(edf) == 0:
            rec["reason"] = "no earnings dates"
            return rec
        report_times = list(edf.index)

        now_utc = pd.Timestamp.now("UTC")
        moves = compute_earnings_moves(close, report_times, now_utc=now_utc)

        if verbose:
            log(f"    {ticker}: {len(moves)} usable reports")
            for m in moves:
                flag = "HIT " if m["hit"] else "    "
                log(f"      {flag}{m['report_ts'].date()}  "
                    f"{m['pre']:.2f} -> {m['post']:.2f}  "
                    f"{m['move_pct']:+.2f}%")

        usable, hits, rate, med = score_from_moves(moves)
        if usable < MIN_USABLE_REPORTS:
            rec["reason"] = f"only {usable} usable reports (< {MIN_USABLE_REPORTS})"
            return rec

        rec.update({
            "status": "scored",
            "reason": "",
            "usable_reports": usable,
            "hits": hits,
            "band_hit_rate": rate,
            "median_abs_move": med,
        })
        return rec

    except Exception as exc:
        rec["reason"] = f"error: {type(exc).__name__}: {str(exc)[:120]}"
        return rec


# ----------------------------------------------------------------------------
# Output writers
# ----------------------------------------------------------------------------
CSV_COLUMNS = [
    "ticker", "sector", "industry", "market_cap", "avg_dollar_volume",
    "usable_reports", "hits", "band_hit_rate", "median_abs_move", "selected",
]


def build_outputs(state: dict):
    """From the full checkpoint state, compute selection and write all outputs."""
    scored = [r for r in state.values() if r.get("status") == "scored"]
    skipped = [r for r in state.values() if r.get("status") != "scored"]

    scored.sort(key=sort_key)
    selected = set(select_with_sector_cap(scored))

    # scored CSV (all scored tickers)
    rows = []
    for r in scored:
        rows.append({
            "ticker": r["ticker"],
            "sector": r.get("sector"),
            "industry": r.get("industry"),
            "market_cap": r.get("market_cap"),
            "avg_dollar_volume": r.get("avg_dollar_volume"),
            "usable_reports": r.get("usable_reports"),
            "hits": r.get("hits"),
            "band_hit_rate": round(r.get("band_hit_rate", 0.0), 6),
            "median_abs_move": round(r.get("median_abs_move", 0.0), 6),
            "selected": r["ticker"] in selected,
        })
    df = pd.DataFrame(rows, columns=CSV_COLUMNS)
    os.makedirs(LOGS_DIR, exist_ok=True)
    df.to_csv(SCORED_CSV, index=False)

    # selected 75 (in ranked order)
    ordered_selected = [r["ticker"] for r in scored if r["ticker"] in selected]
    with open(SELECTED_TXT, "w") as fh:
        for tkr in ordered_selected:
            fh.write(tkr + "\n")

    # skipped reasons
    with open(SKIPPED_TXT, "w") as fh:
        for r in sorted(skipped, key=lambda x: x["ticker"]):
            fh.write(f"{r['ticker']}: {r.get('reason', 'unknown')}\n")

    return df, ordered_selected, scored


def print_summary(df: pd.DataFrame, ordered_selected, scored):
    log("\n" + "=" * 70)
    log(f"Scored: {len(scored)} tickers   Selected: {len(ordered_selected)}")
    log("=" * 70)
    log("\nTop 20 scored rows:")
    with pd.option_context("display.max_columns", None,
                           "display.width", 200,
                           "display.float_format", lambda v: f"{v:,.4g}"):
        log(df.head(20).to_string(index=False))

    if ordered_selected:
        sel_df = df[df["selected"]]
        breakdown = sel_df["sector"].value_counts(dropna=False)
        log("\nSector breakdown of selected 75:")
        for sec, cnt in breakdown.items():
            log(f"  {str(sec):<24} {cnt}")


# ----------------------------------------------------------------------------
# Run modes
# ----------------------------------------------------------------------------
def run_full(limit=None, resume=True, sleep_range=(0.5, 1.0)):
    os.makedirs(LOGS_DIR, exist_ok=True)
    pool = build_seed_pool()
    if not pool:
        log("ERROR: seed pool is empty (could not scrape constituents). Aborting.")
        return 1

    tickers = sorted(pool.keys())
    if limit:
        tickers = tickers[:limit]

    state = load_checkpoint() if resume else {}
    processed_since_ckpt = 0
    total = len(tickers)

    for i, tkr in enumerate(tickers, 1):
        if tkr in state:
            continue
        log(f"[{i}/{total}] {tkr}")
        rec = process_ticker(tkr, pool.get(tkr))
        state[tkr] = rec
        if rec["status"] == "scored":
            log(f"    -> scored: rate={rec['band_hit_rate']:.3f} "
                f"hits={rec['hits']}/{rec['usable_reports']} "
                f"median={rec['median_abs_move']:.2f}%")
        else:
            log(f"    -> skipped: {rec['reason']}")

        processed_since_ckpt += 1
        if processed_since_ckpt >= CHECKPOINT_EVERY:
            save_checkpoint(state)
            processed_since_ckpt = 0
            log(f"    [checkpoint saved: {len(state)} done]")

        time.sleep(random.uniform(*sleep_range))

    save_checkpoint(state)
    df, ordered_selected, scored = build_outputs(state)
    print_summary(df, ordered_selected, scored)
    log(f"\nWrote:\n  {SCORED_CSV}\n  {SELECTED_TXT}\n  {SKIPPED_TXT}")
    return 0


def run_smoke():
    log("SMOKE TEST — verbose per-report moves for known tickers\n")
    for tkr in SMOKE_TICKERS:
        tkr = normalize_ticker(tkr)
        log(f"--- {tkr} ---")
        rec = process_ticker(tkr, None, verbose=True)
        if rec["status"] == "scored":
            log(f"  SCORE  rate={rec['band_hit_rate']:.3f}  "
                f"hits={rec['hits']}/{rec['usable_reports']}  "
                f"median_abs_move={rec['median_abs_move']:.2f}%  "
                f"mktcap=${(rec.get('market_cap') or 0)/1e9:.1f}B  "
                f"$vol=${(rec.get('avg_dollar_volume') or 0)/1e6:.0f}M  "
                f"sector={rec.get('sector')}")
        else:
            log(f"  SKIPPED: {rec['reason']}  "
                f"(sector={rec.get('sector')}, industry={rec.get('industry')}, "
                f"mktcap={rec.get('market_cap')})")
        log("")
    return 0


# ----------------------------------------------------------------------------
# Offline self-test (no network) — validates the pure logic
# ----------------------------------------------------------------------------
def run_selftest():
    log("SELF-TEST — validating pure logic with synthetic data (no network)\n")
    ok = True

    def check(name, cond):
        nonlocal ok
        log(f"  [{'PASS' if cond else 'FAIL'}] {name}")
        ok = ok and cond

    # ticker normalization
    check("normalize BRK.B -> BRK-B", normalize_ticker("BRK.B") == "BRK-B")
    check("normalize bf.b -> BF-B", normalize_ticker(" bf.b ") == "BF-B")

    # Build a synthetic daily close series (business days) with a known jump.
    idx = pd.bdate_range("2023-01-02", periods=20, tz=MARKET_TZ)
    prices = pd.Series([100.0] * 20, index=idx)
    # Day index 5 close = 100; day index 6 close = 106 (a +6% next-close move).
    prices.iloc[6] = 106.0
    prices.iloc[7:] = 106.0

    # AMC report: after close on day 5 (16:30). pre=day5(100), post=day6(106).
    amc = idx[5] + pd.Timedelta(hours=16, minutes=30)
    moves = compute_earnings_moves(prices, [amc])
    check("AMC report pairs day5->day6", len(moves) == 1)
    if moves:
        m = moves[0]
        check("AMC move == 6.00%", abs(m["move_pct"] - 6.0) < 1e-6)
        check("AMC pre=100 post=106", m["pre"] == 100.0 and m["post"] == 106.0)
        check("6% is a hit", m["hit"] is True)

    # BMO report: before open on day 6 (07:00). pre=day5(100), post=day6(106).
    bmo = idx[6] + pd.Timedelta(hours=7)
    moves_bmo = compute_earnings_moves(prices, [bmo])
    check("BMO report also pairs day5->day6",
          len(moves_bmo) == 1 and abs(moves_bmo[0]["move_pct"] - 6.0) < 1e-6)

    # Exactly-16:00 AMC boundary should behave as after-close (pair day5->day6).
    amc0 = idx[5] + pd.Timedelta(hours=16)
    moves0 = compute_earnings_moves(prices, [amc0])
    check("16:00 boundary treated as AMC (day5->day6)",
          len(moves0) == 1 and moves0[0]["pre"] == 100.0)

    # Future report is skipped.
    future = pd.Timestamp("2099-01-01", tz=MARKET_TZ)
    now = pd.Timestamp.now("UTC")
    check("future report skipped",
          len(compute_earnings_moves(prices, [future], now_utc=now)) == 0)

    # Band edges: 4% and 12% inclusive; 3.9% and 12.1% excluded.
    def one_move(pct):
        p = pd.Series([100.0] * 10, index=pd.bdate_range("2023-01-02", periods=10, tz=MARKET_TZ))
        p.iloc[6:] = 100.0 * (1 + pct / 100.0)
        r = compute_earnings_moves(p, [p.index[5] + pd.Timedelta(hours=16, minutes=30)])
        return r[0]["hit"] if r else None
    check("4.0% is a hit", one_move(4.0) is True)
    check("12.0% is a hit", one_move(12.0) is True)
    check("3.9% not a hit", one_move(3.9) is False)
    check("12.1% not a hit", one_move(12.1) is False)
    check("-6% (down) is a hit (direction-agnostic)", one_move(-6.0) is True)

    # Scoring
    fake_moves = [{"move_pct": 5.0, "hit": True},
                  {"move_pct": 6.0, "hit": True},
                  {"move_pct": 2.0, "hit": False},
                  {"move_pct": 20.0, "hit": False}]
    usable, hits, rate, med = score_from_moves(fake_moves)
    check("score usable=4 hits=2 rate=0.5", usable == 4 and hits == 2 and abs(rate - 0.5) < 1e-9)
    check("median abs move = 5.5", abs(med - 5.5) < 1e-9)

    # Filters
    check("Utilities excluded",
          passes_hard_filters("Utilities", "Electric", 10e9, 100e6, None)[0] is False)
    check("Real Estate excluded",
          passes_hard_filters("Real Estate", "REIT", 10e9, 100e6, None)[0] is False)
    check("bank excluded",
          passes_hard_filters("Financials", "Banks - Regional", 10e9, 100e6, None)[0] is False)
    check("non-bank financial ok",
          passes_hard_filters("Financials", "Insurance - Life", 10e9, 100e6, None)[0] is True)
    check("clinical biotech (low rev) excluded",
          passes_hard_filters("Healthcare", "Biotechnology", 10e9, 100e6, 100e6)[0] is False)
    check("biotech w/ big rev kept",
          passes_hard_filters("Healthcare", "Biotechnology", 10e9, 100e6, 900e6)[0] is True)
    check("mktcap too small excluded",
          passes_hard_filters("Technology", "Software", 1e9, 100e6, None)[0] is False)
    check("mktcap too big excluded",
          passes_hard_filters("Technology", "Software", 100e9, 100e6, None)[0] is False)
    check("low dollar vol excluded",
          passes_hard_filters("Technology", "Software", 10e9, 10e6, None)[0] is False)
    check("clean tech passes",
          passes_hard_filters("Technology", "Software", 10e9, 100e6, None)[0] is True)

    # Sector cap selection
    scored = []
    # 20 Tech (high scores), 20 Energy (lower), 5 Healthcare (lowest)
    for i in range(20):
        scored.append({"ticker": f"T{i}", "sector": "Technology",
                       "band_hit_rate": 0.9 - i * 0.001, "median_abs_move": 8.0})
    for i in range(20):
        scored.append({"ticker": f"E{i}", "sector": "Energy",
                       "band_hit_rate": 0.7 - i * 0.001, "median_abs_move": 7.0})
    for i in range(40):
        scored.append({"ticker": f"H{i}", "sector": "Healthcare",
                       "band_hit_rate": 0.5 - i * 0.001, "median_abs_move": 6.0})
    scored.sort(key=sort_key)
    sel = select_with_sector_cap(scored, cap=15, target=75)
    from collections import Counter
    by_sec = Counter(next(r["sector"] for r in scored if r["ticker"] == t) for t in sel)
    check("selection respects 15/sector cap", all(v <= 15 for v in by_sec.values()))
    check("Technology capped at 15", by_sec["Technology"] == 15)
    # 3 sectors * cap 15 = 45 selectable (target 75 unreachable here) -> cap wins
    check("cap limits total to 45 when only 3 sectors x15 available", len(sel) == 45)
    # With enough sectors, the target is reached exactly.
    many = []
    for s in range(10):
        for i in range(10):
            many.append({"ticker": f"S{s}_{i}", "sector": f"Sec{s}",
                         "band_hit_rate": 0.9 - s * 0.05 - i * 0.001,
                         "median_abs_move": 7.0})
    many.sort(key=sort_key)
    sel2 = select_with_sector_cap(many, cap=15, target=75)
    check("reaches target 75 when sectors are plentiful", len(sel2) == 75)

    log("")
    log("SELF-TEST RESULT: " + ("ALL PASS ✅" if ok else "FAILURES PRESENT ❌"))
    return 0 if ok else 1


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="Stock universe earnings-move screener")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--selftest", action="store_true",
                      help="offline logic validation (no network)")
    mode.add_argument("--smoke", action="store_true",
                      help="verbose 5-ticker sanity check")
    mode.add_argument("--rebuild-outputs", action="store_true",
                      help="rebuild CSV/TXT from an existing checkpoint (no network)")
    ap.add_argument("--limit", type=int, default=None,
                    help="cap number of tickers processed (debug)")
    ap.add_argument("--no-resume", action="store_true",
                    help="ignore any existing checkpoint")
    ap.add_argument("--sleep", type=float, default=0.5, metavar="SECONDS",
                    help="base delay between tickers (default 0.5). "
                         "Raise to ~1.5-3 on datacenter/VPS IPs to reduce "
                         "Yahoo rate-limiting.")
    ap.add_argument("--jitter", type=float, default=0.5, metavar="SECONDS",
                    help="extra random delay 0..JITTER added to --sleep "
                         "(default 0.5). Actual wait is uniform[sleep, sleep+jitter].")
    args = ap.parse_args(argv)

    if args.sleep < 0 or args.jitter < 0:
        ap.error("--sleep and --jitter must be non-negative")

    if args.selftest:
        return run_selftest()
    if args.smoke:
        return run_smoke()
    if args.rebuild_outputs:
        state = load_checkpoint()
        if not state:
            log("No checkpoint to rebuild from.")
            return 1
        df, ordered_selected, scored = build_outputs(state)
        print_summary(df, ordered_selected, scored)
        return 0
    return run_full(limit=args.limit, resume=not args.no_resume,
                    sleep_range=(args.sleep, args.sleep + args.jitter))


if __name__ == "__main__":
    sys.exit(main())
