"""Read-only AEGIS operational canaries (Vibe-Trading-inspired, not a dependency).

Never infers a healthy deployment from static markup or configured secrets.
Inspects only persisted Neon receipts; executes no broker API calls, no data
migrations, no strategy orders and no SQL mutations.
"""
from __future__ import annotations

from datetime import datetime, timezone

CORE_PAPER_TABLES = (
    "engine_runs", "paper_accounts", "paper_positions", "paper_trades",
    "shadow_positions", "agent_registry", "agent_allocations", "equity_curve",
    "signals", "ghost_trades", "experiment_controls",
)
STREAM_TABLES = ("stream_status", "stream_accounts", "stream_candles",
                 "stream_decisions", "stream_trades")
DEMO_TABLES = ("demo_account_state", "demo_fills")
TIMEFRAMES = (1, 5, 15, 60, 240, 1440, 10080)


def freshness(ts: datetime | None, *, now: datetime, limit_seconds: int) -> str:
    if ts is None or not isinstance(ts, datetime) or ts.tzinfo is None:
        return "NO_EVIDENCE"
    age = (now - ts.astimezone(timezone.utc)).total_seconds()
    return "CURRENT" if 0 <= age < limit_seconds else "STALE"


def inspect_persisted(cur, *, now: datetime | None = None) -> dict:
    """Build status from real tables; errors fail closed without echoing DB secrets."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("UTC-aware diagnostic clock required")
    now = now.astimezone(timezone.utc)
    tables = CORE_PAPER_TABLES + STREAM_TABLES + DEMO_TABLES
    existence = {}
    for table in tables:
        cur.execute("SELECT to_regclass(%s) IS NOT NULL AS present", ("aegis." + table,))
        row = cur.fetchone()
        existence[table] = bool(row and row.get("present"))
    core_missing = [x for x in CORE_PAPER_TABLES if not existence[x]]
    stream_missing = [x for x in STREAM_TABLES if not existence[x]]
    demo_missing = [x for x in DEMO_TABLES if not existence[x]]

    def latest_run(mode: str, stale_after: int) -> dict:
        if "engine_runs" in core_missing:
            return {"state": "SCHEMA_MISSING", "last_completed_at": None}
        try:
            cur.execute(
                "SELECT max(completed_at) AS ts FROM aegis.engine_runs "
                "WHERE mode=%s AND status='COMPLETED'", (mode,))
            value = cur.fetchone()
            ts = value.get("ts") if value else None
        except Exception:
            # A broken runtime schema/permission is not a successful heartbeat.
            return {"state": "READ_FAILED", "last_completed_at": None}
        return {"state": freshness(ts,now=now,limit_seconds=stale_after),
                "last_completed_at": ts.isoformat() if isinstance(ts, datetime) else None}

    def paper_source_status() -> dict:
        if stream_missing:
            return {"state": "SCHEMA_MISSING", "healthy_intervals_minutes": [],
                    "expected_intervals_minutes": list(TIMEFRAMES),
                    "missing_tables": stream_missing}
        try:
            cur.execute(
                "SELECT stream_name,state,updated_at FROM aegis.stream_status "
                "WHERE stream_name LIKE 'kraken-public-micro-%' ORDER BY updated_at DESC LIMIT 30")
            streams = list(cur.fetchall())
        except Exception:
            return {"state": "READ_FAILED", "healthy_intervals_minutes": [],
                    "expected_intervals_minutes": list(TIMEFRAMES)}
        healthy = []
        for minute in TIMEFRAMES:
            name = f"kraken-public-micro-{minute}m"
            matching = [r for r in streams if r.get("stream_name") == name]
            if any(r.get("state") == "CONNECTED" and freshness(
                    r.get("updated_at"),now=now,limit_seconds=180) == "CURRENT"
                   for r in matching):
                healthy.append(minute)
        state = ("ALL_VERIFIED" if len(healthy) == len(TIMEFRAMES) else
                 "PARTIAL_VERIFIED" if healthy else "NO_FRESH_EVIDENCE")
        return {"state": state, "healthy_intervals_minutes": healthy,
                "expected_intervals_minutes": list(TIMEFRAMES),
                "missing_intervals_minutes": [n for n in TIMEFRAMES if n not in healthy]}

    def gold_status() -> dict:
        if demo_missing:
            return {"state": "SCHEMA_MISSING", "last_synced_at": None}
        try:
            cur.execute(
                "SELECT max(last_synced) AS ts FROM aegis.demo_account_state "
                "WHERE provider='MT5_DEMO'")
            row = cur.fetchone()
            ts = row.get("ts") if row else None
        except Exception:
            return {"state": "READ_FAILED", "last_synced_at": None}
        return {"state": freshness(ts,now=now,limit_seconds=300),
                "last_synced_at": ts.isoformat() if isinstance(ts,datetime) else None}

    return {
        "ok": True, "mode": "SOURCE_BACKED_READ_ONLY_DIAGNOSTICS",
        "checked_at": now.isoformat(),
        "database": {"state": "CONNECTED", "read_only": True},
        "forward_paper_schema": {
            "state": "READY" if not core_missing else "SCHEMA_MISSING",
            "missing_tables": core_missing},
        "market_monitor": latest_run("MARKET_MONITOR", 45*60),
        "hourly_forward": latest_run("FORWARD_PAPER", 2*3600),
        "kraken_paper": paper_source_status(),
        "mt5_demo": gold_status(),
        "live_execution_enabled": False,
        "demo_order_execution_enabled": False,
        "provenance": {
            "monitor": "Neon aegis.engine_runs completed receipts",
            "market_data": "Neon aegis.stream_status real Kraken worker heartbeats",
            "gold": "Neon MT5 Demo broker-confirmed last_synced",
            "backtests_are_forward_evidence": False,
        },
    }


def diagnose() -> dict:
    from .forward_broker import _connect
    try:
        with _connect() as conn, conn.cursor() as cur:
            return inspect_persisted(cur)
    except Exception:
        # Do not log or return connection strings, SQL errors or passwords.
        return {"ok": True, "mode": "SOURCE_BACKED_READ_ONLY_DIAGNOSTICS",
                "database": {"state": "UNAVAILABLE", "read_only": True},
                "forward_paper_schema": {"state": "UNVERIFIED"},
                "market_monitor": {"state": "UNVERIFIED"},
                "hourly_forward": {"state": "UNVERIFIED"},
                "kraken_paper": {"state": "UNVERIFIED", "healthy_intervals_minutes": [],
                                "expected_intervals_minutes": list(TIMEFRAMES)},
                "mt5_demo": {"state": "UNVERIFIED"},
                "live_execution_enabled": False,
                "demo_order_execution_enabled": False,
                "provenance": {"backtests_are_forward_evidence": False}}
