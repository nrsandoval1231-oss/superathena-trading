# Earnings Adaptive paper book

Nick confirmed on 13 October 2026 that he does not want to hold overnight. Both strategy arms must pursue pre-close, same-session exits.

PAPER only. `parse_authority("LIVE")` raises `AuthorityError`. The order endpoint stays `https://paper-api.alpaca.markets`. This arm does not grant real-money authority, and it does not rerun the frozen earnings-universe study.

The screener in `research/earnings-universe/universe_screener.py` ranks about 75 names that historically move 4–12% from the close before a report to the close after it. That screen is a watchlist heuristic. It does not establish that the move continues after entry, and this book does not rerun or relabel that study. The book trades a name from the operator's copy of `universe_75.txt` only when the live gap, on the first regular session after a known report, lands inside that same band. The order that can actually be filled is the post-entry bracket below. Longs and shorts use the sign of the gap and the same stop and target shape. Their results are not pooled into one claim, and neither side has a measured edge.

## Rule set

| Rule | Value |
|---|---|
| Direction | Sign of the gap from the prior regular close to the latest completed minute inside the entry window |
| Gap band | 4% to 12% absolute, inclusive. A watchlist screen, not a profit result. Outside the band is no trade for that bar. The band is not an environment setting |
| Entry window | 5 to 30 minutes after the regular open, on the first session the report is public |
| Before the open (BMO) | Entry session is the report date |
| After the close (AMC) | Entry session is the next regular session |
| Unknown report time | Skipped. The book does not guess |
| Order | DAY limit bracket, whole shares, no extended hours. Stop is halfway back toward the prior close. Target is 2R |
| Max hold | Same regular session only. Exit starts 15 minutes before the broker calendar's actual close, including early closes. An overdue position is recovered at the next available open |
| Unfilled entry | Canceled when the entry window ends. The client order id is not reused |
| Partial fill or missing stop | Close that symbol. Jev is not called |
| Quantity the book does not recognize | `POSITION_MISMATCH`. No market close |
| New entries | At most 1 per day and 3 open names, unless the environment sets a tighter cap |
| Jev | Same floors as the intraday arm: p(TAKE_TRADE) >= 0.6 and confidence >= 0.5. A veto or a bad answer skips that report. It is not an approval |
| Model outage | No new order. Open brackets stay. A transport failure is not a flatten |

APDE labels on the book are `EXPLORE` while the bracket is working and `EXIT` when the book starts to close it. PROTECT, HARVEST, and DEFEND are not driven yet.

## Size

Default paper caps, which the environment may tighten but not raise past the ceiling:

| Cap | Default | Ceiling |
|---|---|---|
| Risk per trade | $50 | $100 |
| Open stop risk | $150 | $300 |
| Notional per trade | $2,000, and 2% of equity | $5,000 |
| Open notional | $6,000 | $10,000 |
| Open positions | 3 | 5 |
| Hold | Same session | No overnight permission |

Buying power is checked again before the order is sent. One share that would exceed the risk or notional cap is skipped. Sizing is not fractional Kelly.

A 0.5% drop versus broker `last_equity` stops new entries. Existing stops remain managed, and the same-session exit deadline still applies.

## Calendar

Free source: `https://api.nasdaq.com/api/calendar/earnings?date=YYYY-MM-DD`. No API key. The request sends a browser User-Agent because the host often refuses a bare client.

Limits:

- The endpoint is undocumented and has no availability promise. A failed or unusable payload blocks new entries. It does not invent a calendar.
- One call is one calendar day. The book reads today and the previous regular session.
- `time-pre-market` is before the open. `time-after-hours` is after the close. `time-not-supplied` and any other token are skipped.
- Rows do not include a surprise, guidance, options skew, or the historical reaction. EPS text is ignored.
- The list can change after publication. This book does not detect revisions.
- Symbols are normalized to Alpaca form (`BRK/B` and `BRK-B` become `BRK.B`).

Session dates come from Alpaca's paper calendar, not from Nasdaq.

## Universe

