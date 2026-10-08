"""Persist only fresh FINRA research snapshots, with event time separate from ingestion."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, time, timezone

from .forward_broker import _connect
from .intelligence import WATCHLIST, finra_snapshot


def build_snapshot(symbol: str, data: dict, ingested_at: datetime) -> dict | None:
    if not data.get("ok") or not data.get("context_eligible"):
        return None
    latest = data.get("latest") or {}
    stamp = str(latest.get("date") or "")
    if not stamp:
        return None
    try:
        event_date = datetime.combine(datetime.fromisoformat(stamp).date(), time.min, tzinfo=timezone.utc)
    except ValueError:
        return None
    return {
        "key":f"FINRA_REGSHO:{symbol}:{stamp}",
        "symbol":symbol,
        "source":"FINRA_REGSHO",
        "source_event_ts":event_date,
        "ingested_at":ingested_at,
        "score":float(data.get("anomaly_score") or 0.0),
        "raw":data,
    }


def collect_intelligence(symbols: tuple[str,...] = WATCHLIST, fetcher=finra_snapshot) -> dict:
    now=datetime.now(timezone.utc)
    results=[]
    for symbol in symbols:
        try:
            snapshot=build_snapshot(symbol,fetcher(symbol),now)
            results.append((symbol,snapshot,None))
        except Exception as exc:
            results.append((symbol,None,str(exc)[:180]))

    inserted=0
    with _connect() as conn, conn.cursor() as cur:
        for symbol,snapshot,error in results:
            if snapshot is None:
                continue
            cur.execute(
                "INSERT INTO aegis.intelligence_snapshots "
                "(snapshot_key,symbol,source,source_event_ts,disclosed_at,ingested_at,is_fresh,attention_score,raw) "
                "VALUES (%s,%s,%s,%s,NULL,%s,TRUE,%s,%s::jsonb) "
                "ON CONFLICT(snapshot_key) DO NOTHING RETURNING snapshot_key",
                (snapshot["key"],symbol,snapshot["source"],snapshot["source_event_ts"],
                 snapshot["ingested_at"],snapshot["score"],json.dumps(snapshot["raw"])),
            )
            if not cur.fetchone():
                continue
            inserted+=1
            cur.execute(
                "INSERT INTO aegis.live_events "
                "(event_key,created_at,event_type,scope,symbol,severity,title,description,payload) "
                "VALUES (%s,%s,'INTEL_SNAPSHOT','INTELLIGENCE',%s,'info',%s,%s,%s::jsonb) "
                "ON CONFLICT(event_key) DO NOTHING",
                (f"intel:{snapshot['key']}",now,symbol,f"{symbol} FINRA snapshot persisted",
                 "Public short-sale volume context · no trading signal",
                 json.dumps({"source_event_date":snapshot["source_event_ts"].date().isoformat(),
                             "attention_score":snapshot["score"]})),
            )
        conn.commit()
    return {
        "ok":True,"mode":"PERSISTED_INTEL_CONTEXT","inserted":inserted,
        "symbols_checked":len(results),"errors":{s:e for s,_,e in results if e},
        "not_available_or_stale":[s for s,x,_ in results if not x],
        "live_execution":False,
        "ingested_at":now.isoformat(),
    }
