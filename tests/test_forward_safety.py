"""Prevent stale fills, optimistic gap returns, and unsafe scheduler requests."""
from datetime import datetime,timedelta,timezone
import pytest

from aegis.live_lab import Candle
from aegis.forward_broker import _require_fresh_crypto_hourly
from aegis.shadow_broker import conservative_stop_fill, shadow_bar_exit
from api.paper_tick import validate_scheduled_at


def _candles(now):
    current=int(now.replace(minute=0,second=0,microsecond=0).timestamp())
    return [Candle(ts=current-3600*i,open=100,high=105,low=96,close=101,volume=1)
            for i in (2,1,0)]


def test_current_crypto_hour_allowed_without_lookahead():
    now=datetime(2026,10,8,11,5,tzinfo=timezone.utc)
    _require_fresh_crypto_hourly("BTC",_candles(now),now)


def test_stale_crypto_feed_blocks_forward_fills():
    now=datetime(2026,10,8,11,5,tzinfo=timezone.utc)
    candles=_candles(now-timedelta(hours=2))
    with pytest.raises(RuntimeError,match="stale"):
        _require_fresh_crypto_hourly("BTC",candles,now)


def test_gapped_crypto_feed_blocks_forward_fills():
    now=datetime(2026,10,8,11,5,tzinfo=timezone.utc)
    candles=_candles(now)
    candles[1]=Candle(ts=candles[1].ts-3600,open=100,high=101,low=99,close=100,volume=1)
    with pytest.raises(RuntimeError,match="discontinuous"):
        _require_fresh_crypto_hourly("ETH",candles,now)


def test_ambiguous_stop_gap_uses_worse_open_not_stop():
    start=datetime(2026,10,8,10,5,tzinfo=timezone.utc)
    next_hour=int(datetime(2026,10,8,11,tzinfo=timezone.utc).timestamp())
    p={"opened_at":start,"stop_price":97.0,"target_price":105.0}
    bar=Candle(ts=next_hour,open=93,high=107,low=90,close=100,volume=1)
    event=shadow_bar_exit(p,[bar])
    assert event[0]==93.0
    assert event[1]=="STOP_AMBIGUOUS_BAR"
    assert conservative_stop_fill(97,99)==97


def test_scheduler_time_validation_rejects_replay_and_future():
    now=datetime(2026,10,8,11,5,tzinfo=timezone.utc)
    assert validate_scheduled_at("2026-10-08T11:05:00Z",now=now)==now
    with pytest.raises(ValueError):
        validate_scheduled_at("2026-10-08T01:00:00Z",now=now)
    with pytest.raises(ValueError):
        validate_scheduled_at("2026-10-08T16:05:00Z",now=now)
    with pytest.raises(ValueError):
        validate_scheduled_at("2026-10-08T11:05:00",now=now)
