-- AEGIS bounded research experiment switches. No capital, broker, or order permissions.
CREATE TABLE IF NOT EXISTS aegis.experiment_controls (
  singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  assets TEXT[] NOT NULL DEFAULT ARRAY['BTC','XAU']::TEXT[],
  strategies TEXT[] NOT NULL DEFAULT ARRAY['EMA Cross','RSI Pullback','Channel Breakout']::TEXT[],
  max_candidates INTEGER NOT NULL DEFAULT 6 CHECK (max_candidates BETWEEN 1 AND 6),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO aegis.experiment_controls(singleton) VALUES(TRUE)
ON CONFLICT(singleton) DO NOTHING;
