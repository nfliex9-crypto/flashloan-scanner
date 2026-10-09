"""Security regressions for website-paired MT5 DEMO read-only connector."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from api import mt5_link

SAMPLE = {
    "provider": "MT5_DEMO", "account_ref": "mt5-demo-" + "a" * 20,
    "market": "XAUUSD", "account_type": "DEMO", "currency": "USD",
    "balance": 10000.0, "equity": 10001.0,
    "fills": [], "open_positions": [], "open_orders": [],
    "live_execution_enabled": False,
}


@pytest.mark.parametrize("changes", [
    {"provider": "BINANCE_SPOT_DEMO"},
    {"account_type": "REAL"},
    {"live_execution_enabled": True},
    {"account_ref": "123456789"},
    {"market": "BTCUSDT"},
    {"balance": float("nan")},
    {"equity": -5},
    {"password": "never-accept-password"},
    {"fills": [{"symbol": "XAUUSD", "side": "BUY", "qty": float("nan"),
                "price": 2350, "executed_at": datetime.now(timezone.utc).isoformat()}]},
    {"fills": [{}] * 201},
])
def test_rejects_invalid_or_non_demo_snapshot(changes):
    with pytest.raises(ValueError):
        mt5_link.validate_mt5_payload({**SAMPLE, **changes})


def test_demo_payload_is_accepted_but_cannot_enable_trading():
    value = mt5_link.validate_mt5_payload({**SAMPLE})
    assert value["live_execution_enabled"] is False
    assert value["provider"] == "MT5_DEMO"
    assert "order_send" not in mt5_link.__file__


def test_pairing_code_is_long_hashed_and_strict():
    token = "Q" * 43
    assert mt5_link.token_digest(token) == hashlib.sha256(token.encode()).hexdigest()
    assert token not in mt5_link.token_digest(token)
    for invalid in ("1234", "../" * 12, "", " " * 43):
        with pytest.raises(ValueError):
            mt5_link.token_digest(invalid)


def test_owner_pairing_locked_without_configured_key(monkeypatch):
    monkeypatch.delenv("AEGIS_CONTROL_TOKEN", raising=False)
    status, report = mt5_link.owner_action("create", {
        "Authorization": "Bearer " + "x" * 40,
        "Origin": "https://site.example",
        "Host": "site.example",
        "Sec-Fetch-Site": "same-origin",
    })
    assert status == 503
    assert report["error"] == "owner_control_key_not_configured"


def test_owner_pairing_rejects_cross_origin(monkeypatch):
    token = "owner-password-not-a-broker-password" * 2
    monkeypatch.setenv("AEGIS_CONTROL_TOKEN", token)
    status, report = mt5_link.owner_action("create", {
        "Authorization": "Bearer " + token,
        "Origin": "https://evil.example",
        "Host": "good.example",
        "Sec-Fetch-Site": "cross-site",
    })
    assert status == 403
    assert report["ok"] is False


def test_schema_unavailable_displays_setup_required():
    cur = Mock()
    cur.fetchone.return_value = {"pairing": False, "accounts": True, "fills": True}
    response = mt5_link.status_report(cur)
    assert response["state"] == "SETUP_REQUIRED"
    assert response["connected"] is False
    assert response["demo_order_execution_enabled"] is False


def test_bogus_connector_token_never_touches_database(monkeypatch):
    def fail_connect():
        raise AssertionError("No DB call expected for invalid credential")
    monkeypatch.setattr(mt5_link, "_connect", fail_connect)
    status, result = mt5_link.ingest_snapshot("Bearer too-short", SAMPLE)
    assert status == 422
    assert result["ok"] is False
    status, result = mt5_link.ingest_snapshot("", SAMPLE)
    assert status == 401


class DummyCursor:
    def __init__(self, record):
        self.record = record
        self.sql = []
        self.args = []
        self.last = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, params=None):
        self.sql.append(query)
        self.args.append(params)
        self.last = query

    def fetchone(self):
        if "to_regclass" in self.last:
            return {"pairing": True, "accounts": True, "fills": True}
        if "FOR UPDATE" in self.last:
            return self.record
        return None


class DummyConn:
    def __init__(self, record):
        self.cur = DummyCursor(record)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return self.cur


def test_claim_binds_demo_fingerprint_and_never_calls_broker(monkeypatch):
    conn = DummyConn({
        "pairing_id": 5,
        "state": "PENDING",
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
        "source_id": None,
    })
    monkeypatch.setattr(mt5_link, "_connect", lambda: conn)
    write = Mock(return_value={"new_fills": 0})
    monkeypatch.setattr(mt5_link, "store_demo_snapshot", write)
    status, result = mt5_link.ingest_snapshot("Bearer " + "Q" * 43, SAMPLE)
    assert status == 200
    assert result["state"] == "CONNECTED_DEMO"
    assert result["demo_order_execution_enabled"] is False
    write.assert_called_once_with(conn, SAMPLE)
    assert any("state='ACTIVE'" in x for x in conn.cur.sql)


def test_cannot_switch_connected_demo_account(monkeypatch):
    conn = DummyConn({
        "pairing_id": 5,
        "state": "ACTIVE",
        "expires_at": datetime.now(timezone.utc) - timedelta(days=2),
        "source_id": "mt5-demo-" + "b" * 20,
    })
    monkeypatch.setattr(mt5_link, "_connect", lambda: conn)
    forbidden_write = Mock()
    monkeypatch.setattr(mt5_link, "store_demo_snapshot", forbidden_write)
    status, result = mt5_link.ingest_snapshot("Bearer " + "Q" * 43, SAMPLE)
    assert status == 403
    forbidden_write.assert_not_called()


def test_expired_pairing_cannot_sync(monkeypatch):
    conn = DummyConn({
        "pairing_id": 5, "state": "PENDING",
        "expires_at": datetime.now(timezone.utc) - timedelta(seconds=1),
        "source_id": None,
    })
    monkeypatch.setattr(mt5_link, "_connect", lambda: conn)
    forbidden_write = Mock()
    monkeypatch.setattr(mt5_link, "store_demo_snapshot", forbidden_write)
    status, result = mt5_link.ingest_snapshot("Bearer " + "Q" * 43, SAMPLE)
    assert status == 410
    forbidden_write.assert_not_called()
