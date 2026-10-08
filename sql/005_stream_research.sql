-- 005: Independent continuous public Kraken research stream. Additive.
-- NEVER stores broker credentials or grants live order permissions.
CREATE TABLE IF NOT EXISTS aegis.stream_candles (
    symbol TEXT NOT NULL CHECK (symbol IN ('BTC','ETH')),
    interval_minutes INTEGER NOT NULL CHECK (interval_minutes IN (1,5,15)),
    bar_start TIMESTAMPTZ NOT NULL,
    open NUMERIC(24,10) NOT NULL CHECK (open>0),
    high NUMERIC(24,10) NOT NULL CHECK (high>0),
    low NUMERIC(24,10) NOT NULL CHECK (low>0),
    close NUMERIC(24,10) NOT NULL CHECK (close>0),
    volume NUMERIC(26,10) NOT NULL DEFAULT 0 CHECK (volume>=0),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    source TEXT NOT NULL DEFAULT 'Kraken public spot WS v2',
    PRIMARY KEY(symbol,interval_minutes,bar_start),
    CHECK(low<=open AND low<=close AND high>=open AND high>=close)
);
CREATE INDEX IF NOT EXISTS stream_candles_time_idx ON aegis.stream_candles(bar_start DESC);

CREATE TABLE IF NOT EXISTS aegis.stream_bar_ledger (
    symbol TEXT NOT NULL CHECK (symbol IN ('BTC','ETH')),
    interval_minutes INTEGER NOT NULL CHECK (interval_minutes IN (1,5,15)),
    bar_start TIMESTAMPTZ NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(symbol,interval_minutes,bar_start)
);
CREATE TABLE IF NOT EXISTS aegis.stream_accounts (
    agent_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL CHECK(symbol IN ('BTC','ETH')),
    interval_minutes INTEGER NOT NULL CHECK(interval_minutes IN (1,5,15)),
    strategy TEXT NOT NULL,
    cash NUMERIC(24,8) NOT NULL DEFAULT 100000,
    peak_equity NUMERIC(24,8) NOT NULL DEFAULT 100000,
    max_drawdown DOUBLE PRECISION NOT NULL DEFAULT 0,
    halted BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS aegis.stream_positions (
    agent_id TEXT PRIMARY KEY REFERENCES aegis.stream_accounts(agent_id),
    position_id TEXT NOT NULL UNIQUE,
    symbol TEXT NOT NULL,
    interval_minutes INTEGER NOT NULL,
    opened_at TIMESTAMPTZ NOT NULL,
    entry_price NUMERIC(24,8) NOT NULL CHECK(entry_price>0),
    qty NUMERIC(24,12) NOT NULL CHECK(qty>0),
    stop_price NUMERIC(24,8) NOT NULL CHECK(stop_price>0),
    target_price NUMERIC(24,8) NOT NULL CHECK(target_price>0),
    entry_fee NUMERIC(24,8) NOT NULL DEFAULT 0,
    entry_slippage NUMERIC(24,8) NOT NULL DEFAULT 0,
    last_mark NUMERIC(24,8) NOT NULL CHECK(last_mark>0)
);
CREATE TABLE IF NOT EXISTS aegis.stream_trades (
    position_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL REFERENCES aegis.stream_accounts(agent_id),
    symbol TEXT NOT NULL,
    interval_minutes INTEGER NOT NULL,
    opened_at TIMESTAMPTZ NOT NULL,
    closed_at TIMESTAMPTZ NOT NULL,
    entry_price NUMERIC(24,8) NOT NULL,
    exit_price NUMERIC(24,8) NOT NULL,
    qty NUMERIC(24,12) NOT NULL,
    entry_fee NUMERIC(24,8) NOT NULL,
    exit_fee NUMERIC(24,8) NOT NULL,
    slippage_cost NUMERIC(24,8) NOT NULL,
    net_pnl NUMERIC(24,8) NOT NULL,
    reason TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'Kraken spot simulated paper',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS stream_trades_closed_idx ON aegis.stream_trades(closed_at DESC);

CREATE TABLE IF NOT EXISTS aegis.stream_status (
    stream_name TEXT PRIMARY KEY,
    state TEXT NOT NULL CHECK(state IN ('STARTING','CONNECTED','DEGRADED','DISCONNECTED')),
    last_message_at TIMESTAMPTZ,
    last_closed_bar TIMESTAMPTZ,
    last_error TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    mode TEXT NOT NULL DEFAULT 'PUBLIC_DATA_SHADOW_ONLY'
);
