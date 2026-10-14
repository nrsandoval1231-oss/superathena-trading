# Risk and execution ownership

Deterministic code authorizes orders. Jev can veto or abstain. Astra 6 cannot send an order, and it is not connected.

| Control | Owner | Current behavior |
|---|---|---|
| LIVE authority | `execution.authority` | `parse_authority("LIVE")` raises. Allowed values are `ABSENT` and `PAPER` |
| Paper send | `execution.authority.require_paper` | Sends require an explicit PAPER grant |
| Alpaca endpoint | `broker_adapters.alpaca` | Only `https://paper-api.alpaca.markets` |
| Per-trade and session halt | `risk.halt` | Blocks a send that fails the halt gate. Does not call a model |
| Shared symbol and buying power | `portfolio.shared_risk` | One symbol reservation and combined notional within buying power |
| Inactive portfolio numbers | `portfolio.shared_risk.UNRESOLVED_SHARED_POLICY` | No correlation, concentration, weekly, monthly, drawdown, or overnight threshold is active |
| Same-session flat | intraday runner and earnings book | No overnight plan. Earnings exits start before the regular close |
| Earnings headline label | `earnings.news_for_decision` | A headline can be labeled `confirmed`. That label does not authorize the trade |
| Idempotent client ids | paper runners | Intraday `athp-`, earnings `athe-`. Restarts reconcile ids and do not resubmit them |
| Journal recovery | `accounting.journal` | Hash-chained SQLite events. A second writer fails closed |

Approved risk limits from the source checkout were not edited. The one-share intraday pilot and the earnings dollar caps remain the values in those modules. ORB-M constitution ceilings remain the research simulator's ceilings. They are not a claim that the paper pilot uses those ceilings for live-sized orders.

Protective flatten and halt paths run when the model is unavailable. An outage can still leave a position open. `EXIT_UNRESOLVED`, `FLATTENING`, and `POSITION_MISMATCH` stay visible and block new entries.
