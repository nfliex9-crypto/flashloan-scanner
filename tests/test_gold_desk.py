"""Gold Desk test fixtures are NOT market prices or Pepperstone receipts."""
from datetime import datetime,timedelta,timezone
import json

from aegis import gold_desk
from api.stage3 import handler

NOW=datetime(2026,10,9,9,0,tzinfo=timezone.utc)


def real_shape(updated=None):
    return {"symbol":"XAU","name":"Gold","price":4385.2,"currency":"USD",
            "updatedAt":(updated or NOW-timedelta(seconds=32)).isoformat()}


def test_real_spot_payload_requires_precise_currency_symbol_and_provider_timestamp():
    x=gold_desk.parse_gold_spot(real_shape(),now=NOW)
    assert x["state"]=="CURRENT"
    assert x["price"]==4385.2
    assert x["fresh"] is True
    assert x["unit"]=="USD_PER_TROY_OUNCE"
    assert x["kind"]=="INDICATIVE_SPOT_REFERENCE_NOT_BROKER_EXECUTABLE"
    assert x["pepperstone_bid"] is None and x["pepperstone_ask"] is None
    assert x["trading_permission"] is False


def test_weekend_or_stale_price_is_visibly_distinct_from_live_price():
    x=gold_desk.parse_gold_spot(real_shape(NOW-timedelta(days=2)),now=NOW)
    assert x["state"]=="STALE_SOURCE_QUOTE"
    assert x["fresh"] is False
    assert x["price"] is None
    assert x["last_known_price"]==4385.2


def test_gold_weekend_reference_is_visible_but_never_claimed_tradeable():
    saturday=datetime(2026,10,10,10,57,tzinfo=timezone.utc)
    info=real_shape(saturday-timedelta(seconds=7))
    gold=gold_desk.parse_gold_spot(info,now=saturday)
    assert gold["state"]=="MARKET_CLOSED_WEEKEND"
    assert gold["market_session"]=="WEEKEND_CLOSED"
    assert gold["provider_timestamp_fresh"] is True
    assert gold["fresh"] is False
    assert gold["price"] is None
    assert gold["last_known_price"]==4385.2
    assert gold["trading_permission"] is False


def test_unsupported_currency_and_fake_prices_are_rejected():
    import pytest
    for field,value in [
        ("symbol","XAG"),("currency","EUR"),("price",float("nan")),
        ("price",-100),("price","999999"),("updatedAt","not-a-time"),
        ("updatedAt",(NOW+timedelta(days=1)).isoformat())
    ]:
        bad={**real_shape(),field:value}
        with pytest.raises(ValueError):
            gold_desk.parse_gold_spot(bad,now=NOW)


def test_fixed_provider_is_read_only_and_does_not_need_api_credentials(monkeypatch):
    seen=[]
    class FakeResponse:
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def read(self,limit):return json.dumps(real_shape()).encode()
    def fake_urlopen(req,timeout):
        seen.append((req.full_url,req.get_method(),timeout))
        return FakeResponse()
    monkeypatch.setattr(gold_desk.urllib.request,"urlopen",fake_urlopen)
    report=gold_desk.get_gold_quote(now=NOW)
    assert report["fresh"]
    assert seen==[("https://api.gold-api.com/price/XAU","GET",6)]


def test_provider_outage_cannot_generate_fabricated_quote(monkeypatch):
    from urllib.error import URLError
    def fail(*args,**kwargs):raise URLError("unavailable")
    monkeypatch.setattr(gold_desk.urllib.request,"urlopen",fail)
    report=gold_desk.get_gold_quote(now=NOW)
    assert report["price"] is None
    assert report["fresh"] is False
    assert report["state"]=="SOURCE_UNAVAILABLE"


def test_pepperstone_is_not_linked_by_choosing_a_tradingview_account(monkeypatch):
    monkeypatch.setattr(gold_desk,"get_gold_quote",lambda **_:gold_desk.parse_gold_spot(real_shape(),now=NOW))
    doc=gold_desk.get_gold_desk()
    assert doc["ok"] is True
    assert doc["broker"]["verified"] is False
    assert doc["broker"]["positions"] is None
    assert doc["broker"]["fills"] is None
    assert doc["broker"]["account_balance"] is None
    assert doc["live_order_execution_enabled"] is False
    assert doc["demo_order_execution_enabled"] is False


class FakeRequest:
    def __init__(self,path):self.path=path;self.result=None
    def _reply(self,status,data,cache="no-store"):self.result=(status,data)


def test_gold_api_query_cannot_be_smuggled_into_other_routes(monkeypatch):
    req=FakeRequest("/api/stage3?gold_desk=1&mt5_cloud=1")
    handler.do_GET(req)
    assert req.result[0]==400
    assert req.result[1]["error"]=="invalid_gold_desk_query"


def test_gold_market_api_uses_same_vercel_function(monkeypatch):
    expected={"ok":True,"mode":"SOURCE_BACKED_GOLD_MARKET_INFORMATION"}
    monkeypatch.setattr(gold_desk,"get_gold_desk",lambda:expected)
    req=FakeRequest("/api/stage3?gold_desk=1")
    handler.do_GET(req)
    assert req.result==(200,expected)
