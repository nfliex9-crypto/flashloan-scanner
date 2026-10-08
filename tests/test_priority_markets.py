from datetime import datetime, timezone, timedelta
from aegis.priority_markets import _quote, priority_market_board
import aegis.priority_markets as m

def test_quote_age_and_freshness():
    now=datetime.now(timezone.utc)
    fresh=_quote("BTC/USD",50000,now,"Kraken","SPOT_CRYPTO",48000)
    assert fresh["fresh"]
    assert not fresh["execution_enabled"]
    stale=_quote("XAU/USD",3300,now-timedelta(hours=3),"Twelve Data","SPOT_GOLD")
    assert not stale["fresh"]

def test_gold_is_never_faked_when_key_absent(monkeypatch):
    monkeypatch.delenv("TWELVEDATA_API_KEY",raising=False)
    from aegis.live_lab import Candle
    now=int(datetime.now(timezone.utc).timestamp())
    monkeypatch.setattr(m,"fetch_ohlc",lambda pair:[Candle(ts=now-3600,open=1,high=2,low=1,close=2,volume=1)]*24+[Candle(ts=now-60,open=2,high=2,low=1,close=2,volume=1)])
    data=priority_market_board()
    gold=next(x for x in data["markets"] if x["symbol"]=="XAU/USD")
    assert gold["connected"] is False
    assert "price" not in gold
    assert data["live_money"] is False
