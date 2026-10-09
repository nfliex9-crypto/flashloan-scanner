# AEGIS vNext — radical dashboard redesign brief (after engine validation)

**Status:** design backlog, NOT a deployed UI change. Retain the present
`agent-city-v1` UI while functional trading research is under validation.
This plan honors the owner's request to replace the current playful city
layout with a serious research terminal once the engine is stabilized.

## Product target

A professional, information-dense, mobile-friendly trading research cockpit:
market evidence and execution provenance first, illustrations last.
Source-backed prices, authoritative broker-demo account balances, separate
costed shadow/paper PnL, and visible audit trails on every displayed number.
Never mix simulated outcomes with broker-confirmed DEMO fills.

## Proposed navigation and layout

1. **Mission Control:** market/connection status, latency and candle freshness,
   data provider per market, circuit breakers, what is working/not working;
   BTC and gold status side by side, with research-only badges clearly labeled.
2. **Markets:** switch BTC/USD and XAU/USD, 1m/5m/15m/1h/4h/1d/1w
   only when valid feed/provider entitlements exist; synchronized candles,
   regime classification with precise source, no fabricated chart ticks.
3. **Strategy Lab:** LONG/SHORT/BOTH and scalping/intraday/swing/position filters;
   exact backtest assumptions, strategy comparison, 3-fold historical
   walk-forward, chronological holdout, 2x cost stress, forward evidence.
   A HISTORICAL winner does not authorize forward/demonstration execution.
4. **Trade Ledger:** broker-native MT5 DEMO gold and Binance SPOT DEMO BTC
   separated from synthetic Shadow and Micro Paper books; agent, direction,
   entry/exit, fees, financing, drawdown, rationale, timestamp and provenance.
5. **Risk Room:** editable research-only limits ONLY after separate auth;
   drawdown, exposure, quarantine, stale-feed veto, remaining paper risk.
   Real broker execution is always disabled without explicit additional
   user-requested code and verified DEMO entitlement. No live-money mode.
6. **Operations:** Railway stream health, 15m and hourly scheduler activity,
   last clean bar, reconnect count and gap reason, Neon database health,
   deploy/CI versions, unknown/unavailable states surfaced honestly.

## Design constraints

- Replace ornamental buildings/towers with a compact, readable terminal grid;
  accessible and keyboard-navigable on desktop and touch-friendly on mobile.
- Clear hierarchy and one source of truth. Do not infer live trading from a
  merely active WebSocket or from a recently updated chart.
- Use semantic status text + color, not color alone. Avoid dense meaningless
  charts and fake animated activity.
- Mobile first: market switcher, account state, real execution feed and
  fast control affordances must remain accessible without horizontal overflow.
- Avoid leaking API keys, account numbers, signed URLs, database credentials
  or internal stack traces. Separate owner control key and hardcoded demo-only
  provider selection remain mandatory.
- No new styling or redesign is merged until market feeds, paper/demo
  separation, historical validation and dashboard metrics have passed
  measurable functional acceptance checks.

## Acceptance gates before replacing the UI

1. BTC micro worker reliably registers current 1m/5m/15m heartbeats and
   completed candles, no duplicate virtual fills after reconnects.
2. Backtest signals use only completed bars and next-open fills,
   including LONG/SHORT stop and financing cost, with passing CI.
3. Walk-forward gates cannot pass on unclosed unrealized gains or a
   single lucky history window.
4. Demo ledger shows NOT LINKED until an authenticated DEMO account is
   actually connected; never render a synthetic fill as MT5/Binance execution.
5. Vercel returns HTTP 200 for page and Stage3 data; tests and required
   browser event bindings pass.
6. UX sign-off: review with owner before replacing familiar navigation;
   approve layout, density and color direction. Do not decide visual
   aesthetics without the owner's feedback.

**Do not modify branch `Bot` or any production/live trading service.**
