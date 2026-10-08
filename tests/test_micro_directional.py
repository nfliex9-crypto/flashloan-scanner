"""Micro Paper short positions use costed, direction-aware virtual fills only."""
from datetime import datetime,timezone
from aegis.live_lab import Candle
from aegis.stream_core import CompletedBar
from aegis.stream_paper import (
    fill_decision,stream_agent_id,MICRO_DIRECTIONS,SHORT_FINANCE_BPS_PER_DAY,
    _model_short_financing,
)
from aegis.horizon_selector import rank_forward_horizons


def falling_history(n=145,minutes=1):
    base=1700000000//(60*minutes)*(60*minutes)
    return [Candle(ts=base+i*minutes*60,open=150-0.1*i,
                   high=150-0.1*i+.01,low=150-0.1*i-.01,
                   close=150-0.1*i,volume=1) for i in range(n)]


def test_distinct_long_and_short_virtual_accounts():
    long=stream_agent_id("BTC",1,"Channel Breakout")
    short=stream_agent_id("BTC",1,"Channel Breakout","SHORT")
    assert long!=short and short.endswith("-short")
    assert MICRO_DIRECTIONS==("LONG","SHORT")


def test_short_signal_and_risk_sizing_use_real_price_not_inverse():
    xs=falling_history()
    # Flat then rapid downside breakout at final candle.
    base=xs[0].ts
    closes=[130.]*144+[120.]
    xs=[Candle(ts=base+i*60,open=p,high=p+.02,low=p-.02,close=p,volume=1)
        for i,p in enumerate(closes)]
    event=CompletedBar("BTC",1,xs[-1],119.8,xs[-1].ts+60)
    acc={"strategy":"Channel Breakout","direction":"SHORT",
         "cash":100000,"max_drawdown":0,"halted":False}
    outcome=fill_decision(acc,None,xs,event)
    assert outcome["action"]=="ENTER"
    assert outcome["direction"]=="SHORT"
    assert outcome["stop"]>outcome["entry"]>outcome["target"]
    assert outcome["qty"]*outcome["entry"]<=20000.01
    assert outcome["entry_fee"]>0 and outcome["entry_slippage"]>=0


def test_short_stop_gap_prioritizes_worse_open():
    x=falling_history()
    bar=Candle(ts=x[-1].ts,open=110,high=112,low=91,close=102,volume=1)
    evt=CompletedBar("BTC",1,bar,104,bar.ts+60)
    pos={"direction":"SHORT","opened_at":datetime.fromtimestamp(bar.ts-60,timezone.utc),
         "entry_price":100,"qty":1,"stop_price":103,"target_price":95}
    account={"strategy":"Channel Breakout","direction":"SHORT",
             "cash":99990,"max_drawdown":0,"halted":False}
    d=fill_decision(account,pos,x,evt)
    assert d["action"]=="EXIT"
    assert d["raw_price"]==110
    assert d["reason"]=="STOP_AMBIGUOUS_BAR"


def test_short_financing_not_applied_to_long():
    now=datetime(2026,10,8,12,tzinfo=timezone.utc)
    short={"direction":"SHORT","opened_at":now,
           "entry_price":100,"qty":2}
    long={**short,"direction":"LONG"}
    assert _model_short_financing(short,int(now.timestamp())+86400)==.04
    assert _model_short_financing(long,int(now.timestamp())+86400)==0
    assert SHORT_FINANCE_BPS_PER_DAY==2.0


def test_forward_research_selector_separates_long_short_evidence():
    now=datetime(2026,10,8,12,tzinfo=timezone.utc)
    from datetime import timedelta
    a={"symbol":"BTC","interval_minutes":5,"side":"SHORT",
       "trades":29,"net_pnl":650,"gross_gains":1100,
       "gross_losses":-450,"max_drawdown":.01,
       "first_trade":now-timedelta(days=45),"last_trade":now}
    r=rank_forward_horizons([a],side="BOTH")
    assert r["selected"] is not None
    assert r["selected"]["direction"]=="SHORT"
    assert r["selected_by_direction"]["SHORT"]["interval"]=="5min"
    assert r["selected_by_direction"]["LONG"] is None
    assert not r["demo_order_execution_enabled"]
