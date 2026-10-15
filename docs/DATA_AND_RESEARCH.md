# Futures research data: real inputs, never fabricated performance

## ProjectX / TopstepX (read-only REST history)
Sources: https://gateway.docs.projectx.com/docs/getting-started/authenticate/authenticate-api-key/
https://gateway.docs.projectx.com/docs/api-reference/market-data/retrieve-bars/
https://gateway.docs.projectx.com/docs/api-reference/market-data/search-contracts/

The API login requires the trader's platform username (not email) and API key, and the user's platform must authorize the API. No secrets in chat, GitHub, logs, or Vercel env. Run locally on Windows/Linux from your own device where policies require it.

PowerShell:
\`\`\`powershell
$env:PROJECTX_USERNAME="your-platform-username"
$env:PROJECTX_API_KEY="your-local-api-key"
python -m funded_trader.cli contracts MES
# Copy the appropriate ACTIVE/current contract ID from the response:
python -m funded_trader.cli fetch "CON.F.US.MES.<YOUR_CURRENT_EXPIRY>" "2026-10-01T00:00:00Z" "2026-10-07T00:00:00Z" "data/mes-5m.csv"
python -m funded_trader.cli backtest data/mes-5m.csv --instrument MES --fee 2.50 --risk 75 --stop-ticks 20 --target-ticks 40
\`\`\`
Fee 2.50 above is an ILLUSTRATION — replace with your real all-in round-trip fee per micro contract.

The adapter uses only three endpoints: \`/api/Auth/loginKey\`, \`/api/Contract/search\`, \`/api/History/retrieveBars\`. No order endpoints, no broker execution, no credential persistence. Historical bars are capped by the provider at 20,000 per call. Any partial bar is excluded. Requested contract IDs must be resolved each expiry; never hardcode an obsolete expiry. CSV includes a SHA256 provenance sidecar.

The API payload's 'live=false' selects simulated feed; it does **not** mean that its OHLCV prices were invented. Access/licensing remains broker-dependent. Do not publish exchange data without the requisite licensing.

## ORB proof of concept
Baseline: 5-minute RTH bars only, six-bar 09:30–10:00 ET opening range. Completed-bar breakout generates a **next-bar OPEN** entry, with 1 trade/day, conservative stop-first fills on ambiguous bars, slippage on entry+exit and commission. Trades in USD using the selected future contract's tick size/value. Position sizing uses the illustrative drawdown rule engine, never a certified firm rule set.

This is a first-pass OHLC backtest, not exchange-grade tick replay. Intrabar paths and actual fills cannot be reconstructed from candles. Gaps between 5-minute RTH candles cause the session to be skipped rather than silently interpolated. Each bar timestamp is treated as the bar's START. Historical sessions containing early closes, contract rolls, DST, half-days or provider outages need individual validation. Raw strategy results **must not** be sold as verified or used to assume a funded-account pass rate.

No independent historical bars or API keys are present in the repository. Results remain unknown until a licensed data feed is connected and out-of-sample tests are executed.

## Next
- reconcile EOD vs intraday thresholds using signed provider account agreement and firm clock
- walk-forward holdout; confidence intervals and regime diagnostics
- avoid signal lookahead under bar completion and gap conditions
- add authenticated API-free, local-only execution simulator and audit ledger
- realtime quotes via ProjectX market SignalR hub from authorized user's local machine; remote Vercel is UI only
