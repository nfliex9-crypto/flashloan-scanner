-- AEGIS Persistent Paper Broker schema.
-- Non-destructive migration: only creates the aegis schema, tables and indexes.

CREATE SCHEMA IF NOT EXISTS aegis;

CREATE TABLE IF NOT EXISTS aegis.paper_accounts (
  account_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  currency TEXT NOT NULL DEFAULT 'USD',
  starting_equity NUMERIC(20,8) NOT NULL,
  cash NUMERIC(20,8) NOT NULL,
  realized_pnl NUMERIC(20,8) NOT NULL DEFAULT 0,
  peak_equity NUMERIC(20,8) NOT NULL,
  circuit_state TEXT NOT NULL DEFAULT 'OPEN',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS aegis.agent_registry (
  agent_id TEXT PRIMARY KEY,
  asset TEXT NOT NULL,
  strategy TEXT NOT NULL,
  generation INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL,
  survival_score NUMERIC(10,4) NOT NULL DEFAULT 0,
  config JSONB NOT NULL DEFAULT '{}'::jsonb,
  evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS aegis.signals (
  signal_key TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  candle_ts TIMESTAMPTZ NOT NULL,
  side TEXT NOT NULL,
  signal_price NUMERIC(20,8),
  decision TEXT NOT NULL,
  reason TEXT,
  snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS aegis.paper_orders (
  order_id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL,
  signal_key TEXT NOT NULL UNIQUE,
  agent_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  order_type TEXT NOT NULL,
  qty NUMERIC(28,12),
  requested_price NUMERIC(20,8),
  stop_price NUMERIC(20,8),
  target_price NUMERIC(20,8),
  status TEXT NOT NULL,
  submitted_at TIMESTAMPTZ NOT NULL,
  filled_at TIMESTAMPTZ,
  closed_at TIMESTAMPTZ,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS aegis.paper_fills (
  fill_id TEXT PRIMARY KEY,
  order_id TEXT NOT NULL,
  fill_kind TEXT NOT NULL,
  fill_ts TIMESTAMPTZ NOT NULL,
  fill_price NUMERIC(20,8) NOT NULL,
  qty NUMERIC(28,12) NOT NULL,
  fee NUMERIC(20,8) NOT NULL DEFAULT 0,
  slippage_cost NUMERIC(20,8) NOT NULL DEFAULT 0,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS aegis.paper_positions (
  position_id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  qty NUMERIC(28,12) NOT NULL,
  entry_price NUMERIC(20,8) NOT NULL,
  stop_price NUMERIC(20,8),
  target_price NUMERIC(20,8),
  opened_at TIMESTAMPTZ NOT NULL,
  status TEXT NOT NULL,
  last_mark_price NUMERIC(20,8),
  unrealized_pnl NUMERIC(20,8) NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(account_id, agent_id, symbol, status)
);

CREATE TABLE IF NOT EXISTS aegis.paper_trades (
  trade_id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  entry_ts TIMESTAMPTZ NOT NULL,
  exit_ts TIMESTAMPTZ NOT NULL,
  entry_price NUMERIC(20,8) NOT NULL,
  exit_price NUMERIC(20,8) NOT NULL,
  qty NUMERIC(28,12) NOT NULL,
  gross_pnl NUMERIC(20,8) NOT NULL,
  fees NUMERIC(20,8) NOT NULL DEFAULT 0,
  slippage_cost NUMERIC(20,8) NOT NULL DEFAULT 0,
  net_pnl NUMERIC(20,8) NOT NULL,
  r_multiple NUMERIC(20,8),
  exit_reason TEXT NOT NULL,
  evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS aegis.ghost_trades (
  ghost_id TEXT PRIMARY KEY,
  signal_key TEXT NOT NULL UNIQUE,
  agent_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  signal_ts TIMESTAMPTZ NOT NULL,
  signal_price NUMERIC(20,8) NOT NULL,
  reason TEXT NOT NULL,
  settlement_due_at TIMESTAMPTZ NOT NULL,
  settled_at TIMESTAMPTZ,
  forward_return NUMERIC(20,10),
  outcome JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS aegis.equity_curve (
  point_id BIGSERIAL PRIMARY KEY,
  account_id TEXT NOT NULL,
  ts TIMESTAMPTZ NOT NULL,
  cash NUMERIC(20,8) NOT NULL,
  realized_pnl NUMERIC(20,8) NOT NULL,
  unrealized_pnl NUMERIC(20,8) NOT NULL,
  equity NUMERIC(20,8) NOT NULL,
  peak_equity NUMERIC(20,8) NOT NULL,
  drawdown NUMERIC(20,10) NOT NULL,
  source_run_id TEXT NOT NULL,
  UNIQUE(account_id, ts, source_run_id)
);

CREATE TABLE IF NOT EXISTS aegis.intelligence_events (
  event_key TEXT PRIMARY KEY,
  symbol TEXT NOT NULL,
  source TEXT NOT NULL,
  event_type TEXT NOT NULL,
  source_event_ts TIMESTAMPTZ,
  disclosed_at TIMESTAMPTZ,
  ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  score NUMERIC(10,4),
  direction TEXT,
  execution_eligible BOOLEAN NOT NULL DEFAULT FALSE,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS aegis.engine_runs (
  run_id TEXT PRIMARY KEY,
  started_at TIMESTAMPTZ NOT NULL,
  completed_at TIMESTAMPTZ,
  mode TEXT NOT NULL,
  status TEXT NOT NULL,
  market_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
  summary JSONB NOT NULL DEFAULT '{}'::jsonb,
  error TEXT
);

CREATE TABLE IF NOT EXISTS aegis.audit_events (
  event_id BIGSERIAL PRIMARY KEY,
  event_key TEXT NOT NULL UNIQUE,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  occurred_at TIMESTAMPTZ NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_signals_agent_candle ON aegis.signals(agent_id, candle_ts DESC);
CREATE INDEX IF NOT EXISTS idx_orders_status ON aegis.paper_orders(status, submitted_at DESC);
CREATE INDEX IF NOT EXISTS idx_positions_status ON aegis.paper_positions(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_trades_agent_exit ON aegis.paper_trades(agent_id, exit_ts DESC);
CREATE INDEX IF NOT EXISTS idx_ghost_due ON aegis.ghost_trades(settled_at, settlement_due_at);
CREATE INDEX IF NOT EXISTS idx_equity_account_ts ON aegis.equity_curve(account_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_intel_symbol_time ON aegis.intelligence_events(symbol, ingested_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON aegis.audit_events(entity_type, entity_id, occurred_at DESC);
