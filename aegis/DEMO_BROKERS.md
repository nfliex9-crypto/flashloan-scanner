# AEGIS Broker-Native Demo Ledgers

## Why this exists

The earlier Kraken micro engine records *simulated* positions; it does
not place an order with any broker. These adapters instead read **actual
DEMO server executions**, open positions/orders and balances, so the
broker/exchange becomes the authoritative account ledger.

- **Gold:** Windows MetaTrader 5 desktop terminal logged into a
  broker-provided **DEMO** account that offers an XAUUSD symbol.
  The script checks `account_info().trade_mode == ACCOUNT_TRADE_MODE_DEMO`
  before reading positions or deals. Broker symbols often have suffixes
  like XAUUSDm, GOLD or XAUUSD.a. Choose your broker's exact symbol.
- **Bitcoin:** Binance **Spot Demo Mode** BTCUSDT, using *Demo Mode*
  API credentials generated **inside Binance Demo**, not live keys.
  The endpoint is pinned in source to `https://demo-api.binance.com`.
  This is **spot and long-only**; it does not permit short selling.
  Demo features depend on availability in the user's location.
- Adapters currently perform **GET/read-only reconciliation only**.
  They do not contain `order_send`, Binance `POST /order` or any broker
  order path. Opening automatic demo trades must be implemented and
  deliberately enabled separately after validating account identity,
  risk rules, timestamp freshness and idempotency.
- **Keep micro Shadow and broker-native Demo separate.** Shadow fills
  cannot be reported as broker-confirmed deals. P&L on a Binance
  individual spot fill is unknown; account returns require cost basis
  and whole-account reconciliation. MT5 returns broker-reported
  realized deal P&L.

## Demo setup (no secret in ChatGPT)

### Gold: Windows PC or Windows VPS

1. Install MetaTrader 5 (Windows desktop), sign into a broker **DEMO**
   account and verify an XAU instrument appears in Market Watch.
2. Install Python and dependencies on the same Windows computer:
   ```sh
   py -m pip install MetaTrader5 "psycopg[binary]>=3.2,<4"
   ```
3. Run from the cloned repository's root:
   ```sh
   py -m aegis.demo_sync --provider mt5 --symbol XAUUSD --once
   ```
   Substitute your broker's exact XAU symbol.
   A disconnected terminal, absent symbol or non-DEMO account is
   rejected; no other account is read.
4. After configuring a **dedicated least-privilege** Neon connection
   in local secrets as `AEGIS_DEMO_DATABASE_URL`, remove `--once`
   to sync every 60 seconds. It stores only compact identifiers and
   recent open-state snapshots. The platform and broker still own the
   original order/deal history. Keep Windows terminal running.

### BTC: Binance SPOT Demo Mode (separate API keys)

1. In Binance log into **Demo Trading**, then generate a *DEMO* API
   key there; do not create a live key or use Binance Spot Testnet.
2. Set `BINANCE_DEMO_API_KEY` and `BINANCE_DEMO_API_SECRET` in
   your host's secret environment manager (not GitHub and not chat).
3. Use Python 3.12 and:
   ```sh
   python -m aegis.demo_sync --provider binance --once
   ```
   The adapter requests only `/api/v3/account`,
   `/api/v3/myTrades`, and `/api/v3/openOrders` from the **fixed**
   `demo-api.binance.com` host using authenticated GET requests.
4. After a dedicated least-privilege `AEGIS_DEMO_DATABASE_URL`
   has been configured, enable periodic 60-second syncing. This
   can run in a separate Railway worker once the user's Demo
   credentials are configured. **Do not attach Binance keys to the
   existing Kraken-only worker.**

## Persisted data and privacy

Apply `sql/007_demo_accounts.sql`. Tables `aegis.demo_fills` and
`aegis.demo_account_state` keep **only** provider-specific execution
IDs, time, instrument, side, quantity, price, fee, MT5 broker P&L (if
reported), latest open positions/orders and sync timestamp.
No passwords, account login, secret, signed URL, or historical price
bars are stored in these tables. Individual trade IDs are idempotent
across polling attempts.

**Demo history is not permanent storage.** Brokers can close/reset demo
accounts and API retention may be limited. Therefore a compact local
execution mirror is essential for continuous multi-agent statistics
even though the DEMO platform remains the source of executions.
Binance Spot Testnet resets periodically and is intentionally avoided.

For new micro research experiments, retain forward-only risk filters;
only broker-confirmed Demo fills may appear in the demo dashboard.
When providers are not configured, show NOT LINKED, not mock trades.

**Never paste any API key, Binance secret, Neon URL or MT5 account
password into a chat.** Never enable a live order endpoint. Keep the
separate `Bot` branch and existing live systems untouched.


## Directional research / horizon selection (added 2026-10-08)

The Research Lab now accepts **LONG**, **SHORT** and **BOTH** modes,
from **1min, 5min (scalping)** through **15min, 1h (intraday)**,
**4h, 1day (swing)** and **1week (position research)**.

Directional signals are tested on genuine completed OHLC bars, with
entry at the next bar open. Short positions use the reciprocal price
*solely to derive downside signals*, never as a traded asset.
The simulator books reverse-direction P&L, conservative gap-up stops,
fees, side-aware slippage and an illustrative 2 bps/day short financing
charge (scaled by selected stress mode). This is **not** broker-margin
or liquidation simulation. Gold weekends, exchange holidays, sparse
history and unsupported provider entitlements can cause backtest
requests to fail closed instead of fabricating candles.

The **Adaptive Timeframe Selector** is a *research recommender*, not
an execution router. It compares persisted, costed forward trade
results and refuses to identify a leader without 20+ closed trades,
time-window coverage, positive net returns, PF >= 1.25 and a max
drawdown below 4%. Backtest holdout results do not count toward
forward sample thresholds. It currently only sees long-only BTC
micro shadow evidence; SHORT, gold and weekly forward cohorts are
not yet measured. Until there is enough evidence it reports
INSUFFICIENT_FORWARD_EVIDENCE. No automatic Demo broker or real money
order permission is added.

**Broker capability firewall:** XAUUSD on a verified MT5 DEMO account
can support both LONG/SHORT subject to broker symbol permissions.
Binance **Spot** Demo only supports long spot inventory positions:
a SELL there is reduction/liquidation of owned BTC, **not a short**.
BTC short execution would require a dedicated, separately verified
non-production futures/margin environment, with independent liquidation,
funding and leverage risk rules. The current repo intentionally
provides no order-sending adapter for this.
