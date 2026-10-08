"""Broker demo safety: no live MT5 sessions or non-demo Binance URLs."""
from collections import namedtuple
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from aegis.demo_adapters import (
    BINANCE_SPOT_DEMO_API, BinanceSpotDemoReader, DemoConnectionError,
    read_mt5_demo_gold,
)
from aegis.demo_sync import validate_demo_snapshot,store_demo_snapshot


class FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO=0
    ACCOUNT_TRADE_MODE_REAL=2
    DEAL_TYPE_BUY=0
    DEAL_TYPE_SELL=1

    def __init__(self, mode=0):
        self.mode=mode
        self.shut=False
    def initialize(self):return True
    def shutdown(self):self.shut=True
    def account_info(self):
        return SimpleNamespace(trade_mode=self.mode,login=129000,
            server="Example Demo",currency="USD",balance=10000,equity=10030)
    def symbol_info(self,symbol):
        return object() if symbol=="XAUUSDm" else None
    def history_deals_get(self,*args,**kwargs):
        Deal=namedtuple("Deal","ticket order position_id symbol type price volume commission profit swap time time_msc entry magic")
        return [Deal(8901,8900,7401,"XAUUSDm",0,4055.1,.1,-.2,4.2,0,1791480000,1791480000000,0,777)]
    def positions_get(self,**kwargs):
        Position=namedtuple("Position","ticket symbol type volume price_open price_current profit sl tp")
        return [Position(7401,"XAUUSDm",0,.1,4055.1,4059.0,39,4040,4080)]


def test_mt5_real_account_cannot_be_read_as_demo_even_if_connected():
    fake=FakeMT5(mode=FakeMT5.ACCOUNT_TRADE_MODE_REAL)
    with pytest.raises(DemoConnectionError,match="non-DEMO"):
        read_mt5_demo_gold(mt5=fake,symbol="XAUUSDm")
    assert fake.shut


def test_mt5_demo_history_comes_from_real_terminal_apis():
    fake=FakeMT5()
    x=read_mt5_demo_gold(mt5=fake,symbol="XAUUSDm",now=datetime(2026,10,8,16,tzinfo=timezone.utc))
    assert x["provider"]=="MT5_DEMO"
    assert x["account_type"]=="DEMO" and x["live_execution_enabled"] is False
    assert x["fills"][0]["external_id"]=="8901"
    assert x["fills"][0]["net_pnl"]==4.0
    assert x["open_positions"][0]["external_id"]=="7401"
    assert fake.shut


def test_mt5_demo_requires_exact_broker_gold_symbol():
    with pytest.raises(DemoConnectionError,match="Gold symbol"):
        read_mt5_demo_gold(mt5=FakeMT5(),symbol="XAUUSD")


def test_binance_is_hardwired_to_demo_domain_and_allowlisted_gets(monkeypatch):
    reader=BinanceSpotDemoReader("test-demo-key","test-demo-secret")
    paths=[]
    def fake_get(path,**params):
        paths.append((path,params))
        if path=="/api/v3/account":
            return {"accountType":"SPOT","uid":123,"balances":[{"asset":"BTC","free":"0.3","locked":"0.0"}]}
        if path=="/api/v3/myTrades":
            return [{"id":71,"orderId":9,"price":"12000","qty":"0.01",
                     "commission":"0.0001","commissionAsset":"BTC",
                     "isBuyer":True,"time":1791480000000}]
        return [{"orderId":9,"symbol":"BTCUSDT","side":"BUY",
                 "type":"LIMIT","origQty":"0.02","executedQty":"0.01",
                 "price":"12000","status":"PARTIALLY_FILLED"}]
    monkeypatch.setattr(reader,"_signed_get",fake_get)
    doc=reader.snapshot()
    assert BINANCE_SPOT_DEMO_API=="https://demo-api.binance.com"
    assert all(path in {"/api/v3/account","/api/v3/myTrades","/api/v3/openOrders"} for path,_ in paths)
    assert doc["provider"]=="BINANCE_SPOT_DEMO"
    assert doc["fills"][0]["external_id"]=="71"
    assert doc["fills"][0]["net_pnl"] is None
    assert doc["spot_balances"]["BTC"]["free"]==.3
    assert doc["live_execution_enabled"] is False


def test_binance_client_refuses_live_order_endpoints():
    client=BinanceSpotDemoReader("fake","fake")
    with pytest.raises(ValueError,match="allowlisted"):
        client._signed_get("/api/v3/order",symbol="BTCUSDT")


def test_binance_rejects_unsupported_instruments():
    client=BinanceSpotDemoReader("fake","fake")
    with pytest.raises(ValueError,match="BTCUSDT"):
        client.snapshot("ETHUSDT")


def test_reconciliation_never_accepts_live_or_unknown_accounts():
    for s in ({"provider":"MT5_DEMO","account_type":"REAL","live_execution_enabled":False},
              {"provider":"BINANCE_SPOT_DEMO","account_type":"DEMO","live_execution_enabled":True},
              {"provider":"UNKNOWN","account_type":"DEMO","live_execution_enabled":False}):
        with pytest.raises(ValueError):
            validate_demo_snapshot(s)


def test_minimal_demo_mirror_deduplicates_broker_trade_ids():
    class Cursor:
        def __init__(self):
            self.calls=[];self.inserted=True
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def execute(self,statement,params):
            self.calls.append((statement,params))
        def fetchone(self):
            return {"external_id":"71"} if self.inserted else None
    class Conn:
        def __init__(self):self.cur=Cursor()
        def transaction(self):return self
        def cursor(self):return self.cur
        def __enter__(self):return self
        def __exit__(self,*args):return False
    doc={"provider":"BINANCE_SPOT_DEMO","account_ref":"example-hash",
         "market":"BTCUSDT","account_type":"DEMO",
         "live_execution_enabled":False,
         "fills":[{"external_id":"71","symbol":"BTCUSDT","side":"BUY",
                   "price":110,"qty":.1,
                   "executed_at":"2026-10-08T15:00:00+00:00"}],
         "open_positions":[],"open_orders":[],"source_of_truth":"DEMO"}
    conn=Conn()
    assert store_demo_snapshot(conn,doc)["new_fills"]==1
    conn.cur.inserted=False
    assert store_demo_snapshot(conn,doc)["new_fills"]==0
    sql=" ".join(s for s,_ in conn.cur.calls)
    assert "ON CONFLICT(source_id,external_id) DO NOTHING" in sql
    assert "order_send" not in sql
