-- MT5 Demo enrollment. Apply only to the isolated AEGIS research database.
-- Pairing secrets are never stored in plaintext; no broker login/password.
CREATE TABLE IF NOT EXISTS aegis.mt5_pairings (
    pairing_id BIGSERIAL PRIMARY KEY,
    token_sha256 CHAR(64) NOT NULL UNIQUE,
    state TEXT NOT NULL CHECK (state IN ('PENDING','ACTIVE','REVOKED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    source_id TEXT,
    market TEXT,
    last_synced TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS mt5_pairings_state_idx
    ON aegis.mt5_pairings(state,last_synced DESC);
-- Existing broker-ledger schema is in sql/007_demo_accounts.sql.
-- Grant SELECT/INSERT/UPDATE on this table and USAGE/SELECT on its
-- sequence only to the restricted AEGIS preview bridge database role.
