# AEGIS Micro Research Worker — independent process

**Mode: public market data + independent virtual paper accounts ONLY.**
No funding, exchange API key, OANDA token, trading account, or broker order
endpoint. The old Neon hourly Shadow/Paper engine remains separate.

## Verified design

- Kraken Spot WebSocket v2 `ohlc`, `BTC/USD`, interval 1, 5 and 15 minutes.
- Trade-event updates are not final candles. A new interval is required
  to close the previous one. A snapshot or a repeated update cannot trade.
- Each reconnection warms up indicator history via public Kraken REST.
  Restart is never allowed to reconstruct imaginary historical fills.
- Only closed, contiguous candles trigger research signals; entry uses
  the observed *next* interval open within 10 seconds. If the first trade
  arrives late, entry is skipped (no retroactive fill).
- EMA Cross and Channel Breakout each run in 1, 5 and 15 minute
  **independent micro paper** books. Every trade includes modeled
  fees/slippage; position notional <= 20% of simulated balance,
  budgeted initial price-stop risk 0.25%, 5% latched drawdown halt.
- Neon table `aegis.stream_bar_ledger` ensures each completed candle is
  processed exactly once, transactionally, across reconnects/replicas.
- Risk stops have precedence over targets on ambiguous OHLC candles,
  including pessimistic gaps.
- **Not exchange-grade tick execution:** OHLC feeds cannot prove which
  threshold came first inside the bar, real spreads, fill probability,
  queue position, or latency. Simulated fills are explicitly hypothetical.

## Start on an always-running container (not Vercel Functions)

1. Apply the idempotent `sql/005_stream_research.sql` migration to the
   same Neon branch as Agent City (if not already applied).
2. Run from project root:
   ```sh
   pip install -r requirements-stream.txt
   DATABASE_URL="<your Neon pooled database URL>" AEGIS_STREAM_SYMBOLS=BTC \
       python -m aegis.stream_worker
   ```
   Or build `docker build -f Dockerfile.stream -t aegis-micro .` and
   run the container with `DATABASE_URL` set through hosting secrets.
3. Deploy **one** always-on worker (Railway, VPS or equivalent).
   The dashboard reads Neon; it does not need broker secrets.
4. Observe `aegis.stream_status` and `aegis.stream_bar_ledger` for
   fresh time stamps. Trade/activity rows are created only on real,
   new completed candles *after* the worker begins.
5. Never paste the DATABASE_URL or other credentials into a chat,
   GitHub issue, code file or browser field. Restrict DB privileges in
   the final deployment and monitor database storage/credits.

Gold **is not streamed by this worker**: Twelve Data's historical feed
and the configured paper-only gold lab remain separate. XAU/USD
low-latency data requires verifying the provider plan and instrument
permissions before implementing a different source. DO NOT pass
OANDA Live credentials into the micro worker.

### Deployment scope

Keep `agent-city-v1` separate from `Bot`. Never deploy this as a
live order execution worker or alter brokerage permissions. This process
needs an independent always-running host; Vercel's request/response
functions cannot hold the required WebSocket connection indefinitely.
