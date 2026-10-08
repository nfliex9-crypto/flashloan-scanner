-- Indexed costed micro trade evidence for automatic forward-only quarantine.
-- Additive; never modifies an existing trade or opens broker orders.
CREATE INDEX IF NOT EXISTS stream_trades_agent_closed_idx
    ON aegis.stream_trades(agent_id,closed_at DESC);
