-- 008: Add short-only independent virtual cohort alongside existing long.
-- All existing micro positions/accounts remain LONG by default. No brokers.
ALTER TABLE aegis.stream_accounts
  ADD COLUMN IF NOT EXISTS direction TEXT NOT NULL DEFAULT 'LONG'
  CHECK(direction IN ('LONG','SHORT'));
ALTER TABLE aegis.stream_positions
  ADD COLUMN IF NOT EXISTS direction TEXT NOT NULL DEFAULT 'LONG'
  CHECK(direction IN ('LONG','SHORT'));
ALTER TABLE aegis.stream_trades
  ADD COLUMN IF NOT EXISTS direction TEXT NOT NULL DEFAULT 'LONG'
  CHECK(direction IN ('LONG','SHORT'));
ALTER TABLE aegis.stream_trades
  ADD COLUMN IF NOT EXISTS financing_cost NUMERIC(24,8) NOT NULL DEFAULT 0
  CHECK(financing_cost>=0);
CREATE INDEX IF NOT EXISTS stream_trades_side_horizon_idx
  ON aegis.stream_trades(symbol,direction,interval_minutes,closed_at DESC);
