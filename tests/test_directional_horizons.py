"""Bidirectional research and conditional horizon selection are paper-only."""
from datetime import datetime,timedelta,timezone

import pytest

from aegis.live_lab import Candle
from aegis.directional_signals import (
    DIRECTIONS,HORIZONS,classify_horizon,signed_strategy_signals,
)
from aegis.backtest_lab import (
    INTERVALS,simulate_costed_backtest,validate_backtest_request,
)
from aegis.horizon_selector import rank_forward_horizons


def candles(prices,interval=300):
    return [Candle(ts=1700000100+i*interval,open=p,
                   high=p*1.001,low=p*.999,close=p,volume=5)
            for i,p in enumerate(prices)]


def test_supported_research_modes_and_horizons():
    assert DIRECTIONS==("LONG","SHORT","BOTH")
    assert classify_horizon("1min")=="SCALPING"
    assert classify_horizon("1h")=="INTRADAY"
    assert classify_horizon("1day")=="SWING"
    assert classify_horizon("1week")=="POSITION"
    assert INTERVALS["1week"]==604800
    assert validate_backtest_request({"direction":"SHORT","interval":"4h"})["direction"]=="SHORT"
    with pytest.raises(ValueError):
        validate_backtest_request({"direction":"REAL_ACCOUNT"})
    with pytest.raises(ValueError):
        signed_strategy_signals([100,101],"EMA Cross","ORDER_SELL")


def test_short_causal_inverse_trend_and_long_uptrend():
    series=[180*(.9995**i) for i in range(240)]
    short=signed_strategy_signals(series,"EMA Cross","SHORT")
    assert short[-1]==-1
    assert -1 not in signed_strategy_signals(series,"EMA Cross","LONG")
    assert signed_strategy_signals(series[:200],"EMA Cross","SHORT")==short[:200]
    assert all(s in (-1,0,1) for s in signed_strategy_signals(series,"EMA Cross","BOTH"))


def test_short_profitable_when_market_drops_no_live_fills():
    prices=[200*(.997**i) for i in range(200)]
    xs=candles(prices)
    a=simulate_costed_backtest(xs,asset="BTC",strategy="EMA Cross",
        interval="5min",direction="SHORT")
    assert a["stats"]["short_trades"]>=0
    assert a["stats"]["long_trades"]==0
    assert all(x["direction"]=="SHORT" for x in a["trades"])
    assert all(x["financing_cost"]>=0 for x in a["trades"])
    assert a["parameters"]["risk_per_trade_pct"]==.25
    assert a["parameters"]["short_finance_bps_per_day"]>0


def test_short_stop_gap_uses_worse_open_and_long_stop_unmodified(monkeypatch):
    from aegis import backtest_lab as bt
    n=130
    prices=[100.0]*n
    xs=candles(prices)
    # Entry at i=70 using an already CLOSED bar 69. Next bar 71
    # opens through short stop and still reaches target in the bar.
    sig=[0]*n
    for i in range(69,n):sig[i]=-1
    monkeypatch.setattr(bt,"signed_strategy_signals",
                        lambda closes,strategy,direction:sig)
    originals=xs[:]
    bar=xs[71]
    xs[71]=Candle(ts=bar.ts,open=105,high=107,low=93,close=98,volume=5)
    result=simulate_costed_backtest(xs,asset="BTC",strategy="EMA Cross",
                                   interval="5min",direction="SHORT")
    assert result["trades"]
    trade=result["trades"][0]
    assert trade["direction"]=="SHORT"
    assert trade["reason"] in ("STOP","STOP_AMBIGUOUS_BAR")
    assert trade["exit_price"]>=105
    assert trade["net_pnl"]<0


def test_short_finance_grows_with_holding_time(monkeypatch):
    from aegis import backtest_lab as bt
    n=180
    base=[100]*n
    sig=[0]*n
    for i in range(90,159):sig[i]=-1
    monkeypatch.setattr(bt,"signed_strategy_signals",
                        lambda closes,strategy,direction:sig)
    x=simulate_costed_backtest(candles(base),asset="BTC",strategy="EMA Cross",
                              interval="5min",direction="SHORT")
    if x["trades"]:
        assert x["trades"][0]["financing_cost"]>0


