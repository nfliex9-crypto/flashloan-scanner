"""Streaming tests use fabricated candles ONLY as fixtures; never persist fills."""
from datetime import datetime, timedelta, timezone

import pytest

from aegis.live_lab import Candle
from aegis.stream_core import (
    ALLOWED_MINUTES, ClosedBarGate, CompletedBar, fresh_closed_history,
    parse_kraken_bar,
)
from aegis.stream_paper import fill_decision, stream_agent_id, RISK


def kraken_row(start: datetime, *, minute: int = 1, price: float = 100) -> dict:
    return {"symbol":"BTC/USD","interval":minute,
            "interval_begin":start.isoformat().replace("+00:00","Z"),
            "open":price,"high":price+2,"low":price-2,
            "close":price+1,"volume":10}


def test_ws_snapshot_and_same_bar_cannot_trigger_a_trade():
    now=datetime(2026,10,8,15,0,8,tzinfo=timezone.utc)
    g=ClosedBarGate()
    r=kraken_row(now.replace(second=0,microsecond=0))
    assert g.consume({"channel":"ohlc","type":"snapshot","data":[r]},now)==[]
    assert g.consume({"channel":"ohlc","type":"update","data":[r]},now)==[]
    assert g.current[("BTC",1)].ts==int(now.replace(second=0).timestamp())


def test_exact_next_interval_emits_only_prior_completed_bar():
    now=datetime(2026,10,8,15,1,3,tzinfo=timezone.utc)
    start=now.replace(minute=0,second=0,microsecond=0)
    g=ClosedBarGate()
    g.consume({"channel":"ohlc","type":"snapshot","data":[kraken_row(start)]},
              start+timedelta(seconds=2))
    out=g.consume({"channel":"ohlc","type":"update","data":[
        kraken_row(start+timedelta(minutes=1),price=102)]},now)
    assert len(out)==1
    assert out[0].candle.ts==int(start.timestamp())
    assert out[0].next_start==int((start+timedelta(minutes=1)).timestamp())
    assert out[0].next_open==102


def test_missed_websocket_interval_cannot_create_a_fill():
    now=datetime(2026,10,8,15,4,1,tzinfo=timezone.utc)
    start=now.replace(minute=0,second=0)
    g=ClosedBarGate()
    g.consume({"channel":"ohlc","type":"snapshot","data":[kraken_row(start)]},now)
    r=g.consume({"channel":"ohlc","type":"update","data":[kraken_row(
        start+timedelta(minutes=4))]},now)
    assert not r
    assert g.gaps==1


def test_stale_and_invalid_ohlc_fail_closed():
    now=datetime(2026,10,8,15,3,2,tzinfo=timezone.utc)
    start=now.replace(minute=0,second=0)-timedelta(minutes=3)
    g=ClosedBarGate()
    g.consume({"channel":"ohlc","type":"snapshot","data":[kraken_row(start)]},now)
    assert not g.consume({"channel":"ohlc","type":"update","data":[
        kraken_row(start+timedelta(minutes=1))]},now)
    assert g.rejected>0
    invalid=kraken_row(start)
    invalid["low"]=200
    with pytest.raises(ValueError,match="Inconsistent"):
        parse_kraken_bar(invalid)


def make_history(n:int=160,minute:int=1,price:float=100)->list[Candle]:
    # Need current test OHLC close to be valid; only last bar triggers breakout.
    begin=1700000040
    begin-=begin%(minute*60)
    out=[]
    for i in range(n):
        close=price if i<n-1 else price+10
        out.append(Candle(ts=begin+i*minute*60,open=close,
            high=close+2,low=close-2,close=close,volume=1))
    return out


def test_causal_next_open_micro_entry_with_risk_limits():
    candles=make_history()
    closed=candles[-1]
    event=CompletedBar("BTC",1,closed,110.1,closed.ts+60)
    acc={"strategy":"Channel Breakout","cash":100000,
         "halted":False,"max_drawdown":0}
    result=fill_decision(acc,None,candles,event)
    assert result["action"]=="ENTER"
    assert result["at"].timestamp()==event.next_start
    assert result["qty"]*result["entry"]<=20000.01
    assert result["stop"]<result["entry"]<result["target"]


def test_micro_stop_gap_priority_and_no_live_order():
    bars=make_history()
    candle=Candle(ts=bars[-1].ts,open=91,high=111,low=85,close=100,volume=10)
    event=CompletedBar("BTC",1,candle,100,candle.ts+60)
    pos={"opened_at":datetime.fromtimestamp(candle.ts-60,timezone.utc),
         "stop_price":95,"target_price":110,"entry_price":100,"qty":2}
    acc={"strategy":"EMA Cross","cash":100000,
         "halted":False,"max_drawdown":0}
    decision=fill_decision(acc,pos,bars,event)
    assert decision["action"]=="EXIT"
    assert decision["raw_price"]==91
    assert decision["reason"]=="STOP_AMBIGUOUS_BAR"


def test_micro_account_drawdown_latches_new_entries():
    bars=make_history()
    event=CompletedBar("BTC",1,bars[-1],110,bars[-1].ts+60)
    acc={"strategy":"Channel Breakout","cash":99900,
         "halted":True,"max_drawdown":.052}
    assert fill_decision(acc,None,bars,event)["action"]=="WAIT"


def test_micro_gap_histories_block_new_position():
    xs=make_history()
    xs[-20]=Candle(ts=xs[-20].ts-50,open=100,high=102,low=98,
                    close=100,volume=1)
    assert not fresh_closed_history(xs,1)


def test_multiple_timeframes_and_unique_ids():
    assert ALLOWED_MINUTES==(1,5,15,60,240,1440,10080)
    aids={stream_agent_id("BTC",m,"EMA Cross") for m in ALLOWED_MINUTES}
    assert len(aids)==7
    assert all("micro-btc" in id for id in aids)
