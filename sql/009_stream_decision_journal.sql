-- Compact auditable decisions from real CLOSED Kraken micro candles only.
-- Includes WAIT/MARK/risk-veto as well as ENTER/EXIT, not just trade fills.
-- No credentials, predictions, secrets, broker order permissions or tick payloads.
CREATE TABLE IF NOT EXISTS aegis.stream_decisions (
    agent_id TEXT NOT NULL REFERENCES aegis.stream_accounts(agent_id),
    bar_start TIMESTAMPTZ NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    symbol TEXT NOT NULL CHECK(symbol IN ('BTC','ETH')),
    interval_minutes INTEGER NOT NULL CHECK(interval_minutes IN (1,5,15)),
    strategy TEXT NOT NULL,
    direction TEXT NOT NULL CHECK(direction IN ('LONG','SHORT')),
    action TEXT NOT NULL CHECK(action IN ('WAIT','MARK','ENTER','EXIT','VETO')),
    reason TEXT NOT NULL,
    reference_price NUMERIC(24,10) NOT NULL CHECK(reference_price>0),
    position_id TEXT,
    qty NUMERIC(24,12),
    risk_stop NUMERIC(24,10),
    risk_target NUMERIC(24,10),
    net_pnl NUMERIC(24,10),
    source TEXT NOT NULL DEFAULT 'KRAKEN_CLOSED_CANDLE_MICRO_PAPER',
    PRIMARY KEY(agent_id,bar_start)
);
CREATE INDEX IF NOT EXISTS stream_decisions_recent_idx ON aegis.stream_decisions(observed_at DESC);
