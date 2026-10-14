"""Measure how far ORB-M results depend on the intra-bar ordering assumption.

Management fires at +0.5R and +1R inside an eight-minute window, so a single
one-minute bar can contain both a harvest level and the stop.  OHLC cannot order
them.  ADVERSE_FIRST resolves such bars against the position; FAVORABLE_FIRST is
the optimistic alternative.  The gap between the two is not a modelling detail:
it is the amount of apparent edge the assumption alone can manufacture.

The probe sweeps synthetic volatility regimes because the effect scales with bar
range relative to R -- a low-volatility sweep produces no ambiguous bars at all
and would report a falsely reassuring zero.
"""
from __future__ import annotations

import argparse
import random
from datetime import UTC, datetime, timedelta

from athena_trading.orb_m import (
    Bar, BreakoutSignal, Constitution, ManagementParameters, OpeningRange, run_position,
)

BASE = datetime(2026, 3, 2, 14, 30, tzinfo=UTC)
OPENING_RANGE = OpeningRange(high=101.0, low=99.0, volume=15000.0, frozen_at_minute=15)
SIGNAL = BreakoutSignal("LONG", 15, 101.2, OPENING_RANGE)
REGIMES = ((0.35, 0.25), (1.0, 0.8), (2.0, 1.5), (3.0, 2.5))


def synthetic_session(seed: int, body_sd: float, wick_sd: float) -> list[Bar]:
    rng = random.Random(seed * 7919)
    price, bars = 101.2, []
    for minute in range(16, 200):
        open_ = price
        close = max(1.0, open_ + rng.gauss(0, body_sd))
        high = max(open_, close) + abs(rng.gauss(0, wick_sd))
        low = max(0.5, min(open_, close) - abs(rng.gauss(0, wick_sd)))
        bars.append(Bar(BASE + timedelta(minutes=minute), minute, open_, high, low,
                        close, 1000.0))
        price = close
    return bars


def sweep(body_sd: float, wick_sd: float, trials: int, atr14: float) -> dict:
    adverse = Constitution(slippage_bps=2.0)
    favorable = Constitution(slippage_bps=2.0, intrabar_resolution="FAVORABLE_FIRST")
    parameters = ManagementParameters()
    harvest = SIGNAL.signal_close + parameters.first_harvest_r * atr14
    differences, ambiguous = [], 0
    for seed in range(trials):
        bars = synthetic_session(seed, body_sd, wick_sd)
        ambiguous += sum(1 for bar in bars
                         if bar.high >= harvest and bar.low <= SIGNAL.signal_close - atr14)
        pessimistic = run_position(SIGNAL, bars, atr14, adverse, parameters)
        optimistic = run_position(SIGNAL, bars, atr14, favorable, parameters)
        differences.append(optimistic.net_r - pessimistic.net_r)
    affected = sum(1 for value in differences if abs(value) > 1e-9)
    return {"body_sd": body_sd, "wick_sd": wick_sd, "ambiguous_bars": ambiguous,
            "affected": affected, "trials": trials,
            "mean_inflation_r": sum(differences) / len(differences),
            "max_inflation_r": max(differences)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=600)
    parser.add_argument("--atr14", type=float, default=2.0)
    args = parser.parse_args()
    print(f"{'body_sd':>8} {'wick_sd':>8} {'ambig_bars':>11} {'affected':>12} "
          f"{'mean_infl':>11} {'max_infl':>10}")
    for body_sd, wick_sd in REGIMES:
        row = sweep(body_sd, wick_sd, args.trials, args.atr14)
        print(f"{row['body_sd']:>8} {row['wick_sd']:>8} {row['ambiguous_bars']:>11} "
              f"{row['affected']:>6}/{row['trials']:<5} "
              f"{row['mean_inflation_r']:>+10.4f}R {row['max_inflation_r']:>+9.3f}R")
    print("\nInflation is the edge the optimistic ordering invents. ORB-M targets "
          "high-RVOL\nopening sessions, which is the regime where it is largest.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
