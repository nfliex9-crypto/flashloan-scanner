# AEGIS: Open-source adoption without compromising production isolation

## Source audit (2026-10-10)

| Upstream | Direct source | What is useful | Decision |
| --- | --- | --- | --- |
| HKUDS/Vibe-Trading | https://github.com/HKUDS/Vibe-Trading (MIT, source reviewed at `main`) | Source health canaries, evidence-grounded research, logged reasons for incomplete backtests, report provenance | **Adapt concepts; no runtime dependency or copied source.** |
| freqtrade/freqtrade | https://github.com/freqtrade/freqtrade (GPL-3.0) | Stoploss guard, cooldown, drawdown protections and no-trade states | Review risk design only. No GPL code vendored; AEGIS already has hard drawdown/loss vetoes. |
| QuantConnect/Lean | https://github.com/QuantConnect/Lean (Apache-2.0) | Live-vs-backtest separation, chronological simulation and reproducible receipts | Review for future incremental test harnesses; do not replace the current AEGIS engine. |

Vibe-Trading is a substantial FastAPI/LangChain/agent and broker integration.
Installing the entire package would introduce many transitive dependencies,
broker write surfaces, cache/workspace complexity, and deploy/runtime costs.
AEGIS retains a narrow, separately deployed Kraken-only Paper worker and
a read-only MetaApi MT5 DEMO synchronizer.

## Implemented in this branch

- `aegis/ops_health.py`: read-only Neon canaries. Independently checks schema,
  15-minute heartbeat, hourly forward-paper receipt, 1m/5m/15m/1h/4h/1d/1w
  Kraken worker freshness, and MT5 DEMO ledger freshness. Does not place orders
  or label missing feeds as connected.
- `/api/stage3?diagnostics=1`: uses an **existing** Vercel Function, not a new
  Function. No migrations or broker HTTP calls.
- `/city.html#opsHealthPanel`: displays each status from persisted receipts,
  with the missing timeframes and missing tables when applicable.
- `tests/test_ops_health.py`: tests incomplete or stale receipts, partial
  3/7 data, Neon outages, no-demo and strict diagnostics query validation.

## Deploy and verify — remaining operational prerequisites

1. GitHub branch `agent-city-v1` only, never default `Bot`.
2. Confirm Vercel Preview deployment SHA = latest branch SHA and is READY.
3. Read `/api/stage3?diagnostics=1` and inspect genuine, current Neon
   receipts. A READY deployment is **not** evidence of an active scheduler.
4. The existing Railway `aegis-public-kraken-micro` service is independently
   deployed. It last had **1m, 5m, 15m**, not all seven timeframes. Verify Neon
   `sql/008-010` schema/constraints before deploying newer worker code.
5. Resolve `/api/paper_tick` 503 by confirming database tables/grants and
   observing the **new** safe error class and SQLSTATE. Do not assume a root
   cause based on an HTTP status alone.
6. For Gold: configure `AEGIS_METAAPI_TOKEN`,
   `AEGIS_METAAPI_ACCOUNT_ID` and `AEGIS_CONTROL_TOKEN` in Preview secrets,
   using a verified DEMO / investor-only account. MetaApi trades are **read
   only** and cannot count as Bitcoin Kraken Paper fills.
7. **Do not** authorize any live-money or broker-demo order placement through
   this integration. Backtest, OOS and synthetic fixtures are separate from
   independently recorded forward fills.

## Anti-goals

Do not claim zero drawdown, zero failure, automatic profits, or completed
testing just because all UI elements show healthy. If no verified forward
receipts exist the honest state is `NO_EVIDENCE`/`UNVERIFIED`.
