# Strategy inventory

| Directory | Id | Entrypoint | Standing |
|---|---|---|---|
| `strategies/custom/predictive-intraday` | `predictive-intraday` | `athena_trading.intraday.live` | Paper pilot. One ORB candidate, Jev decision, deterministic checks, Alpaca paper bracket. Not an established edge |
| `strategies/event-driven/earnings-adaptive` | `earnings-adaptive` | `athena_trading.earnings.earnings` | Paper book. Gap band, Jev, shared gate, same-session exit. Not a thesis generator and not promoted |
| `strategies/momentum/orb-m` | `orb-momentum` | `athena_trading.orb_m` | Frozen research baseline and the intraday candidate component. Simulator management is not the paper order path |
| `strategies/custom/legacy-strategy-research` | `legacy-strategy-research` | `athena_trading.aat_v1` | Historical experiments. Secondary module `athena_trading.aat_v2`. Execution authority in those experiments stays absent. Not promoted |

No other trading strategy was present in `athena-trading` at the source anchor. `strategies/orb_momentum.py` is a compatibility wrapper over `orb_m`, not a second constitution. The fixture self-improve lab is an offline mutator with authority ABSENT. The earnings universe screener is research input, not an order path.

Astra Desk is a separate repository and was already absent from this source tree. It was not copied.

These ids are registered by `tests/test_strategy_registration.py`.
