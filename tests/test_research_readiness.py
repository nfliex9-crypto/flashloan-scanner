"""Research controls must disclose readiness without leaking secrets or placing orders."""
from api.stage3 import handler


class FakeReadinessRequest:
    def __init__(self, path):
        self.path=path
        self.result=None

    def _reply(self, status, payload, cache="no-store"):
        self.result=(status, payload)


def test_controls_are_locked_when_no_owner_key(monkeypatch):
    monkeypatch.delenv("AEGIS_CONTROL_TOKEN", raising=False)
    request=FakeReadinessRequest("/api/stage3?capabilities=1")
    handler.do_GET(request)
    status, data=request.result
    assert status==200
    assert data["ok"] is True
    assert data["owner_controls_configured"] is False
    assert data["demo_order_execution_enabled"] is False
    assert data["live_execution_enabled"] is False
    assert "token" not in str(data).lower()


def test_controls_readiness_never_returns_owner_secret(monkeypatch):
    secret="private-example-token-do-not-use-in-production"
    monkeypatch.setenv("AEGIS_CONTROL_TOKEN", secret)
    request=FakeReadinessRequest("/api/stage3?capabilities=1")
    handler.do_GET(request)
    status, data=request.result
    assert status==200
    assert data["owner_controls_configured"] is True
    assert secret not in str(data)
    assert data["demo_order_execution_enabled"] is False


def test_invalid_readiness_request_fails_closed(monkeypatch):
    monkeypatch.setenv("AEGIS_CONTROL_TOKEN", "some-long-configured-owner-key")
    for path in (
        "/api/stage3?capabilities=0",
        "/api/stage3?capabilities=1&capabilities=1",
        "/api/stage3?capabilities=1&backtest=compare",
    ):
        request=FakeReadinessRequest(path)
        handler.do_GET(request)
        assert request.result[0]==400
        assert request.result[1]["ok"] is False
