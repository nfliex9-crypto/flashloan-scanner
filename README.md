# Funded Trader AI — clean replacement

Funded Trader AI replaces the retired AEGIS Agent City application. The legacy version is preserved on `archive/aegis-agent-city-2026-10-15`; the independent `Bot` branch is untouched.

## Current functionality
- Python prop-account risk rule engine with static, end-of-day trailing and intraday trailing drawdown policies.
- Contract risk sizing with fees and stop/slippage allowances.
- Daily loss checks and profit consistency calculation.
- Seeded historical-trade bootstrap simulator for *hypothetical* evaluation passes.
- Arabic RTL static risk-preview dashboard (manual, local inputs — no live feed).
- Unit tests and GitHub Actions checks.

**Current status:** research/demo only. NO broker connection, NO order execution, NO market feed, NO verified trading performance. The UI explicitly does not manufacture live prices or trades.

## Test locally

```bash
python -m unittest discover -s tests -v
python -m http.server 8000
```
Open http://localhost:8000 for the browser dashboard.

## Layout
- `funded_trader/rules.py`: pure Python account policy and position risk management
- `funded_trader/simulation.py`: limited seeded resampling simulator
- `tests/`: policy invariants and simulation tests
- `index.html`, `app.js`, `styles.css`: standalone interactive dashboard
- `docs/NEXT_STEPS.md`: integrations, compliance and acceptance gates

## Compliance
Default templates are **illustrative, not certified**. Confirm all prop firm rules, instruments, fees, clock reset, drawdown calculation, API policy, and payout conditions against the specific signed agreement. Never deploy automatic order execution to a provider that prohibits it.
