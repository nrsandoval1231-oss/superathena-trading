> **Superseded on 24 September 2026.** Historical snapshot. Product authority: [Athena Trading Canon](../../docs/ATHENA_TRADING_CANON.md). Relative links below retain their original context.

# Athena Trading Canon v1.0

## Identity

Athena Trading is a domain application and research laboratory for Athena. It is not Athena Core.

## Ownership boundary

### Remains in Athena Core
- evidence-governed adaptation architecture
- Decision Episodes and validated experience
- attribution and lesson lifecycle
- policy/genome abstraction and lineage
- Athena Arena
- Athena Gauntlet
- domain-neutral evaluation, falsification, promotion and authority boundaries
- general mathematical foundation

### Belongs in Athena Trading
- equity/market data adapters
- trading strategies and signal definitions
- ORB logic
- earnings and intraday strategy arms
- trading-specific APDE configuration and position management
- stops, targets, trailing and harvest rules
- trading risk budgets and sizing
- fills, slippage and execution simulation
- Alpaca/broker adapters
- backtests, paper trading and trading performance metrics
- trading-specific experiment datasets and results

## Relationship

Athena Trading emits domain observations, decisions, actions and outcomes through an Athena domain adapter. Athena Core may learn and evaluate policy behavior without becoming coupled to equities or broker semantics.

## Non-negotiable separation

No trading-specific primitive may become a required Athena Core primitive. Athena must remain capable of operating in non-trading domains such as commercial intelligence, football decision support, engineering R&D, and other bounded decision environments.

## Research posture

Trading is useful because outcomes are measurable, data is abundant, repeated episodes are possible, and policies can be evaluated quantitatively. Success or failure of one trading strategy does not prove or disprove Athena as a general architecture.

## Current strategy portfolio

- ORB-Momentum: first reconstructed deterministic baseline.
- Predictive Intraday: planned full strategy arm.
- Earnings Adaptive: planned full strategy arm.

The ORB-Momentum baseline is deliberately strong enough to be useful without Athena. Athena's research question is whether validated adaptation can improve decision quality and risk-adjusted realized value over that frozen baseline without violating hard risk authority.
