# Replacement acceptance gates

1. **Archived** — `archive/aegis-agent-city-2026-10-15` preserves the former agent-city branch.
2. **Removed legacy tree** — This branch contains only Funded Trader AI modules and static dashboard. No automated executor is active.
3. **Provider policy** — Check *specific account agreement* and approval to automate BEFORE any broker API is wired.
4. **Historical inputs** — Source independently audited and timestamped MES/MNQ historical trades including execution fees, spread/slippage and market sessions.
5. **Rule profiles** — Per-program signed-off target, drawdown, reset timezone, payout consistency and scaling. Example policy must never be used as official.
6. **Validation** — Boundary tests, gap/overshoot tests, reconciliation, order rejection handling, stale feed circuit breaker and Monte Carlo with dependent-block resampling.
7. **Paper execution** — Distinguish observed live provider prices and fills from synthetic scenarios. No fabricated 'live' metrics.
8. **Actual accounts** — Enable only with compliant adapter, explicit secret management and manual kill switch. Automatic order execution disabled by default.

The bootstrap simulator assumes exchangeable trade outcomes. This is a deliberately limited research model, not a demonstrated pass probability.
