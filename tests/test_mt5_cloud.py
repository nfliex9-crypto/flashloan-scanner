"""MetaApi cloud MT5 Demo read-only safety and normalization tests.

These use mocked provider data. They never transmit an order or contact a
real broker, and cannot be mistaken for a successful account connection.
"""
import pytest

from aegis import mt5_cloud

INFO = {
    "type": "ACCOUNT_TRADE_MODE_DEMO", "login": 12345678,
    "server": "Broker-Demo", "currency": "USD", "balance": 10000,
    "equity": 10020, "tradeAllowed": False, "investorMode": True,
}
CONFIG = {"token": "not-a-real-metaapi-token", "account": "01234567-89ab-cdef-0123-456789abcdef",
          "region": "london", "symbol": "XAUUSD"}


def test_missing_cloud_config_fails_closed(monkeypatch):
    monkeypatch.delenv("AEGIS_METAAPI_TOKEN", raising=False)
    monkeypatch.delenv("AEGIS_METAAPI_ACCOUNT_ID", raising=False)
    result = mt5_cloud.public_status()
    assert result["state"] == "SETUP_REQUIRED"
    assert result["connected"] is False
    assert result["demo_order_execution_enabled"] is False


def test_rejects_invalid_regions_and_ids(monkeypatch):
    monkeypatch.setenv("AEGIS_METAAPI_TOKEN", "confidential-token")
    monkeypatch.setenv("AEGIS_METAAPI_ACCOUNT_ID", CONFIG["account"])
    monkeypatch.setenv("AEGIS_METAAPI_REGION", "evil.com")
    with pytest.raises(mt5_cloud.CloudUnavailable):
        mt5_cloud.configuration()
    monkeypatch.setenv("AEGIS_METAAPI_REGION", "london")
    monkeypatch.setenv("AEGIS_METAAPI_ACCOUNT_ID", "https://evil.example")
    with pytest.raises(mt5_cloud.CloudUnavailable):
        mt5_cloud.configuration()


def test_prohibits_metaapi_order_routes_even_with_read_credentials():
    cfg = dict(CONFIG)
    for route in ("/trade", "/orders", "/deploy", "https://evil.example", "/history-deals/time/invalid"):
        with pytest.raises(ValueError):
            mt5_cloud.metaapi_get(cfg, route)


def test_allows_bounded_history_path_only(monkeypatch):
    endpoints=[]
    class MockResponse:
        def __enter__(self):return self
        def __exit__(self, *_):return False
        def read(self, size):return b"[]"
    def mock_open(req, timeout):
        assert req.get_method()=="GET"
        assert req.full_url.startswith("https://mt-client-api-v1.london.agiliumtrade.ai/")
        assert "/trade" not in req.full_url
        endpoints.append(req.full_url)
        return MockResponse()
    monkeypatch.setattr(mt5_cloud.urllib.request, "urlopen", mock_open)
    result=mt5_cloud.metaapi_get(CONFIG,
        "/history-deals/time/2026-10-01T01:00:00.000Z/2026-10-02T01:00:00.000Z?limit=200")
    assert result==[]
    assert len(endpoints)==1


def test_real_account_is_rejected_before_history_access(monkeypatch):
    calls=[]
    def stub(cfg, route):
        calls.append(route)
        return {**INFO, "type":"ACCOUNT_TRADE_MODE_REAL"}
    monkeypatch.setattr(mt5_cloud,"metaapi_get",stub)
    with pytest.raises(mt5_cloud.CloudUnavailable,match="not_verified_demo_account"):
        mt5_cloud.snapshot_from_metaapi(CONFIG)
    assert calls==["/account-information"]


def test_broker_demo_snapshot_is_source_backed(monkeypatch):
    def stub(cfg, route):
        if route=="/account-information":return dict(INFO)
        if route=="/symbols":return ["XAUUSD","EURUSD"]
        if route=="/positions":
            return [{"id":"p1","symbol":"XAUUSD","type":"POSITION_TYPE_BUY",
                     "volume":0.05,"openPrice":2400.0,"currentPrice":2401.0,
                     "profit":4.5}]
        if route.startswith("/history-deals/"):
            return [{"id":"deal-1","orderId":"ord-1","symbol":"XAUUSD",
                     "type":"DEAL_TYPE_SELL","entryType":"DEAL_ENTRY_OUT",
                     "price":2400.25,"volume":0.1,"profit":2.0,
                     "commission":-0.2,"swap":-0.01,
                     "time":"2026-10-09T10:00:00.000Z"},
                    {"id":"not-gold","symbol":"EURUSD","type":"DEAL_TYPE_BUY"}]
        raise AssertionError("Unallowlisted route")
    monkeypatch.setattr(mt5_cloud,"metaapi_get",stub)
    result=mt5_cloud.snapshot_from_metaapi(CONFIG)
    assert result["provider"]=="MT5_DEMO"
    assert result["live_execution_enabled"] is False
    assert result["account_ref"].startswith("mt5-demo-")
    assert result["fills"][0]["external_id"]=="deal-1"
    assert result["fills"][0]["side"]=="SELL"
    assert result["fills"][0]["net_pnl"]==pytest.approx(1.79)
    assert len(result["fills"])==1
    assert len(result["open_positions"])==1
    assert "login" not in result
    assert "password" not in result
    assert CONFIG["token"] not in str(result)


