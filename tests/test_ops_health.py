"""Run source-backed canary tests without a Neon account or network calls."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aegis import ops_health
from api.stage3 import handler


NOW = datetime(2026, 10, 10, 7, 0, tzinfo=timezone.utc)


class FakeCursor:
    def __init__(self, *, tables=None, recent=(), monitor_age=1, forward_age=1, demo_age=None):
        self.tables = set(tables if tables is not None else
                          ops_health.CORE_PAPER_TABLES+
                          ops_health.STREAM_TABLES+ops_health.DEMO_TABLES)
        self.recent=set(recent)
        self.monitor_age=monitor_age
        self.forward_age=forward_age
        self.demo_age=demo_age
        self.sql=[]
        self.last=None
        self.params=None

    def execute(self, statement, params=None):
        assert not any(k in statement.upper() for k in ("INSERT INTO", "UPDATE ", "DELETE FROM", "DROP ", "ALTER ", "CREATE "))
        self.sql.append(statement)
        self.last=statement
        self.params=params

    def fetchone(self):
        if "to_regclass" in self.last:
            return {"present":self.params[0].removeprefix("aegis.") in self.tables}
        if "max(completed_at)" in self.last:
            age=self.monitor_age if self.params[0]=="MARKET_MONITOR" else self.forward_age
            return {"ts":NOW-timedelta(minutes=age) if age is not None else None}
        if "max(last_synced)" in self.last:
            return {"ts":NOW-timedelta(minutes=self.demo_age) if self.demo_age is not None else None}
        raise AssertionError("Unexpected SELECT: "+self.last)

    def fetchall(self):
        if "FROM aegis.stream_status" in self.last:
            return [
                {"stream_name":f"kraken-public-micro-{m}m",
                 "state":"CONNECTED","updated_at":NOW-timedelta(seconds=40)}
                for m in self.recent]
        raise AssertionError("Unexpected SELECT: "+self.last)


def test_complete_operational_evidence_is_source_backed_and_read_only():
    cur=FakeCursor(recent=ops_health.TIMEFRAMES, demo_age=1)
    report=ops_health.inspect_persisted(cur,now=NOW)
    assert report["market_monitor"]["state"]=="CURRENT"
    assert report["hourly_forward"]["state"]=="CURRENT"
    assert report["kraken_paper"]["state"]=="ALL_VERIFIED"
    assert report["mt5_demo"]["state"]=="CURRENT"
    assert report["database"]["read_only"] is True
    assert report["live_execution_enabled"] is False
    assert report["demo_order_execution_enabled"] is False
    assert len(cur.sql)>10


def test_three_active_kraken_streams_are_partial_not_failed_or_seven():
    report=ops_health.inspect_persisted(FakeCursor(recent=(1,5,15)),now=NOW)
    assert report["kraken_paper"]["state"]=="PARTIAL_VERIFIED"
    assert report["kraken_paper"]["healthy_intervals_minutes"]==[1,5,15]
    assert report["kraken_paper"]["missing_intervals_minutes"]==[60,240,1440,10080]


def test_no_forward_run_never_claims_active_trading():
    report=ops_health.inspect_persisted(FakeCursor(forward_age=None,monitor_age=240),now=NOW)
    assert report["market_monitor"]["state"]=="STALE"
    assert report["hourly_forward"]["state"]=="NO_EVIDENCE"


def test_missing_stream_schema_is_detected_without_writing_migrations():
    existing=set(ops_health.CORE_PAPER_TABLES+ops_health.DEMO_TABLES)
    report=ops_health.inspect_persisted(FakeCursor(tables=existing),now=NOW)
    assert report["kraken_paper"]["state"]=="SCHEMA_MISSING"
    assert report["kraken_paper"]["healthy_intervals_minutes"]==[]
    assert "stream_status" in report["kraken_paper"]["missing_tables"]


def test_gold_demo_is_not_connected_without_real_broker_receipt():
    report=ops_health.inspect_persisted(FakeCursor(demo_age=None),now=NOW)
    assert report["mt5_demo"]["state"]=="NO_EVIDENCE"


def test_clock_and_missing_timestamps_fail_closed():
    assert ops_health.freshness(NOW+timedelta(minutes=1),now=NOW,limit_seconds=20)=="STALE"
    assert ops_health.freshness(None,now=NOW,limit_seconds=20)=="NO_EVIDENCE"
    try:
        ops_health.inspect_persisted(FakeCursor(),now=datetime(2026,10,10))
    except ValueError:
        pass
    else:
        raise AssertionError("Naive timestamp must not be silently accepted")


def test_neon_connect_failure_never_leaks_exception_or_makes_up_records(monkeypatch):
    from aegis import forward_broker
    def unavailable():
        raise RuntimeError("DATABASE_URL=postgres://secret:password@host")
    monkeypatch.setattr(forward_broker,"_connect",unavailable)
    report=ops_health.diagnose()
    assert report["database"]["state"]=="UNAVAILABLE"
    assert report["market_monitor"]["state"]=="UNVERIFIED"
    assert "secret" not in str(report)
    assert report["live_execution_enabled"] is False


class FakeRequest:
    def __init__(self,path):
        self.path=path
        self.result=None

    def _reply(self,status,payload,cache="no-store"):
        self.result=(status,payload)


def test_diagnostics_endpoint_rejects_parameter_smuggling(monkeypatch):
    request=FakeRequest("/api/stage3?diagnostics=1&backtest=compare")
    handler.do_GET(request)
    assert request.result[0]==400
    assert request.result[1]["error"]=="invalid_diagnostics_query"


def test_diagnostics_endpoint_reads_only_verified_canaries(monkeypatch):
    monkeypatch.setattr(ops_health,"diagnose",lambda:{"ok":True,"mode":"SOURCE_BACKED_READ_ONLY_DIAGNOSTICS"})
    request=FakeRequest("/api/stage3?diagnostics=1")
    handler.do_GET(request)
    assert request.result[0]==200
    assert request.result[1]["mode"]=="SOURCE_BACKED_READ_ONLY_DIAGNOSTICS"
