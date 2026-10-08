from datetime import datetime,timezone,timedelta
from aegis.oanda_gold import parse_gold_price,fetch_practice_gold_price

def test_practice_gold_mid_and_spread():
    now=datetime(2026,10,8,13,tzinfo=timezone.utc)
    data={"prices":[{"instrument":"XAU_USD","time":now.isoformat(),
          "status":"tradeable","bids":[{"price":"4200.10"}],"asks":[{"price":"4200.40"}]}]}
    q=parse_gold_price(data,now)
    assert q["price"]==4200.25
    assert q["spread"]==.3
    assert q["fresh"] and q["execution_enabled"] is False

def test_gold_closed_market_not_fresh():
    now=datetime(2026,10,8,13,tzinfo=timezone.utc)
    data={"prices":[{"instrument":"XAU_USD","time":(now-timedelta(hours=2)).isoformat(),
          "status":"non-tradeable","bids":[{"price":"4200.10"}],"asks":[{"price":"4200.40"}]}]}
    assert parse_gold_price(data,now)["fresh"] is False

def test_missing_credentials_doesnt_claim_connection(monkeypatch):
    monkeypatch.delenv("OANDA_API_TOKEN",raising=False)
    monkeypatch.delenv("OANDA_ACCOUNT_ID",raising=False)
    q=fetch_practice_gold_price()
    assert q["connected"] is False
    assert q["execution_enabled"] is False

def test_live_broker_mode_get_only(monkeypatch):
    import json
    import aegis.oanda_gold as gold
    monkeypatch.setenv("OANDA_ENVIRONMENT","live")
    monkeypatch.setenv("OANDA_API_TOKEN","example")
    monkeypatch.setenv("OANDA_ACCOUNT_ID","demo")
    request_info={}
    class Stub:
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def read(self):
            return json.dumps({"prices":[{"instrument":"XAU_USD",
                "time":datetime.now(timezone.utc).isoformat(),
                "status":"tradeable","bids":[{"price":"4000.0"}],
                "asks":[{"price":"4000.5"}]}]}).encode()
    def fake_open(req,timeout):
        request_info["url"]=req.full_url
        request_info["method"]=req.get_method()
        return Stub()
    monkeypatch.setattr(gold.urllib.request,"urlopen",fake_open)
    result=gold.fetch_practice_gold_price()
    assert result["connected"] is True
    assert request_info["url"].startswith(gold.LIVE_URL)
    assert request_info["method"]=="GET"
    assert result["execution_enabled"] is False

def test_unknown_environment_stops_before_network(monkeypatch):
    monkeypatch.setenv("OANDA_ENVIRONMENT","invalid")
    assert fetch_practice_gold_price()["status"]=="INVALID_OANDA_ENVIRONMENT"