`ATHENA_EARNINGS_UNIVERSE` is a text file, one ticker per line, at most 75 names. Produce it with the research screener and copy `universe_75.txt`. The book ranks candidates in file order and takes the first name that clears the gap, the asset check, and Jev. It will not enter `ATHENA_SYMBOL`, a symbol that already has an `athp-` order, or a symbol that already has a position or order the book did not reserve.

## State, restarts, and the other arm

Client order ids start with `athe-` and are a hash of account, symbol, and report date. The id is journaled before the POST. A lost response looks the id up. It is not sent again. Two flat HTTP 404s, with no acknowledgement and no exposure in that symbol, record `entry_not_created`.

The book file is `/var/lib/athena-earnings/book.sqlite`, reused across sessions. A restart loads the same journal, republishes `ownership.json`, and reconciles open ids before seeking another entry. Live symbol ownership clears only when the trade closes; exact account-bound historical entry, leg and acknowledged close identities remain in the ledger so completed earnings orders cannot contaminate intraday outcomes. A manual order on the same symbol is not historical ownership.

A close must match the signed residual explained by entry fills, bracket fills and all previous terminal close attempts. Every position-close request specifies that exact remaining quantity; a concurrent manual addition cannot expand it to an account-wide quantity. Partial working acknowledgements are refreshed. Terminal canceled, rejected or expired zero-fill attempts contribute zero while later attempts can complete the cashflow. A changed broker ID, symbol, side or requested quantity is not accepted as the refreshed close.

After a lost response, recovery reads both working orders and bounded terminal history. A unique candidate must match symbol, opposite side, requested quantity and a broker creation/submission time inside the durable intent's one-minute send window; prior known order IDs and competing unknown working orders are excluded. Missing, malformed, truncated or ambiguous evidence stays `FLATTENING`; the request is never blindly repeated. Other symbols continue their own protection. Outcomes require terminal, balanced fills and broker-flat observations. The receipt is committed before the closure marker; restart fills in only a missing event. Legacy journals with a closure marker but no receipt remain in recovery until the exact fills can be reconstructed.

The holding policy is same-session only. New brackets use DAY, with no extended hours. Exit begins 15 minutes before the actual regular-session close, including early closes, regardless of model availability. Pending entries are canceled. Prior-day exposure is recovered as soon as the broker can execute. Legacy GTC orders and policies remain readable; `ATHENA_EARNINGS_MAX_HOLD_SESSIONS=2..5` is recovery-only and produces `MULTIDAY_POLICY_DISABLED` for new entries. Remove that old setting or set it to 1; do not replace a journal containing unresolved trades.

`EXIT_UNRESOLVED` and the durable `exit_unresolved` event identify a closed-market position requiring operator attention. A market halt, rejected cancellation, disconnected broker or failed close can prevent actual flatness. `FLATTENING` means execution or bookkeeping remains unresolved, and `POSITION_MISMATCH` requires resolving unowned exposure. Do not claim a flat account from cancellation or order acknowledgement alone. New entries are blocked while these states remain. SIGTERM stops the process and does not establish flatness; the next start must recover the journal. Before planned downtime, complete the operator-owned flatten workflow and verify broker-confirmed flatness; do not leave unresolved exposure unattended or treat DAY expiration as a position close. `--flatten-owned` closes only owned earnings exposure and durably blocks new entries, even after an older daily-loss halt.

Intraday orders start with `athp-`. The intraday runner's flat check and `flatten_step` ignore `athe-` orders and symbols listed in the earnings ledger. They still flatten `athp-` exposure, and they still refuse a symbol that belongs to neither arm. The earnings book will not cancel an `athp-` order.

`athena-paper.service` reads `ATHENA_EARNINGS_STATE_DIR=/var/lib/athena-earnings`. `athena-earnings.service` uses `/etc/athena/earnings.env`. It writes its book under `/var/lib/athena-earnings` and appends closed trades under `/var/lib/athena/learning`. It does not write the intraday session journals. Enabling the earnings unit does not restart the intraday unit. This repository does not enable either unit.

