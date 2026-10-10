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

## Additional research systems (user-selected)

| Provider/system | Inspected implementation | Safe AEGIS role | Actual connection |
| --- | --- | --- | --- |
| Fincept Terminal | https://github.com/Fincept-Corporation/FinceptTerminal | Reference for multi-source analytics and UI only; AGPL-3.0-or-later code **not copied or linked** | No account or data API keys configured |
| TypeSafe JEV / Jev Trade | https://github.com/aowang-ai/jev-trade | Maker/taker latency, hold, fill provenance and order lifecycle research only; **no Hyperliquid order calls** | User-owned Railway `resilient-generosity/jev-trade` is a separate online deployment of this repo, not linked to AEGIS or assumed to be in real trading |
| Grok (xAI) | https://docs.x.ai/developers/rest-api-reference/inference/responses | Manual owner-authorized **operational risk commentary** based on Neon canaries, no strategy voting or execution | Requires `XAI_API_KEY` in isolated Vercel Preview; no automatic network calls |
| Vibe-Trading | https://github.com/HKUDS/Vibe-Trading | Evidence provenance, partial source canaries, run diagnostics | Adapted patterns, not installed as a runtime dependency |

The JEV upstream is Bun/Hyperliquid and may submit genuine venue orders
when configured with private keys; its dry-run logic is **not** equivalent
to AEGIS Kraken Paper fills. The existing Railway JEV deployment has no
visible `TYPESAFE_API_KEY`, `AI_GATEWAY_API_KEY` or `PRIVATE_KEY` variable
names as of inspection. The absence of visible variables does not itself
prove the exact model or order behavior; inspect logs and source on every
execution before making any claims.

### Grok integration controls

- `GET /api/stage3?research_advisors=1` exposes only readiness flags,
  **not** credentials or a paid API call.
- `POST /api/stage3?grok_review=1` is owner-authenticated using the separate
  `AEGIS_CONTROL_TOKEN`, checks same-origin, accepts only
  `{"action":"review"}`, and calls xAI at most once per requested invocation.
- Input is a bounded allowlisted projection of documented statuses from
  `aegis.ops_health`. No account IDs, broker records, positions, passwords,
  raw price history, external prompts or arbitrary user text enter the model.
- The model allowlist is `grok-4.3` (default) or `grok-4.7`; up to 256
  output tokens; no tools/function calls; xAI `store=false`.
- The result is untrusted commentary rendered using `textContent`, never
  a strategy filter, portfolio allocation or order.
- xAI calls cost real money, require user provisioning and should never be
  scheduled automatically at a tight cadence. Any cost budget must be
  separately provisioned at xAI; the per-call bound is **not** a total
  spending cap.

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
