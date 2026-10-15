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

## Phase 2: real-data ingestion + ORB research
- \`python -m funded_trader.cli contracts MES\` — search authorized current ProjectX contract ID.
- \`python -m funded_trader.cli fetch ...\` — read-only historical bars, never an order.
- \`python -m funded_trader.cli backtest ... --fee <YOUR_FEE>\` — local 5-minute ORB, two-sided trading, fee/slippage.
- \`/api/research\` — hosted, bounded, no-storage historical simulator for uploaded bars.
- Browser: open "مختبر البيانات" and upload valid real historical bars. Nothing displays as live until authenticated real feeds exist.

See [DATA_AND_RESEARCH.md](docs/DATA_AND_RESEARCH.md). Provider data is not included in the repo; results are unknown before using licensed data.

## Phase 3: local authorized live quote reader (read-only)
This only runs on the **user's own machine**, never on Railway/Vercel. No trading or order endpoints.

PowerShell:
\`\`\`powershell
npm install
$env:PROJECTX_USERNAME="your-platform-username"
$env:PROJECTX_API_KEY="your-secret-keep-local"
$env:PROJECTX_CONTRACT_ID="CON.F.US.MES.<CURRENT_ACTIVE_EXPIRY>"
npm run feed
\`\`\`

- Quote reader validates bid/ask and event timestamps.
- Writes only the current data snapshot to \`data/projectx-latest-quote.json\` once per second (untracked).
- A 30-second heartbeat explicitly marks the feed STALE. It **never** invents data.
- It is not yet connected to the hosted dashboard; no account/order reader exists.
- Subscription/licensing, access approval, and current contract ID must be obtained from the user's own authorized account.

Official SignalR market hub specification:
https://gateway.docs.projectx.com/docs/realtime/
