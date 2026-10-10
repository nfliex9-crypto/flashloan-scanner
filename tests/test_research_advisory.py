"""External AI reviewers must remain read-only, opt-in and untrusted."""
from __future__ import annotations

import io
import json
from unittest.mock import Mock

import pytest

from aegis import research_advisory as advisor
from api.stage3 import handler


def valid_diagnostic():
    return {
        "ok":True,"checked_at":"2026-10-10T07:00:00+00:00",
        "database":{"state":"CONNECTED"},
        "market_monitor":{"state":"STALE"},
        "hourly_forward":{"state":"NO_EVIDENCE"},
        "mt5_demo":{"state":"NO_EVIDENCE"},
        "kraken_paper":{"state":"PARTIAL_VERIFIED",
                        "healthy_intervals_minutes":[1,5,15]},
        "broker_password":"DO-NOT-SEND-THIS",
        "account_id":"PRIVATE123",
    }


def test_provider_readiness_does_not_spend_tokens_or_disclose_secrets(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY","password-not-for-dashboard")
    state=advisor.provider_status()
    assert state["grok"]["state"]=="OWNER_ENABLED"
    assert state["grok"]["automatic_calls"] is False
    assert state["jev"]["state"]=="SEPARATE_RAILWAY_SERVICE"
    assert state["fincept"]["code_vendored"] is False
    assert state["execution_authorized"] is False
    assert "password-not-for-dashboard" not in str(state)


def test_cannot_spend_on_missing_kraken_receipts():
    data=valid_diagnostic()
    data["kraken_paper"]["healthy_intervals_minutes"]=[]
    with pytest.raises(advisor.AdvisoryUnavailable,match="no_fresh_kraken_data"):
        advisor.sanitized_receipts(data)


def test_neon_not_connected_is_hard_gate():
    data=valid_diagnostic()
    data["database"]={"state":"UNAVAILABLE"}
    with pytest.raises(advisor.AdvisoryUnavailable,match="neon_source_not_verified"):
        advisor.sanitized_receipts(data)


def test_sanitization_never_sends_account_ids_or_broker_secrets():
    clean=advisor.sanitized_receipts(valid_diagnostic())
    assert clean["kraken_healthy_intervals_minutes"]==[1,5,15]
    assert clean["hourly_forward"]=="NO_EVIDENCE"
    assert clean["broker_execution_enabled"] is False
    assert "DO-NOT-SEND" not in str(clean)
    assert "PRIVATE123" not in str(clean)


def test_bounded_xai_provider_request_is_read_only(monkeypatch):
    captured=[]
    class FakeResponse:
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def read(self,n):
            return json.dumps({"status":"completed",
                "output":[{"type":"message","content":[
                    {"type":"output_text","text":"لا توجد بيانات Paper كافية"}]}]}).encode()
    def fake_open(req, timeout):
        captured.append(req)
        assert req.full_url=="https://api.x.ai/v1/responses"
        assert req.get_method()=="POST"
        assert timeout<=14
        return FakeResponse()
    monkeypatch.setattr(advisor.urllib.request,"urlopen",fake_open)
    result=advisor.request_grok_critique(valid_diagnostic(),key="x"*30,model="grok-4.3")
    assert result["ok"] is True
    assert result["text"]=="لا توجد بيانات Paper كافية"
    assert result["live_execution_enabled"] is False
    assert result["demo_order_execution_enabled"] is False
    body=json.loads(captured[0].data)
    assert body["store"] is False
    assert body["tools"]==[]
    assert body["tool_choice"]=="none"
    assert body["max_output_tokens"]<=256
    assert body["model"]=="grok-4.3"
    assert "DO-NOT-SEND-THIS" not in body["input"]
    assert "PRIVATE123" not in body["input"]
    assert "x"*30 not in body["input"]


def test_unallowlisted_model_is_refused_without_http(monkeypatch):
    monkeypatch.setattr(advisor.urllib.request,"urlopen",
                        lambda *_args,**_kwargs: (_ for _ in ()).throw(
                            AssertionError("Network must never be touched")))
    with pytest.raises(advisor.AdvisoryUnavailable,match="grok_model_not_allowed"):
        advisor.request_grok_critique(valid_diagnostic(),
                                     key="x"*30,model="attacker/untrusted")


def test_invalid_grok_output_rejected():
    with pytest.raises(advisor.AdvisoryUnavailable,match="incomplete_grok_reply"):
        advisor.parse_review_reply({"status":"in_progress","output":[]})
    with pytest.raises(advisor.AdvisoryUnavailable,match="empty_grok_reply"):
        advisor.parse_review_reply({"status":"completed","output":[]})


def test_no_external_api_calls_without_xai_key(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY",raising=False)
    monkeypatch.setattr(advisor.urllib.request,"urlopen",
                        lambda *_args,**_kwargs: (_ for _ in ()).throw(
                            AssertionError("Paid HTTP call forbidden")))
    code, result=advisor.owner_review()
    assert code==503
    assert result["error"]=="grok_not_configured"


class DummyRequest:
    def __init__(self,path,headers=None,raw=b""):
        self.path=path
        self.headers=headers or {}
        self.rfile=io.BytesIO(raw)
        self.result=None

    def _reply(self, status, payload, cache="no-store"):
        self.result=status,payload


def test_research_readiness_is_public_and_cost_free(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY",raising=False)
    request=DummyRequest("/api/stage3?research_advisors=1")
    handler.do_GET(request)
    assert request.result[0]==200
    assert request.result[1]["grok"]["state"]=="NOT_CONFIGURED"


def test_invalid_expensive_operation_blocked_before_payment(monkeypatch):
    monkeypatch.delenv("AEGIS_CONTROL_TOKEN",raising=False)
    request=DummyRequest("/api/stage3?grok_review=1",
        headers={"Content-Length":"20","Authorization":"Bearer fake"},
        raw=b'{"action":"review"}')
    handler.do_POST(request)
    assert request.result[0]==503
    assert request.result[1]["error"]=="owner_control_key_not_configured"


def test_no_confused_deputy_crossover_between_research_and_broker(monkeypatch):
    request=DummyRequest("/api/stage3?grok_review=1&mt5_cloud=1")
    handler.do_POST(request)
    assert request.result[0]==400
    assert request.result[1]["error"]=="invalid_grok_review_query"
