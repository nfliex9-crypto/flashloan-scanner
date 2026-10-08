from datetime import datetime,timezone
from aegis.intelligence_ledger import build_snapshot

def test_intel_requires_fresh_and_valid_data():
    now=datetime(2026,10,8,tzinfo=timezone.utc)
    stale={"ok":True,"context_eligible":False,"latest":{"date":"2026-01-01"},"anomaly_score":90}
    assert build_snapshot("QQQ",stale,now) is None
    assert build_snapshot("QQQ",{"ok":False},now) is None

def test_finra_snapshot_timestamp_and_stable_key():
    now=datetime(2026,10,8,tzinfo=timezone.utc)
    data={"ok":True,"context_eligible":True,"latest":{"date":"2026-10-07"},"anomaly_score":34.2}
    a=build_snapshot("SPY",data,now)
    assert a["key"]=="FINRA_REGSHO:SPY:2026-10-07"
    assert a["ingested_at"]>a["source_event_ts"]
    assert a["score"]==34.2
