# AEGIS Stage 3 — Living Agent City / Implementation Blueprint

This document describes deployed source on `agent-city-v1`. It separates what is live, what is scheduled, and what is future work.

## Status and safety
- **Neon forward ledger** is authoritative. Python broker on Vercel handles virtual orders, risk, trades and fills.
- Neon `aegisscheduler` trigger executes at `5 * * * *` UTC; candles are Kraken 1h OHLC, not a broker-level tick stream.
- Real-money order placement is disabled.
- `city.html` is the interactive Stage 3 experience; `city-legacy.html` retains the classic dashboard.
- Research replay from `/api/city` is never presented as forward P&L.
- Stage 3 promotes **nothing** from 12h ghost results alone: costed forward or costed shadow fills and adequate sample periods are required.
- Research ACTIVE is **not** a proven profitable champion.

## Live architecture
```
Kraken 1h candles -> aegis.forward_broker.run_forward_tick()
                   -> hard risk gates / paper orders / paper fills
                   -> Neon: paper_accounts, paper_positions, paper_trades,
                      ghost_trades, equity_curve, agent_registry, engine_runs
                   -> aegis.stage3.review_run() in SAME TRANSACTION
                   -> agent_evaluations, agent_allocations, evolution_events,
                      live_events
                   -> api/stage3.py (read-only)
                   -> city.js polling 15s + data-driven visuals

FINRA public feed -> aegis.intelligence_ledger.collect_intelligence()
                  -> intelligence_snapshots (idempotent by source+symbol+date)
                  -> live_events (source available context; not trade signals)
                  -> api/intelligence_cron.py daily at 23:30 UTC in
                     vercel.json, ACTIVE ONLY AFTER PRODUCTION DEPLOY
```

## UI design — user interaction
- `city.html`: routes/tabs for City, Payroll, Evolution, Intelligence; inline animated SVG with agent districts and central vault.
- `city.css`: immersive dark purple cyber-city design, animated buildings, responsive iPhone pan/worker carousel and accessibility settings.
- `city.js`: read-only REST fetches of Neon, event reconciliation, trade-dependent beam effects, equity sparkline, payroll, evolution cards, source freshness.
- The vault and each worker tower open factual server-backed inspector drawers.
- Only **new persisted PAPER_EXIT** events animate money moving to/from the vault. Ambient animation is decorative.
- The client never writes to the broker or sizes positions.

## Backend files
- `aegis/forward_broker.py`: hard-risk forward paper execution; allocation multiplier <= 1 and blocked evolution states.
- `aegis/stage3.py`: windowed forward evidence, fail-closed role changes, audit/event publishing and read-only living city projection.
- `aegis/intelligence_ledger.py`: time-stamped fresh FINRA snapshots; separates data event time from ingestion time.
- `api/stage3.py`: GET living city data.
- `api/intelligence_tick.py`: POST key-protected intelligence ingestion.
- `api/intelligence_cron.py`: GET Vercel CRON_SECRET protected daily ingestion.
- `sql/002_stage3_living_city.sql`: additive migration defining live_events, agent_evaluations, agent_allocations, evolution_events and intelligence_snapshots.
- `tests/test_stage3.py` and `tests/test_intelligence_ledger.py`: risk/promotion and timestamp tests; CI now verifies `node --check city.js`.

## Risk constitution
- Existing paper risk per trade: 0.25% of equity.
- Portfolio notional cap: 35%; no more than 2 concurrent positions.
- Daily realized loss halt: 1% of initial equity; portfolio drawdown halt: 5%.
- Stage 3 multiplier cannot exceed 1; role other than ACTIVE_PAPER blocks paper orders.
- A HALTED agent does not auto-rearm, even if research performance recovers.
- Ghost 12h outcomes are explicitly *observations*, not comparable costed fills.
- At least 30 forward days, 40 costed trades, profit factor >=1.30 and DD <5% for evaluation; insufficient observations cannot imply skill.

## Real-time truth
- Operational events are recorded in Neon. The browser polls every 15s; that does NOT mean the strategy trades every 15s.
- The engine runs hourly (trigger `:05 UTC`), so market and P&L changes are discrete.
- Archived historical hourly forward runs were imported as actual `ENGINE_TICK` event logs, clearly labeled as archived, not fabricated trades.
- FINRA daily short-sale volume is NOT short interest; SEC forms are NOT inferred buying direction. Quiver is optional and not connected.
- `/api/intelligence` is live context but SEC may return HTTP 403 from serverless; unavailable/stale sources are excluded.

## Release conditions
- GitHub Actions full pytest + JavaScript syntax must pass.
- Vercel branch preview must reach READY; `/city.html`, `/api/stage3`, `/api/city` and `/api/intelligence` must return 200.
- Stage 3 evolution integration is only proven end-to-end after the next new hourly candle completes and creates `agent_evaluations` and `live_events`.
- Vercel Cron daily intelligence ingestion requires Production deployment; previews do not execute cron.
- No move to real-money trading without user approval, broker integration, 30+ days of forward testing and credible costs/slippage.

## Next engineering milestones
1. **Costed shadow broker** with independent virtual fills and identical execution modeling to incumbent workers (required before challenger promotion).
2. Equity execution feed for SPY/QQQ/NVDA/TSLA with market calendars, adjusted prices and verifiable market data; current equities are intelligence-only.
3. Source-correct SEC access with a legitimate compliant request origin; record disclosure/publication time to prevent look-ahead.
4. Forward trade autopsy drawer with price chart, entry/exit markers, and saved decision snapshots.
5. Mobile performance profiling and richer WebGL/3D tower transitions after correctness tests.

_This project is experimental research software. Nothing guarantees profit or prevents losses._