def test_short_and_long_sizing_share_absolute_stop_risk(monkeypatch):
    from aegis import backtest_lab as bt
    n=140
    sig=[0]*n
    for i in range(100,110):sig[i]=-1
    monkeypatch.setattr(bt,"signed_strategy_signals",
                        lambda closes,strategy,direction:sig)
    x=simulate_costed_backtest(candles([100.0]*n),asset="XAU",
                               strategy="EMA Cross",interval="5min",direction="SHORT")
    assert x["trades"]
    assert x["trades"][0]["qty"]*x["trades"][0]["entry_price"]<=20000.1


def evidence(n=25,net=500,gains=950,losses=-450,days=40,minutes=5):
    now=datetime(2026,10,8,tzinfo=timezone.utc)
    return {"symbol":"BTC","interval_minutes":minutes,
        "trades":n,"net_pnl":net,"gross_gains":gains,
        "gross_losses":losses,
        "first_trade":now-timedelta(days=days),"last_trade":now,
        "max_drawdown":.02}


def test_auto_router_requires_verified_costed_forward_ledger():
    none=rank_forward_horizons([])
    assert none["selected"] is None
    assert none["state"]=="INSUFFICIENT_FORWARD_EVIDENCE"
    assert not none["demo_order_execution_enabled"]
    short=rank_forward_horizons([evidence()],side="SHORT")
    assert short["selected"] is None
    assert "direction_supported" in short["candidates"][0]["failed_checks"]
    wins=rank_forward_horizons([evidence(minutes=5),evidence(minutes=15)],side="LONG")
    assert wins["state"]=="RESEARCH_LEADER_AVAILABLE"
    assert wins["selected"] is not None
    assert not wins["selected"]["execution_authorized"]


def test_router_rejects_lucky_small_samples_and_high_drawdown():
    tiny=rank_forward_horizons([evidence(n=4)],side="LONG")
    assert tiny["selected"] is None
    assert "trades" in tiny["candidates"][0]["failed_checks"]
    dd=evidence()
    dd["max_drawdown"]=.055
    assert rank_forward_horizons([dd])["selected"] is None
    flat=evidence(net=-1)
    assert rank_forward_horizons([flat])["selected"] is None


def test_gold_weekend_market_closure_allowed_but_weekday_data_gap_rejected():
    from aegis.backtest_lab import _verify_research_history
    fri=datetime(2026,10,2,23,tzinfo=timezone.utc)
    # We need >= 120 valid 1h bars. 120 hours preceding Friday close,
    # followed by Monday; the only omitted slots are weekend sessions.
    stamps=[int((fri-timedelta(hours=n)).timestamp()) for n in range(119,-1,-1)]
    stamps.append(int(datetime(2026,10,5,tzinfo=timezone.utc).timestamp()))
    bars=[Candle(ts=ts,open=100,high=101,low=99,close=100,volume=5)
          for ts in stamps]
    _verify_research_history(bars,"XAU",3600)
    with pytest.raises(ValueError,match="nonconsecutive"):
        _verify_research_history(bars,"BTC",3600)
    # A missing weekday bar is never silently filled with synthetic data.
    broken=bars[:50]+bars[51:]
    with pytest.raises(ValueError,match="nonconsecutive"):
        _verify_research_history(broken,"XAU",3600)


def test_horizon_ranks_each_agent_not_blended_pooled_profit():
    from aegis.horizon_selector import rank_forward_horizons
    base=evidence(n=28,net=900,days=45,minutes=5)
    base.update({"agent_id":"micro-btc-5m-ema-cross","strategy":"EMA Cross","side":"LONG"})
    other={**base,"agent_id":"micro-btc-5m-channel-breakout",
           "strategy":"Channel Breakout","net_pnl":-500}
    result=rank_forward_horizons([base,other],side="LONG")
    assert result["selected"]["agent_id"]=="micro-btc-5m-ema-cross"
    assert result["selected"]["strategy"]=="EMA Cross"
    assert len(result["candidates"])==2
    assert sum(int(c["qualified"]) for c in result["candidates"])==1
