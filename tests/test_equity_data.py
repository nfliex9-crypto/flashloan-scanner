from datetime import datetime,timezone,timedelta
from aegis.equity_data import parse_snapshot,get_equity_quotes

def test_missing_credentials_never_invents_stock_prices(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY_ID",raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET_KEY",raising=False)
    payload=get_equity_quotes()
    assert payload["ok"] and not payload["connected"]
    assert payload["stocks"]==[]
    assert not payload["paper_execution_enabled"]

def test_iex_recent_print_is_not_consolidated_sip():
    now=datetime(2026,10,8,13,tzinfo=timezone.utc)
    data={"latestTrade":{"t":now.isoformat(),"p":502.5},
          "prevDailyBar":{"c":500}}
    result=parse_snapshot("SPY",data,now)
    assert result["fresh"] is True
    assert result["price"]==502.5
    assert result["feed"]=="IEX_BASIC"
    assert result["market_coverage"]=="IEX only, not consolidated SIP"
    assert result["change_from_prev_close"]==.005

def test_old_quote_is_stale_no_matter_if_price_is_positive():
    now=datetime(2026,10,8,13,tzinfo=timezone.utc)
    earlier=now-timedelta(hours=1)
    result=parse_snapshot("QQQ",{"latestTrade":{"t":earlier.isoformat(),"p":600}},now)
    assert result["status"]=="STALE_OR_MARKET_CLOSED"
    assert not result["fresh"]
    assert result["price"]==600
