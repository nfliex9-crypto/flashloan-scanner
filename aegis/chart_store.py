"""Bounded latest snapshots, idempotent writes, explicit provenance."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from .chart_reader import normalize, freshness, utcnow, stamp


def connect():
    from .forward_broker import _connect
    return _connect()


def persist(doc, conn=None):
    if conn is None:
        with connect() as owned:
            return persist(doc, owned)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO aegis.chart_snapshots "
                    "(source_id,source,symbol,interval_minutes,snapshot_id,observed_at,payload) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb) "
                    "ON CONFLICT(source_id) DO UPDATE SET snapshot_id=EXCLUDED.snapshot_id, "
                    "observed_at=EXCLUDED.observed_at,received_at=now(),payload=EXCLUDED.payload || "
                    "CASE WHEN EXCLUDED.payload ? 'last_image' THEN '{}'::jsonb ELSE "
                    "jsonb_build_object('last_image',aegis.chart_snapshots.payload->'last_image') END "
                    "WHERE aegis.chart_snapshots.observed_at < EXCLUDED.observed_at "
                    "AND aegis.chart_snapshots.snapshot_id <> EXCLUDED.snapshot_id "
                    "RETURNING snapshot_id",
                    (doc['source_id'], doc['source'], doc['symbol'], doc['interval_minutes'],
                     doc['snapshot_id'], doc['observed_at'], json.dumps(doc, allow_nan=False)))
        row = cur.fetchone()
    return bool(row)


def claim_job(name, seconds):
    with connect() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO aegis.chart_job_limits(job_key) VALUES(%s) "
                    "ON CONFLICT(job_key) DO UPDATE SET last_started_at=now() "
                    "WHERE aegis.chart_job_limits.last_started_at < now() - %s * interval '1 second' "
                    "RETURNING job_key", (name, seconds))
        return cur.fetchone() is not None


def load(source_id):
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT payload FROM aegis.chart_snapshots WHERE source_id=%s", (source_id,))
        row = cur.fetchone()
        if not row:
            raise ValueError("chart_not_received")
        return row['payload']


def status(source_id=None):
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT source_id,source,symbol,interval_minutes,observed_at FROM aegis.chart_snapshots "
                        "ORDER BY source,symbol,interval_minutes LIMIT 24")
            sources=cur.fetchall()
            chosen=source_id if any(s['source_id']==source_id for s in sources) else (sources[0]['source_id'] if sources else '')
            cur.execute("SELECT s.payload, s.received_at, v.report, v.observed_at AS vision_observed_at, "
                        "v.analyzed_at FROM aegis.chart_snapshots s LEFT JOIN aegis.chart_vision_reports v "
                        "ON s.source_id=v.source_id WHERE s.source_id=%s",(chosen,))
            rows = cur.fetchall()
        docs = []
        for row in rows:
            doc = row['payload']
            fresh=freshness(doc)
            doc['bars']=doc['bars'][-80:]
            if doc.get('last_image'):
                doc['last_image']['context']={k:v for k,v in doc['last_image']['context'].items() if k in ('source','symbol','interval_minutes','observed_at','snapshot_id')}
            # Images are returned only for this protected application's chart view.
            docs.append({**doc, "freshness": fresh,
                         "received_at": row['received_at'].isoformat(),
                         "vision": {"state": "ANALYZED" if row['report'] else "NOT_ANALYZED",
                                    "report": row['report'],
                                    "observed_at": row['vision_observed_at'].isoformat() if row['vision_observed_at'] else None,
                                    "analyzed_at": row['analyzed_at'].isoformat() if row['analyzed_at'] else None}})
        return {"ok": True, "mode": "CHART_READER", "snapshots": docs,
                "sources":[{**s,'observed_at':s['observed_at'].isoformat()} for s in sources],
                "bridge_state": "OBSERVATIONS_RECEIVED" if any(d['source']=='TRADINGVIEW_DESKTOP' for d in sources) else "WAITING_FOR_DESKTOP",
                "ingest_configured": len(os.getenv('AEGIS_CHART_TOKEN','')) >= 32,
                "vision_configured": bool(os.getenv('VERCEL_OIDC_TOKEN') or os.getenv('AI_GATEWAY_API_KEY')),
                "vision_model": os.getenv('AEGIS_CHART_VISION_MODEL',''),
                "execution_enabled": False}
    except Exception:
        return {"ok": False, "mode": "CHART_READER", "error": "chart_storage_unavailable", "snapshots": [], "execution_enabled": False}


def authorize(raw, headers, *, key=None, now=None):
    key = key if key is not None else os.getenv('AEGIS_CHART_TOKEN','')
    if len(key) < 32:
        raise PermissionError("chart_ingest_not_configured")
    ts = headers.get('X-Aegis-Timestamp','')
    try:
        age = (now or utcnow()).timestamp() - int(ts)
    except (ValueError, TypeError):
        raise PermissionError("invalid_chart_signature") from None
    if not -5 <= age <= 60:
        raise PermissionError("expired_chart_signature")
    signature = hmac.new(key.encode(), ts.encode()+b'.'+raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, headers.get('X-Aegis-Signature','')):
        raise PermissionError("invalid_chart_signature")


def refresh_gold():
    """Honest REST fallback, globally limited to one request/minute (not ticks)."""
    key = os.getenv('TWELVEDATA_API_KEY')
    if not key:
        return {"state": "GOLD_KEY_MISSING"}
    if not claim_job('gold-rest-5m', 60):
        return {"state": "CACHED"}
    query = urllib.parse.urlencode({"symbol":"XAU/USD", "interval":"5min", "outputsize":120,
                                   "timezone":"UTC", "apikey":key})
    try:
        request = urllib.request.Request('https://api.twelvedata.com/time_series?'+query,
                                         headers={"User-Agent":"AEGIS-Chart-Reader/1.0"})
        with urllib.request.urlopen(request, timeout=12) as response:
            raw=response.read(180001)
        if len(raw)>180000:
            raise ValueError('response_too_large')
        data=json.loads(raw)
        if data.get('status')=='error' or data.get('meta',{}).get('symbol') != 'XAU/USD':
            return {"state":"GOLD_FEED_NOT_ENTITLED_OR_UNAVAILABLE"}
        bars=[]
        for b in reversed(data.get('values',[])):
            dt=datetime.fromisoformat(b['datetime']).replace(tzinfo=timezone.utc)
            bars.append({"time":int(dt.timestamp()), **{k:float(b[k]) for k in ('open','high','low','close')},
                         "volume":float(b['volume']) if b.get('volume') else None})
        doc=normalize({"version":1,"source":"TWELVE_DATA_REST","symbol":"TWELVEDATA:XAUUSD",
                       "interval_minutes":5,"observed_at":utcnow().isoformat(),"bars":bars})
        persist(doc)
        return {"state":"OBSERVED_REST", "freshness":freshness(doc)}
    except Exception:
        return {"state":"GOLD_FEED_UNAVAILABLE"}


def ingest(body):
    doc=normalize(body, allowed_source='TRADINGVIEW_DESKTOP')
    written=persist(doc)
    return {"ok":True,"written":written,"snapshot_id":doc['snapshot_id'],
            "source_id":doc['source_id'],"freshness":freshness(doc),"execution_enabled":False}
