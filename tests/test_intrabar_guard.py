"""Fail-closed 15-minute shadow risk supervision; no position entry paths."""
from datetime import datetime,timedelta,timezone
import pytest

from aegis.live_lab import Candle
from aegis.intrabar_guard import (
    BAR_SECONDS,closed_fresh_quarters,intrabar_exit_reason,settle_intrabar_shadow
)
from aegis.paper_engine import RiskConfig


def make_quarters(now, prices=None):
    stamp=int(now.replace(minute=(now.minute//15)*15,second=0,microsecond=0).timestamp())
    prices=prices or [100,100,99,99]
    return [Candle(ts=stamp-(len(prices)-1-i)*900,open=p,high=p+1,
                   low=p-1,close=p,volume=100) for i,p in enumerate(prices)]


def test_closed_quarters_exclude_open_15min_bar():
    now=datetime(2026,10,8,15,20,tzinfo=timezone.utc)
    bars=make_quarters(now)
    closed=closed_fresh_quarters(bars,now)
    assert [b.ts for b in closed]==[b.ts for b in bars[:-1]]
    assert closed[-1].ts+BAR_SECONDS<=now.timestamp()


def test_stale_and_gap_quarters_fail_closed():
    now=datetime(2026,10,8,15,20,tzinfo=timezone.utc)
    with pytest.raises(ValueError,match="Stale"):
        closed_fresh_quarters(make_quarters(now-timedelta(minutes=15)),now)
    bars=make_quarters(now)
    shifted=Candle(ts=bars[-2].ts-900,open=bars[-2].open,
                   high=bars[-2].high,low=bars[-2].low,
                   close=bars[-2].close,volume=100)
    with pytest.raises(ValueError,match="discontinuous"):
        closed_fresh_quarters(bars[:-2]+[shifted,bars[-1]],now)


def test_gap_stop_is_conservatively_worse_than_stop():
    now=datetime(2026,10,8,15,20,tzinfo=timezone.utc)
    opened=now-timedelta(hours=2,minutes=30)
    c=Candle(ts=int(datetime(2026,10,8,15,tzinfo=timezone.utc).timestamp()),
             open=93,high=109,low=90,close=98,volume=100)
    p={"opened_at":opened,"stop_price":97,"target_price":105,"entry_price":100}
    price,why,at=intrabar_exit_reason(p,[c])
    assert price==93
    assert why=="STOP_AMBIGUOUS_BAR_15M"
    assert at==datetime(2026,10,8,15,15,tzinfo=timezone.utc)


def test_adverse_two_hour_exit_requires_persistent_losses():
    now=datetime(2026,10,8,15,20,tzinfo=timezone.utc)
    opened=datetime(2026,10,8,13,5,tzinfo=timezone.utc)
    p={"opened_at":opened,"stop_price":95,"target_price":115,"entry_price":102}
    bars=closed_fresh_quarters(make_quarters(now,[100,100,100,100]),now)
    decision=intrabar_exit_reason(p,bars)
    assert decision is not None
    assert decision[1]=="ADVERSE_TIME_STOP_2H"
    assert decision[2]==datetime(2026,10,8,15,15,tzinfo=timezone.utc)
    p_recent={**p,"opened_at":datetime(2026,10,8,14,20,tzinfo=timezone.utc)}
    assert intrabar_exit_reason(p_recent,bars) is None
    p_winner={**p,"entry_price":99}
    assert intrabar_exit_reason(p_winner,bars) is None


def test_partial_open_bar_never_forces_exit():
    now=datetime(2026,10,8,15,20,tzinfo=timezone.utc)
    open_pos={"opened_at":datetime(2026,10,8,15,5,tzinfo=timezone.utc),
              "entry_price":100,"stop_price":98,"target_price":104}
    closed=closed_fresh_quarters(make_quarters(now,[100,100,100,100]),now)
    assert intrabar_exit_reason(open_pos,closed) is None


def test_no_symbols_means_no_database_writes_or_live_order():
    class Cursor:
        def execute(self,*a):raise AssertionError("No database query expected")
    result=settle_intrabar_shadow(Cursor(),run_id="monitor:example",
       now=datetime(2026,10,8,15,20,tzinfo=timezone.utc),
       closed_by_symbol={},config=RiskConfig())
    assert result["quarter_exits"]==0
    assert result["quarter_mark_updates"]==0
