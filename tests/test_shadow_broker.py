from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest

from aegis.live_lab import Candle
from aegis.paper_engine import RiskConfig
from aegis.shadow_broker import shadow_entry_price, shadow_exit_result, shadow_bar_exit, shadow_id


def test_costed_long_open_and_close_include_both_fees_and_slippage():
    cfg=RiskConfig()
    raw=100.0
    entry=shadow_entry_price(raw,cfg)
    pos={"qty":10.0,"entry_price":entry,"entry_fee":0.30,"entry_slippage":(entry-raw)*10,
         "stop_price":98.0}
    result=shadow_exit_result(pos,102.0,cfg)
    assert entry>raw
    assert result["exit_price"]<102
    assert result["slippage_cost"]>0
    assert result["net_pnl"]==pytest.approx(result["gross"]-pos["entry_fee"]-result["exit_fee"])
    assert result["net_pnl"]<20.0


def test_stop_ambiguous_bar_assumes_stop_not_target():
    start=datetime(2026,10,8,12,5,tzinfo=timezone.utc)
    p={"opened_at":start,"stop_price":97.0,"target_price":105.0}
    ts=int((start+timedelta(hours=1)).replace(minute=0).timestamp())
    before=Candle(ts=ts-3600,open=100,high=108,low=95,close=100,volume=1)
    after=Candle(ts=ts,open=100,high=106,low=96,close=102,volume=1)
    event=shadow_bar_exit(p,[before,after])
    assert event[0]==97.0
    assert event[1]=="STOP_AMBIGUOUS_BAR"
    assert event[2]==datetime.fromtimestamp(ts,tz=timezone.utc)+timedelta(hours=1)


def test_shadow_never_reads_pre_entry_ohlc():
    start=datetime(2026,10,8,12,5,tzinfo=timezone.utc)
    p={"opened_at":start,"stop_price":97.0,"target_price":105.0}
    candle=Candle(ts=int(datetime(2026,10,8,12,tzinfo=timezone.utc).timestamp()),
                  open=100,high=200,low=1,close=100,volume=1)
    assert shadow_bar_exit(p,[candle]) is None


def test_shadow_id_stable_across_retries():
    assert shadow_id("position","btc-trend","2026-10-08") == shadow_id("position","btc-trend","2026-10-08")
