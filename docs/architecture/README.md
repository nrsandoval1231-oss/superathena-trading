# Architecture

SuperAthena has one paper execution stack. Strategies do not own a second broker, journal, or risk gate.

## Decision ownership

| Layer | Role | What is actually wired |
|---|---|---|
| Astra 6 | Interpret source-linked evidence and propose a structured thesis, scenario, and plan with expiry and invalidation | Not integrated. No provider id is selected |
| Jev | Judge the evidence and the proposal. Choices are `TAKE_TRADE`, `NO_TRADE`, and `INSUFFICIENT_EVIDENCE` | `athena_trading.athena_adapter.jev`, model `jev-1.13.0`, TypeSafe endpoint |
| Deterministic code | Prices, sizes, freshness, shared account checks, order identity, and execution | `execution`, `portfolio`, `risk`, `accounting`, `broker_adapters` |

Model agreement is not independent evidence. A model confidence is not a probability of profit. A missing or malformed model result cannot open a new position. `parse_authority("LIVE")` raises.

## APDE

The canonical lifecycle is `EXPLORE → PROTECT → HARVEST → DEFEND → EXIT`, defined in `core/portfolio/position_management/apde.py`. The research ORB simulator has its own management stages. The one-share paper pilot does not activate PROTECT, HARVEST, or DEFEND ratchets. Those threshold proposals stay off. Halt and flatten code in `core/risk` does not import Jev or Astra.

## Strategies

Each product or research family has one directory under `strategies/`. Import paths stay on the `athena_trading` package through directory links in `src/athena_trading`, so there is one copy of each module.

- `strategies/momentum/orb-m` — frozen ORB-M constitution, qualification, and simulator
- `strategies/custom/predictive-intraday` — Jev paper runner and its supervisor
- `strategies/event-driven/earnings-adaptive` — earnings paper book
- `strategies/custom/legacy-strategy-research` — historical experiments (`aat_v1`, `aat_v2`)

The predictive-intraday runner calls ORB-M for the opening-range candidate. That is shared component use, not a second engine.

## Shared infrastructure

| Concern | Authoritative package | Directory |
|---|---|---|
| Contracts and Jev adapter | `athena_trading.athena_adapter` | `core/contracts` |
| Strategy manifests | `athena_trading.strategy_registry` | `core/strategy-registry` |
| Account gate and APDE states | `athena_trading.portfolio`, `athena_trading.position_management` | `core/portfolio` |
| Halt before send | `athena_trading.risk` | `core/risk` |
| Authority, intent, broker protocol | `athena_trading.execution` | `core/execution` |
| Alpaca paper adapter | `athena_trading.broker_adapters` | `core/broker-adapters` |
| Hash-chained journal | `athena_trading.accounting` | `core/accounting` |
| Bars, corporate actions, exogenous records | `athena_trading.market_data`, `athena_trading.exogenous` | `data/ingestion` |
| Offline comparison | `athena_trading.backtesting` | `evaluation/backtesting` |
| Paper session, learning, ownership | `athena_trading.paper` | `operations/paper-trading` |

Historical import paths such as `athena_trading.paper.live` and `athena_trading.paper.journal` alias these modules. The alias and the implementation are the same object.

## Holding policy

Neither arm may plan an overnight position. Earnings brackets are DAY orders and exits start before the regular close, including early closes. Unresolved exposure stays visible and blocks new entries. Approved dollar caps and the ORB constitution ceilings are unchanged.

Correlation, concentration, weekly loss, monthly loss, portfolio drawdown, and overnight stress have no approved number. `UNRESOLVED_SHARED_POLICY` lists them and does not authorize exposure.