def test_public_status_never_spends_metaapi_credits_or_leaks_credentials(monkeypatch):
    monkeypatch.setattr(mt5_cloud, "configuration", lambda: dict(CONFIG))
    def unexpected(*args, **kwargs):
        raise AssertionError("Public GET must not query a billable MetaApi endpoint")
    monkeypatch.setattr(mt5_cloud, "metaapi_get", unexpected)
    report=mt5_cloud.public_status()
    assert report["connected"] is False
    assert report["state"]=="READY_FOR_VERIFICATION"
    assert report["demo_order_execution_enabled"] is False
    assert CONFIG["account"] not in str(report)
    assert CONFIG["token"] not in str(report)


def test_sync_requires_owner_secret_not_metaapi_token(monkeypatch):
    monkeypatch.delenv("AEGIS_CONTROL_TOKEN", raising=False)
    result=mt5_cloud.sync_readonly({"Authorization":"Bearer "+CONFIG["token"]})
    assert result[0]==503
    assert result[1]["error"]=="owner_control_key_not_configured"


def test_sync_persists_only_validated_demo_records(monkeypatch):
    monkeypatch.setenv("AEGIS_CONTROL_TOKEN","owner-key-which-is-longer-than-twentyfour-characters")
    monkeypatch.setattr(mt5_cloud,"configuration",lambda:dict(CONFIG))
    monkeypatch.setattr(mt5_cloud,"snapshot_from_metaapi",
                        lambda _:{"provider":"MT5_DEMO","account_ref":"mt5-demo-abcdef",
                           "market":"XAUUSD","account_type":"DEMO","fills":[],
                           "open_positions":[],"live_execution_enabled":False})
    class Conn:
        def __enter__(self):return self
        def __exit__(self,*args):return False
    monkeypatch.setattr(mt5_cloud,"_connect",lambda:Conn())
    saved=[]
    monkeypatch.setattr(mt5_cloud,"store_demo_snapshot",
                        lambda conn,snap:saved.append(snap) or {"new_fills":0,"open_positions":0})
    status,data=mt5_cloud.sync_readonly({
        "Authorization":"Bearer owner-key-which-is-longer-than-twentyfour-characters",
        "Origin":"https://aegis.example","Host":"aegis.example",
        "Sec-Fetch-Site":"same-origin"})
    assert status==200 and data["demo_order_execution_enabled"] is False
    assert len(saved)==1 and saved[0]["provider"]=="MT5_DEMO"

def test_master_demo_account_is_not_investor_only(monkeypatch):
    invoked=[]
    def get(_cfg,route):
        invoked.append(route)
        return {**INFO,"investorMode":False}
    monkeypatch.setattr(mt5_cloud,"metaapi_get",get)
    with pytest.raises(mt5_cloud.CloudUnavailable,match="investor_mode_not_verified"):
        mt5_cloud.snapshot_from_metaapi(CONFIG)
    assert invoked==["/account-information"]


def test_missing_investor_mode_fails_closed(monkeypatch):
    info=dict(INFO)
    info.pop("investorMode")
    monkeypatch.setattr(mt5_cloud,"metaapi_get",lambda *args:info)
    with pytest.raises(mt5_cloud.CloudUnavailable,match="investor_mode_not_verified"):
        mt5_cloud.verified_demo_info(CONFIG)

def test_truncated_history_is_rejected_not_presented_as_complete(monkeypatch):
    def stub(_config, route):
        if route=="/account-information":return dict(INFO)
        if route=="/symbols":return ["XAUUSD"]
        if route=="/positions":return []
        if route.startswith("/history-deals/"):return [
            {"symbol":"EURUSD","type":"DEAL_TYPE_BUY"} for _ in range(200)]
        raise AssertionError("Unexpected route")
    monkeypatch.setattr(mt5_cloud,"metaapi_get",stub)
    with pytest.raises(mt5_cloud.CloudUnavailable,match="history_page_limit_reached"):
        mt5_cloud.snapshot_from_metaapi(CONFIG)


def test_unknown_position_direction_is_rejected(monkeypatch):
    def stub(_config,route):
        if route=="/account-information":return dict(INFO)
        if route=="/symbols":return ["XAUUSD"]
        if route=="/positions":return [{
            "symbol":"XAUUSD","type":"POSITION_TYPE_UNKNOWN","volume":1,
            "openPrice":2500,"id":"x"}]
        if route.startswith("/history-deals/"):return []
        raise AssertionError("Unexpected route")
    monkeypatch.setattr(mt5_cloud,"metaapi_get",stub)
    with pytest.raises(mt5_cloud.CloudUnavailable,match="invalid_metaapi_position"):
        mt5_cloud.snapshot_from_metaapi(CONFIG)
