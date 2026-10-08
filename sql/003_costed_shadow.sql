-- Stage 4: costed forward shadow execution. Each agent runs an isolated virtual account.
-- Safe additive DDL; no inserts/backfill of historical trades and no live orders.
CREATE TABLE IF NOT EXISTS aegis.shadow_accounts (
  agent_id TEXT PRIMARY KEY,
  starting_equity NUMERIC(20,8) NOT NULL DEFAULT 100000,
  cash NUMERIC(20,8) NOT NULL DEFAULT 100000,
  realized_pnl NUMERIC(20,8) NOT NULL DEFAULT 0,
  peak_equity NUMERIC(20,8) NOT NULL DEFAULT 100000,
  max_drawdown NUMERIC(14,10) NOT NULL DEFAULT 0,
  initialized_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS aegis.shadow_positions (
  agent_id TEXT PRIMARY KEY REFERENCES aegis.shadow_accounts(agent_id),
  position_id TEXT UNIQUE NOT NULL,
  signal_key TEXT UNIQUE NOT NULL,
  symbol TEXT NOT NULL,
  opened_at TIMESTAMPTZ NOT NULL,
  raw_entry NUMERIC(20,8) NOT NULL,
  entry_price NUMERIC(20,8) NOT NULL,
  qty NUMERIC(28,12) NOT NULL,
  stop_price NUMERIC(20,8) NOT NULL,
  target_price NUMERIC(20,8) NOT NULL,
  entry_fee NUMERIC(20,8) NOT NULL,
  entry_slippage NUMERIC(20,8) NOT NULL,
  last_mark NUMERIC(20,8),
  unrealized_pnl NUMERIC(20,8) NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS aegis.shadow_trades (
  trade_id TEXT PRIMARY KEY,
  position_id TEXT NOT NULL UNIQUE,
  agent_id TEXT NOT NULL REFERENCES aegis.shadow_accounts(agent_id),
  signal_key TEXT NOT NULL UNIQUE,
  symbol TEXT NOT NULL,
  opened_at TIMESTAMPTZ NOT NULL,
  closed_at TIMESTAMPTZ NOT NULL,
  raw_entry NUMERIC(20,8) NOT NULL,
  entry_price NUMERIC(20,8) NOT NULL,
  exit_price NUMERIC(20,8) NOT NULL,
  qty NUMERIC(28,12) NOT NULL,
  gross_pnl NUMERIC(20,8) NOT NULL,
  entry_fee NUMERIC(20,8) NOT NULL,
  exit_fee NUMERIC(20,8) NOT NULL,
  slippage_cost NUMERIC(20,8) NOT NULL,
  net_pnl NUMERIC(20,8) NOT NULL,
  r_multiple NUMERIC(20,8) NOT NULL,
  reason TEXT NOT NULL,
  evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
  ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS shadow_trades_agent_time ON aegis.shadow_trades(agent_id, closed_at DESC);
CREATE INDEX IF NOT EXISTS shadow_positions_symbol ON aegis.shadow_positions(symbol);
