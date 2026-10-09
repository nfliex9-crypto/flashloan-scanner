"""Fail-closed, read-only verification of the independent stream schema.

Migrations live in sql/*.sql and are applied by the authorized Neon
database maintainer, never by Railway's least-privilege market worker.
No CREATE / ALTER / DROP or privilege escalation is performed here.
"""
from __future__ import annotations

from .stream_worker import _connect

REQUIRED_TABLE_PRIVILEGES={
    "stream_candles":("SELECT","INSERT"),
    "stream_bar_ledger":("SELECT","INSERT"),
    "stream_accounts":("SELECT","INSERT","UPDATE"),
    "stream_positions":("SELECT","INSERT","UPDATE","DELETE"),
    "stream_trades":("SELECT","INSERT"),
    "stream_decisions":("SELECT","INSERT"),
    "stream_status":("SELECT","INSERT","UPDATE"),
    "stream_historical_screens":("SELECT","INSERT"),
}
INTERVAL_TABLES=("stream_candles","stream_bar_ledger",
                 "stream_accounts","stream_decisions")


def verify(conn)->dict:
    """Check essential tables, grants and supported timeframes without writes."""
    with conn.cursor() as cur:
        for table,privileges in REQUIRED_TABLE_PRIVILEGES.items():
            qualified="aegis."+table
            cur.execute("SELECT to_regclass(%s) AS present",(qualified,))
            row=cur.fetchone()
            if not row or row["present"] is None:
                raise RuntimeError("Stream database migration missing: "+table)
            for permission in privileges:
                cur.execute(
                    "SELECT has_table_privilege(current_user,%s,%s) AS allowed",
                    (qualified,permission))
                permission_row=cur.fetchone()
                if not permission_row or not permission_row["allowed"]:
                    raise RuntimeError("Stream database privilege missing: "+table+"/"+permission)
        for table in INTERVAL_TABLES:
            cur.execute(
                "SELECT pg_get_constraintdef(c.oid) AS definition FROM pg_constraint c "
                "WHERE c.conrelid=to_regclass(%s) AND c.conname=%s",
                ("aegis."+table,table+"_interval_minutes_check"))
            constraint=cur.fetchone()
            if not constraint or "10080" not in str(constraint["definition"]):
                raise RuntimeError("Seven-timeframe stream migration missing: "+table)
    return {"verified_tables":len(REQUIRED_TABLE_PRIVILEGES),
            "intervals_minutes":[1,5,15,60,240,1440,10080],
            "mode":"READ_ONLY_SCHEMA_VERIFICATION"}


if __name__=="__main__":
    try:
        with _connect() as conn:
            report=verify(conn)
    except Exception:
        # Never echo password-bearing Neon exception strings in host logs.
        raise SystemExit("Stream schema or permission verification failed; "
                         "apply sql/008–010 using the Neon administrator")
    print("Independent stream database verified (read-only, 7 timeframes)")
