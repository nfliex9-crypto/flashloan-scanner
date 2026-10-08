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
