-- Dedicated market observation tables. No order or existing Bot tables change.
CREATE TABLE IF NOT EXISTS aegis.chart_snapshots (
    source_id text PRIMARY KEY,
    source text NOT NULL CHECK(source IN ('KRAKEN_WS','TRADINGVIEW_DESKTOP','TWELVE_DATA_REST')),
    symbol text NOT NULL,
    interval_minutes integer NOT NULL CHECK(interval_minutes IN (5,15,60,240)),
    snapshot_id text NOT NULL,
    observed_at timestamptz NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now(),
    payload jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS aegis.chart_vision_reports (
    source_id text PRIMARY KEY REFERENCES aegis.chart_snapshots(source_id),
    snapshot_id text NOT NULL,
    image_sha256 text NOT NULL,
    observed_at timestamptz NOT NULL,
    analyzed_at timestamptz NOT NULL DEFAULT now(),
    report jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS aegis.chart_job_limits (
    job_key text PRIMARY KEY,
    last_started_at timestamptz NOT NULL DEFAULT now()
);
-- Only the market-worker roles already used by this application get access.
DO $$ BEGIN
  IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='aegis_micro_limited') THEN
    GRANT SELECT, INSERT, UPDATE ON aegis.chart_snapshots TO aegis_micro_limited;
  END IF;
  IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='aegis_stream_worker') THEN
    GRANT SELECT, INSERT, UPDATE ON aegis.chart_snapshots TO aegis_stream_worker;
  END IF;
END $$;
