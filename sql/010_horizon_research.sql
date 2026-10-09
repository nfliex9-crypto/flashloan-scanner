-- Widen only the independent public-data paper ledger, preserving all rows.
ALTER TABLE aegis.stream_candles DROP CONSTRAINT IF EXISTS stream_candles_interval_minutes_check;
ALTER TABLE aegis.stream_candles ADD CONSTRAINT stream_candles_interval_minutes_check CHECK(interval_minutes IN (1,5,15,60,240,1440,10080));
ALTER TABLE aegis.stream_bar_ledger DROP CONSTRAINT IF EXISTS stream_bar_ledger_interval_minutes_check;
ALTER TABLE aegis.stream_bar_ledger ADD CONSTRAINT stream_bar_ledger_interval_minutes_check CHECK(interval_minutes IN (1,5,15,60,240,1440,10080));
ALTER TABLE aegis.stream_accounts DROP CONSTRAINT IF EXISTS stream_accounts_interval_minutes_check;
ALTER TABLE aegis.stream_accounts ADD CONSTRAINT stream_accounts_interval_minutes_check CHECK(interval_minutes IN (1,5,15,60,240,1440,10080));
ALTER TABLE aegis.stream_decisions DROP CONSTRAINT IF EXISTS stream_decisions_interval_minutes_check;
ALTER TABLE aegis.stream_decisions ADD CONSTRAINT stream_decisions_interval_minutes_check CHECK(interval_minutes IN (1,5,15,60,240,1440,10080));
CREATE TABLE IF NOT EXISTS aegis.stream_historical_screens (
    agent_id TEXT PRIMARY KEY,
    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    evidence JSONB NOT NULL
);
