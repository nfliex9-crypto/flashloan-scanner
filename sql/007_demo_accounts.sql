-- 007: Broker-authoritative DEMO execution indexes. Never store credentials
-- or historical price bars here; each provider retains its native history.
CREATE TABLE IF NOT EXISTS aegis.demo_account_state (
    source_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL CHECK(provider IN ('MT5_DEMO','BINANCE_SPOT_DEMO')),
    market TEXT NOT NULL,
    account_type TEXT NOT NULL DEFAULT 'DEMO' CHECK(account_type='DEMO'),
    currency TEXT,
    balance NUMERIC(25,8),
    equity NUMERIC(25,8),
    open_positions JSONB NOT NULL DEFAULT '[]'::jsonb,
    open_orders JSONB NOT NULL DEFAULT '[]'::jsonb,
    spot_balances JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_of_truth TEXT NOT NULL,
    last_synced TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_status TEXT NOT NULL DEFAULT 'CONNECTED_DEMO'
);
CREATE TABLE IF NOT EXISTS aegis.demo_fills (
    source_id TEXT NOT NULL REFERENCES aegis.demo_account_state(source_id),
    external_id TEXT NOT NULL,
    order_id TEXT,
    position_id TEXT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
    entry_kind TEXT,
    price NUMERIC(25,10) NOT NULL CHECK(price>0),
    qty NUMERIC(25,12) NOT NULL CHECK(qty>0),
    fee NUMERIC(25,10),
    fee_asset TEXT,
    net_pnl NUMERIC(25,10),
    executed_at TIMESTAMPTZ NOT NULL,
    agent_id TEXT,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(source_id,external_id)
);
CREATE INDEX IF NOT EXISTS demo_fills_executed_idx ON aegis.demo_fills(executed_at DESC);
