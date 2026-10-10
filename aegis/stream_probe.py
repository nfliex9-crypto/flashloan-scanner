"""Read-only introspection of the real Kraken Paper worker's storage contract.

No migrations, no broker operations. Helps distinguish stalled decisions,
schema drift and partial timeframe support before touching Railway.
"""
from __future__ import annotations

from .forward_broker import _connect, _json_safe

REQUIRED_COLUMNS={
    "stream_accounts":("agent_id","symbol","interval_minutes","strategy","direction","cash","halted"),
    "stream_decisions":("agent_id","bar_start","symbol","interval_minutes","strategy","direction","action","observed_at"),
    "stream_bar_ledger":("symbol","interval_minutes","bar_start"),
    "stream_positions":("agent_id","direction","last_mark"),
}
WRITER_PERMISSIONS={
    "stream_accounts":("SELECT","INSERT","UPDATE"),
    "stream_decisions":("SELECT","INSERT"),
    "stream_bar_ledger":("SELECT","INSERT"),
    "stream_positions":("SELECT","INSERT","UPDATE","DELETE"),
    "stream_trades":("SELECT","INSERT"),
}
REQUIRED_INTERVALS=(1,5,15,60,240,1440,10080)


def inspect(cur)->dict:
    output={"ok":True,"mode":"READ_ONLY_STREAM_STORAGE_PROBE",
            "actions_disabled":True,"tables":{},"interval_constraints":{},
            "recent_bar_ledger":[],"recent_decisions":[],
            "short_account_count":None}
    for table in set(REQUIRED_COLUMNS)|set(WRITER_PERMISSIONS):
        fullname="aegis."+table
        cur.execute("SELECT to_regclass(%s) AS rel",(fullname,))
        row=cur.fetchone()
        exists=bool(row and row["rel"] is not None)
        info={"exists":exists,"missing_columns":[],"missing_permissions":[]}
        if exists:
            for col in REQUIRED_COLUMNS.get(table,()):
                cur.execute(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema='aegis' AND table_name=%s AND column_name=%s) AS found",
                    (table,col))
                v=cur.fetchone()
                if not (v and v["found"]):info["missing_columns"].append(col)
            for permission in WRITER_PERMISSIONS.get(table,()):
                cur.execute(
                    "SELECT has_table_privilege(current_user,%s,%s) AS allowed",
                    (fullname,permission))
                v=cur.fetchone()
                if not (v and v["allowed"]):info["missing_permissions"].append(permission)
        output["tables"][table]=info
    for table in ("stream_accounts","stream_bar_ledger","stream_decisions","stream_candles"):
        cur.execute(
            "SELECT pg_get_constraintdef(c.oid) AS definition "
            "FROM pg_constraint c WHERE c.conrelid=to_regclass(%s) AND c.conname=%s",
            ("aegis."+table,table+"_interval_minutes_check"))
        row=cur.fetchone()
        definition=str(row["definition"]) if row and row["definition"] else None
        output["interval_constraints"][table]={
            "seven_intervals_supported":bool(definition and all(
                str(n) in definition for n in REQUIRED_INTERVALS)),
            "present":bool(definition)}
    if output["tables"]["stream_bar_ledger"]["exists"]:
        cur.execute(
            "SELECT interval_minutes,count(*) AS n,max(bar_start) AS latest "
            "FROM aegis.stream_bar_ledger WHERE symbol='BTC' "
            "AND bar_start>=now()-interval '1 hour' GROUP BY interval_minutes "
            "ORDER BY interval_minutes")
        output["recent_bar_ledger"]=list(cur.fetchall())
    if output["tables"]["stream_decisions"]["exists"]:
        cur.execute(
            "SELECT interval_minutes,action,count(*) AS n,max(observed_at) AS latest "
            "FROM aegis.stream_decisions WHERE symbol='BTC' "
            "AND observed_at>=now()-interval '1 hour' "
            "GROUP BY interval_minutes,action ORDER BY interval_minutes,action")
        output["recent_decisions"]=list(cur.fetchall())
    account=output["tables"]["stream_accounts"]
    if account["exists"] and "direction" not in account["missing_columns"]:
        cur.execute("SELECT count(*) AS n FROM aegis.stream_accounts "
                    "WHERE symbol='BTC' AND direction='SHORT'")
        output["short_account_count"]=int(cur.fetchone()["n"])
    return _json_safe(output)


def get_stream_storage_probe()->dict:
    with _connect() as conn, conn.cursor() as cur:
        return inspect(cur)