Closed earnings trades are copied into the shared learning store at `ATHENA_STATE_DIR/learning` (default `/var/lib/athena/learning`) with `arm=earnings`. They keep fill quantity, gross P&L when the entry and exit cashflows balance, the decision receipt, and source hashes. `eligible` is false. The intraday discovery, validation, promotion, and context retrieval ignore `arm=earnings`, so these fills do not train or skew that study. A locked store is retried; it does not block a protective exit.

Before the open, and again until the entry window ends, the book calls Alpaca `GET /v1beta1/news` with the paper keys for that day's candidates, starting at the prior regular close. A successful snapshot is kept for fifteen minutes and then refreshed; each snapshot records the time it was available. An empty early pull does not freeze the session. Headlines and summaries are journaled as `news_context` and, when a name is adjudicated, as `news_fed` inside the Jev packet, with source, id, and publication time. `news=confirmed` requires a headline in that window that reads as a released report. A preview, a future or expected report, a negation, a split, a dividend, or a distribution stays `news=unconfirmed`. Confirmation is headline-shaped evidence in the pre-open window. It is not a filing receipt, and it does not authorize the trade. The Nasdaq calendar remains the schedule. The book does not call Alpaca's corporate-actions endpoint. Prices are the broker's unadjusted IEX or SIP prints. A split or distribution is not adjusted in the journal, so a comparable-price series is not claimed. Rate limits use the same GET retry as other broker reads. If news is down or unusable, the book journals `news_unavailable` and continues with `news=unavailable`.

A completed bar outside the 4–12% band is a temporary skip. A later completed bar inside the entry window is judged again. An untradable asset, a blocked short, or the intraday symbol is skipped for the session. A name is adjudicated once. The resulting reservation is not sent twice.

The entry window and the age of the minute bar are checked again after Jev returns, immediately before the order is reserved. A decision that finishes after minute 30, or on a stale bar, does not submit.

A 0.5% daily loss blocks new entries for that broker session only. The event stays in the journal. The next session evaluates equity again. An operator flatten halt stays in force until the book is replaced.

On restart, risk and notional caps may be tightened. A looser cap, or a change to the feed, universe, or any other setting, refuses startup. Existing reservations keep the order that was already journaled. The tightened caps are stored as `policy_tightened` and apply to later entries.

Both arms share one account gate in `paper/shared_risk.py`. One account-specific mutex serializes fresh broker sampling, peer/own exposure checks and durable entry reservation. A repeated symbol or insufficient unreserved buying power returns `SHARED_RISK_BLOCKED`. A busy/unavailable coordinator or unreadable/integrity-failed peer also blocks new entry. The peer journal's lifetime writer lock does not block read-only access. Pending shares plus held residuals, legacy GTC `done_for_day` orders and unresolved prior-session journals remain counted. Protective management and session exits do not acquire the entry mutex. Both arms reject overnight proposals. Correlation, concentration, weekly/monthly loss, portfolio drawdown and overnight stress thresholds remain inactive; this is not the complete portfolio gate. See [shared coordination setup](CLOUD_DEPLOYMENT.md#shared-account-entry-coordination).

Each watched name records an `opportunity` row when the book can see the outcome: temporarily outside the gap band, rejected by asset or short or the intraday symbol, vetoed by Jev, blocked by the shared gate, or submitted. Closed earnings episodes stay in the learning store with `arm=earnings` and `eligible` false. They are not added to the intraday study and they are not promoted.

## Run

Do not put keys in git. Copy `deploy/earnings.env.example` to `/etc/athena/earnings.env` (mode 0600). The example file has empty key fields.

```bash
python scripts/run_athena_earnings.py --authority PAPER --journal /var/lib/athena-earnings/book.sqlite --preflight
python scripts/run_athena_earnings.py --authority PAPER --journal /var/lib/athena-earnings/book.sqlite --run
```

`--preflight` checks the broker, the TypeSafe model list, and the universe file. It does not submit. The cloud supervisor is `python -m athena_trading.paper.earnings_cloud`. `deploy/install.sh` installs `athena-earnings.service` and leaves it stopped.

A passed test suite is not a broker fill and not evidence of trading performance.
