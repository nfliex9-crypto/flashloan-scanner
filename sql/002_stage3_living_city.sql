-- AEGIS Stage 3 | additive only; no modifications to existing data
CREATE TABLE IF NOT EXISTS aegis.live_events (
  event_key TEXT PRIMARY KEY,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  event_type TEXT NOT NULL,
  scope TEXT NOT NULL DEFAULT 'SYSTEM',
  agent_id TEXT,
  symbol TEXT,
  severity TEXT NOT NULL DEFAULT 'info',
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  amount NUMERIC(20,8),
  origin_run_id TEXT,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS live_events_by_time ON aegis.live_events(created_at DESC);
CREATE TABLE IF NOT EXISTS aegis.agent_evaluations (
  agent_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  evaluated_at TIMESTAMPTZ NOT NULL,
  research_status TEXT NOT NULL,
  role TEXT NOT NULL,
  closed_trades INTEGER NOT NULL,
  wins INTEGER NOT NULL,
  net_pnl NUMERIC(20,8) NOT NULL,
  profit_factor NUMERIC(16,8) NOT NULL,
  max_drawdown NUMERIC(16,8) NOT NULL,
  forward_days NUMERIC(12,4) NOT NULL,
  eligible BOOLEAN NOT NULL,
  reason TEXT NOT NULL,
  windows JSONB NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY(agent_id,run_id)
);
CREATE INDEX IF NOT EXISTS agent_evaluations_time ON aegis.agent_evaluations(agent_id,evaluated_at DESC);
CREATE TABLE IF NOT EXISTS aegis.agent_allocations (
  agent_id TEXT PRIMARY KEY,
  role TEXT NOT NULL DEFAULT 'SHADOW',
  risk_multiplier NUMERIC(8,4) NOT NULL DEFAULT 0 CHECK (risk_multiplier >= 0 AND risk_multiplier <= 1),
  review_status TEXT NOT NULL DEFAULT 'COLLECTING',
  reason TEXT NOT NULL DEFAULT '',
  last_reviewed_run TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS aegis.evolution_events (
  event_key TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  previous_role TEXT,
  next_role TEXT NOT NULL,
  reason TEXT NOT NULL,
  evidence JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS evolution_events_time ON aegis.evolution_events(created_at DESC);
CREATE TABLE IF NOT EXISTS aegis.intelligence_snapshots (
  snapshot_key TEXT PRIMARY KEY,
  symbol TEXT NOT NULL,
  source TEXT NOT NULL,
  source_event_ts TIMESTAMPTZ,
  disclosed_at TIMESTAMPTZ,
  ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  is_fresh BOOLEAN NOT NULL DEFAULT FALSE,
  attention_score NUMERIC(10,4),
  raw JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS intelligence_snapshots_symbol_time ON aegis.intelligence_snapshots(symbol,ingested_at DESC);