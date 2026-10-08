"""Source-authoritative DEMO ledger sync (read-only brokers + compact Neon mirror).

Never executes an order; never stores API secrets, terminal login or market
candles. Repeated collection is idempotent by provider-account execution ID.
Windows MT5 and Linux Binance Demo run as separate connector processes.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone

from .demo_adapters import read_mt5_demo_gold,read_binance_spot_demo,DemoConnectionError


def validate_demo_snapshot(snapshot: dict) -> None:
    if snapshot.get("provider") not in ("MT5_DEMO","BINANCE_SPOT_DEMO"):
        raise ValueError("Unsupported broker connector")
    if snapshot.get("account_type")!="DEMO":
        raise ValueError("A live or unknown account cannot be reconciled")
    if snapshot.get("live_execution_enabled") is not False:
        raise ValueError("Unexpected execution entitlement")
    if not snapshot.get("account_ref") or len(snapshot["account_ref"])>96:
        raise ValueError("Demo account fingerprint missing")
    if not isinstance(snapshot.get("fills"),list) or not isinstance(snapshot.get("open_positions"),list):
        raise ValueError("Incomplete demo broker ledger")


def store_demo_snapshot(conn,snapshot:dict)->dict:
    validate_demo_snapshot(snapshot)
    fills=snapshot["fills"]
    stats={"provider":snapshot["provider"],"observed":len(fills),"new_fills":0,
           "open_positions":len(snapshot["open_positions"]),
           "open_orders":len(snapshot.get("open_orders",[]))}
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO aegis.demo_account_state "
                "(source_id,provider,market,account_type,currency,balance,equity,"
                "open_positions,open_orders,spot_balances,source_of_truth,last_status,last_synced)"
                "VALUES (%s,%s,%s,'DEMO',%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s,'CONNECTED_DEMO',now()) "
                "ON CONFLICT(source_id) DO UPDATE SET "
                "balance=EXCLUDED.balance,equity=EXCLUDED.equity,"
                "open_positions=EXCLUDED.open_positions,open_orders=EXCLUDED.open_orders,"
                "spot_balances=EXCLUDED.spot_balances,last_synced=now(),last_status='CONNECTED_DEMO'",
                (snapshot["account_ref"],snapshot["provider"],snapshot["market"],
                 snapshot.get("currency"),snapshot.get("balance"),snapshot.get("equity"),
                 json.dumps(snapshot["open_positions"]),
                 json.dumps(snapshot.get("open_orders",[])),
                 json.dumps(snapshot.get("spot_balances",{})),
                 snapshot.get("source_of_truth","BROKER_DEMO_HISTORY")))
            for fill in fills:
                if not fill.get("external_id") or fill.get("symbol")!=snapshot["market"]:
                    raise ValueError("Malformed or mismatched broker deal")
                if fill.get("side") not in ("BUY","SELL"):
                    raise ValueError("Invalid broker deal direction")
                if float(fill["price"])<=0 or float(fill["qty"])<=0:
                    raise ValueError("Invalid demo execution volume/price")
                cur.execute(
                    "INSERT INTO aegis.demo_fills "
                    "(source_id,external_id,order_id,position_id,symbol,side,entry_kind,"
                    "price,qty,fee,fee_asset,net_pnl,executed_at,agent_id) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT(source_id,external_id) DO NOTHING RETURNING external_id",
                    (snapshot["account_ref"],fill["external_id"],fill.get("order_id"),
                     fill.get("position_id"),fill["symbol"],fill["side"],fill.get("entry_kind"),
                     fill["price"],fill["qty"],fill.get("fee"),fill.get("fee_asset"),
                     fill.get("net_pnl"),fill["executed_at"],fill.get("agent_id")))
                if cur.fetchone():
                    stats["new_fills"]+=1
    return stats


def collect_once(provider:str, *, database_url:str|None=None,symbol:str="XAUUSD")->dict:
    if provider=="mt5":
        snapshot=read_mt5_demo_gold(symbol=symbol)
    elif provider=="binance":
        snapshot=read_binance_spot_demo()
    else:
        raise ValueError("Demo source must be mt5 or binance")
    validate_demo_snapshot(snapshot)
    db_url=database_url if database_url is not None else os.getenv("AEGIS_DEMO_DATABASE_URL","")
    if not db_url:
        return {"provider":snapshot["provider"],
                "history_items":len(snapshot["fills"]),"positions":len(snapshot["open_positions"]),
                "orders":len(snapshot.get("open_orders",[])),"persisted":False}
    import psycopg
    with psycopg.connect(db_url,connect_timeout=8) as conn:
        result=store_demo_snapshot(conn,snapshot)
    return {**result,"persisted":True}


def main()->None:
    p=argparse.ArgumentParser(description="Read-only broker DEMO trade history reconciliation")
    p.add_argument("--provider",choices=["mt5","binance"],required=True)
    p.add_argument("--symbol",default="XAUUSD",help="Exact gold symbol at your MT5 demo broker")
    p.add_argument("--once",action="store_true")
    p.add_argument("--poll-seconds",type=int,default=60)
    args=p.parse_args()
    if not args.once and not 30<=args.poll_seconds<=3600:
        p.error("Polling interval must be 30 to 3600 seconds")
    while True:
        try:
            report=collect_once(args.provider,symbol=args.symbol)
            print(json.dumps({**report,"checked_at":datetime.now(timezone.utc).isoformat()}),flush=True)
        except (DemoConnectionError,ValueError,ConnectionError,OSError):
            # Never show raw client exceptions: API/DB errors can include
            # signed URLs, account IDs or privileged DB connection strings.
            print(json.dumps({"provider":args.provider,"status":"DEMO_SYNC_UNAVAILABLE",
                              "checked_at":datetime.now(timezone.utc).isoformat()}),flush=True)
        if args.once:
            break
        time.sleep(args.poll_seconds)


if __name__=="__main__":
    main()
