# Architecture
The authoritative architecture is [Athena Trading Canon](ATHENA_TRADING_CANON.md), based on the [owner-supplied diagram](assets/athena-trading-canon.jpg) and the owner's 13 October 2026 hybrid amendment.

Both **Earnings Adaptive** and **Athena Predictive Intraday** share:
- Point-in-time world state and validated Athena context.
- **Astra 6**, the owner-selected generative LLM, for evidence-linked interpretation, theses, scenarios and structured plans with expiry/invalidation.
- **TypeSafe Jev**, the bounded judge, reading underlying evidence plus the proposal and retaining an insufficient-evidence option.
- Deterministic calculations, validated forecast outputs, freshness checks, sizing, shared portfolio risk and final execution authorization.
- Model-independent critical protection, exits, broker reconciliation and deterministic APDE transition enforcement.
- Decision Episodes, replay, validation and versioned learning through Athena Core.

See the [hybrid contract and image acceptance map](HYBRID_MODEL_CONTRACT.md). Astra 6's exact deployment/API model ID and access are unverified; no silent substitution is allowed. Agreement between the models is not independent proof and neither confidence score is profit probability.

The current main runner is still a narrow Jev-only intraday paper implementation. The hybrid, full APDE, complete forecasts and general Core learning remain incomplete; Earnings PR #29 is pending integration. Nick confirmed the diagram's pre-close-flat rule on 13 October 2026: neither arm may plan an overnight position. PR #29's earlier multi-day proposal is superseded; legacy positions must be recovered without renewing that permission. Nothing here enables LIVE or changes risk limits.

[Implementation status and repository map](IMPLEMENTATION_STATUS.md) · [Active build sequence](BUILD_PLAN.md) · [Documentation index](README.md)

This file is a navigation entry point. Keep architectural requirements in the canon.
