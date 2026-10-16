# Backtesting

`backtesting/evaluation.py` compares supplied opportunities offline. Fills use the next open. The performance field is unverified. This package does not read consumed holdouts.

`intraday_replay` is the Stage 0 harness for the intraday multi-trade proposal. Authority stays `ABSENT`. A fixture result is not market evidence. Neither tool submits an order.

The proposal itself is [docs/design/intraday-multi-trade.md](../../docs/design/intraday-multi-trade.md). This harness does not change the ORB constitution, `PilotPolicy`, the paper runner, or `athena-paper.service`.

## Replay order

The harness runs families in this order, one report at a time:

1. `frozen_orb_reentry` — the constitution's one initial attempt and one re-entry per direction. The simulator is called as it stands. `constitution.py` is not edited. A hash pin refuses a different constitution.
2. `vwap_reclaim` — a completed close back through session VWAP after the close has lost VWAP by 1 ATR. Session VWAP is an input. The ORB quality weight is not the entry.
3. `intraday_momentum` — a completed close through the prior 20 one-minute highs or lows, after the opening range has frozen, and outside that range.
4. `mean_reversion` — a fade of a 1.5 ATR stretch from session VWAP on a name whose close is at least the constitution's `price_min`. The liquidity floor is a screen.

The 1 ATR, 20-bar, and 1.5 ATR figures are research assumptions written down so a replay can run. They are not approved risk limits and they are not fitted on the sample. Changing one is a different study.

New families stop after two entries on a symbol in a session, so one name cannot loop. That cap is the frozen 1+1 count used inside the research replay. It does not turn on a paper rung. The ORB family uses the constitution budget instead, which is one initial attempt and one re-entry on each side.

## Fills and costs

- The signal is a completed bar. The fill is the next bar's open. The decision close is not a fill.
- A bar that contains both the stop and the target exits at the stop (`ADVERSE_FIRST`).
- A later bar that opens through the stop fills at that open.
- The book holds one position at a time. The approved 0.5% daily-loss halt stops new entries for the rest of that session.
- Share count is 1. A trade whose stop risk is above $10, or whose entry is above the tighter of $1,000 and 1% of the operator-reported equity, is not taken.
- The target multiple stays at 2R, except mean reversion, whose target is the session VWAP frozen at the signal.
- Replay equity is the operator-reported $98,900. A measured buying-power ratio is not in this tree. The report says so.
- The capped marketable limit column is absent.

`paper-cost-scenario-v1` is a labeled scenario, not a measured fee schedule:

- 2 bps adverse slippage on entry and on exit, with a floor of $0.01 per share per side
- an unobserved-spread charge once on entry of `max($0.01, 5 bps of the decision price)`
- $0.01 per share per side as a regulatory scenario
- commission of $0

The frozen ORB simulator already applies its 2 bps haircut inside the fill. The harness adds the one-cent floor when that haircut is smaller, plus the spread and the regulatory cent. It does not charge the 2 bps twice. The other families apply the whole scenario to raw next-open prices.

## Pass line

A family passes the numeric gate only when every item below is true on the out-of-sample folds:

- cost-adjusted expectancy per closed trade is greater than zero
- the session-clustered 95% lower bound of mean cost-adjusted dollars per session is greater than zero
- at least 100 closed out-of-sample trades and 60 out-of-sample sessions
- the 0.5% halt trips on at most 5% of out-of-sample sessions
- chronological peak-to-trough drawdown is at most 2.5% of the $98,900 replay equity
- cost-adjusted expectancy is greater than zero in at least 4 of 5 chronological folds

Walk-forward uses five contiguous folds from earliest session to latest. Nothing is shuffled. These families do not fit a parameter; `fit` is still called with only that fold's earlier sessions.

The gate also requires a `POINT_IN_TIME` or `CURRENT_SNAPSHOT` universe label, the pinned constitution hash, and the sentence "No edge is claimed." `CURRENT_SNAPSHOT` stays marked as survivorship bias. `FIXTURE` can exercise the arithmetic and cannot pass the gate. Holdout paths are refused.

`gate_passed: true` still sets `market_evidence` to false. A pass would open shadow eligibility for that family only, and shadow is a later stage. This checkout does not run shadow and does not send an order.

## Bar file

A local JSON file, or a directory of JSON files that share one provenance:

```json
{
  "provenance": "FIXTURE",
  "universe_members": ["AAA"],
  "sessions": [
    {
      "session": "2024-01-02",
      "symbol": "AAA",
      "atr14": 0.5,
      "bars": [
        {"minute": 0, "open": 50.0, "high": 50.2, "low": 49.8, "close": 50.0, "volume": 10000}
      ]
    }
  ]
}
```

`minute` is minutes after 09:30 America/New_York. `provenance` is `POINT_IN_TIME`, `CURRENT_SNAPSHOT`, or `FIXTURE`. Omit `universe_members` to replay every symbol in the file.

## Commands

From the repository root:

```bash
PYTHONPATH=src python3 scripts/run_intraday_replay.py \
  --bars evaluation/backtesting/fixtures/intraday_replay_sample.json \
  --family frozen_orb_reentry \
  --out /tmp/orb-replay.json

PYTHONPATH=src python3 scripts/run_intraday_replay.py \
  --bars evaluation/backtesting/fixtures/intraday_replay_sample.json \
  --order \
  --out-dir /tmp/intraday-replay
```

The sample file is synthetic. Its report fails the gate. That is the expected result. The script's exit code is 0 when a report is written, including a failed gate. A constitution mismatch, a holdout path, or a malformed file exits 2. `LIVE` on the command line exits 2.

## Values still marked NEEDS NICK

The harness does not choose these:

- `target_r` stays at the approved 2. Changing the intraday multiple is `NEEDS NICK`.
- `concentration_limit` stays inactive. It is `NEEDS NICK` before it does anything.

Correlation, weekly loss, monthly loss, portfolio drawdown, and overnight stress stay inactive as well. No number is proposed for them. S0-6, the read-only buying-power measurement, is not this harness.
