"""A micro stream disconnect must never become a phantom paper fill."""
import asyncio
from collections import deque
from datetime import datetime,timedelta,timezone

import pytest

from aegis.live_lab import Candle
from aegis.stream_worker import KrakenMicroWorker,enabled_symbols


def row(start,price=100):
    return {"symbol":"BTC/USD","interval":1,
            "interval_begin":start.isoformat().replace("+00:00","Z"),
            "open":price,"high":price+1,"low":price-1,
            "close":price,"volume":4}


def test_public_worker_only_accepts_allowlisted_pairs(monkeypatch):
    monkeypatch.setenv("AEGIS_STREAM_SYMBOLS","BTC")
    assert enabled_symbols()==["BTC"]
    monkeypatch.setenv("AEGIS_STREAM_SYMBOLS","BTC,ETH")
    assert enabled_symbols()==["BTC","ETH"]
    for bad in ("BTC,BTC","BTC,XAU","", "USD"):
        monkeypatch.setenv("AEGIS_STREAM_SYMBOLS",bad)
        with pytest.raises(ValueError):
            enabled_symbols()


def test_worker_requires_fresh_next_open_and_never_replays_duplicates():
    async def scenario():
        current=datetime(2026,10,8,15,0,0,tzinfo=timezone.utc)
        w=KrakenMicroWorker(["BTC"])
        closed=[Candle(ts=int((current-timedelta(minutes=i)).timestamp()),
                       open=100,high=101,low=99,close=100,volume=1)
                for i in range(160,0,-1)]
        w.history[("BTC",1)]=deque(closed,maxlen=720)
        observed=[]
        async def fake_persist(event,bars):
            observed.append(event.candle.ts)
            return {"processed":True,"entries":0,"exits":0,"marks":0}
        w._persist=fake_persist
        snap={"channel":"ohlc","type":"snapshot","data":[row(current)]}
        update={"channel":"ohlc","type":"update","data":[row(current+timedelta(minutes=1))]}
        assert await w.handle(snap,current+timedelta(seconds=2))==[]
        assert len(await w.handle(update,current+timedelta(minutes=1,seconds=2)))==1
        assert observed==[int(current.timestamp())]
        assert await w.handle(update,current+timedelta(minutes=1,seconds=4))==[]
        assert observed==[int(current.timestamp())]
    asyncio.run(scenario())


def test_worker_avoids_retroactive_fill_after_websocket_lag():
    async def scenario():
        now=datetime(2026,10,8,15,0,0,tzinfo=timezone.utc)
        w=KrakenMicroWorker(["BTC"])
        w.history[("BTC",1)]=deque([
            Candle(ts=int((now-timedelta(minutes=i)).timestamp()),
                   open=100,high=101,low=99,close=100,volume=1)
            for i in range(160,0,-1)],maxlen=720)
        async def forbid_db(*args):
            raise AssertionError("Do not record fills from stale opening prices")
        w._persist=forbid_db
        await w.handle({"channel":"ohlc","type":"snapshot","data":[row(now)]},now)
        r=await w.handle({"channel":"ohlc","type":"update","data":[row(
            now+timedelta(minutes=1))]},now+timedelta(minutes=1,seconds=25))
        assert r==[]
        assert w.stats["skipped_late"]==1
    asyncio.run(scenario())
