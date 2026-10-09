"""Three independent chronological segments of historical research, not forward fills."""
from datetime import datetime, timezone
import pytest

from aegis.live_lab import Candle
from aegis.walkforward_lab import verify_walkforward,run_walkforward


def candles(n=420,period=900):
    out=[]
    price=100.0
    for i in range(n):
        delta=.002 if i%90<45 else -.0025
        opening=price
        price=max(1.0,opening*(1+delta))
        out.append(Candle(ts=1700000100+i*period,open=opening,
            high=max(opening,price)*1.004,low=min(opening,price)*.996,
            close=price,volume=3))
    return out


def test_three_folds_sequential_and_never_enable_any_broker_execution():
    xs=candles()
    for direction in ("LONG","SHORT","BOTH"):
        report=verify_walkforward(xs,asset="BTC",strategy="EMA Cross",
                    interval="15min",direction=direction)
        assert report["mode"]=="HISTORICAL_WALKFORWARD_ONLY"
        assert report["direction"]==direction
        assert len(report["folds"])==3
        assert report["live_execution_enabled"] is False
        assert report["demo_order_execution_enabled"] is False
        assert report["auto_promotion_enabled"] is False
        assert report["closed_trades"]==sum(f["base"]["trades"] for f in report["folds"])
        for a,b in zip(report["folds"],report["folds"][1:]):
            assert a["end"]==b["start"]
        assert all(f["stress_closed_net_pnl"] is not None for f in report["folds"])


def test_no_future_candles_enter_earlier_fold(monkeypatch):
    from aegis import walkforward_lab as lab
    xs=candles(420)
    seen=[]
    original=lab.simulate_costed_backtest
    def instrument(prefix,**kwargs):
        seen.append((len(prefix),kwargs["entry_from"],kwargs["cost_multiplier"]))
        return original(prefix,**kwargs)
    monkeypatch.setattr(lab,"simulate_costed_backtest",instrument)
    lab.verify_walkforward(xs,asset="BTC",strategy="EMA Cross",
                   interval="15min",direction="LONG")
    assert len(seen)==6
    assert [x[0] for x in seen[::2]]==[252,336,420]
    assert [x[1] for x in seen[::2]]==[168,252,336]
    assert all(seen[i][2]==1.0 and seen[i+1][2]==2.0 for i in (0,2,4))


def test_open_mark_to_market_must_not_pass_closed_fill_gate(monkeypatch):
    from aegis import walkforward_lab as lab
    def fake(prefix,**kw):
        return {"stats":{"trades":0,"net_pnl":4000,"profit_factor":99,
                "max_drawdown_pct":0.0},
                "trades":[]}
    monkeypatch.setattr(lab,"simulate_costed_backtest",fake)
    r=lab.verify_walkforward(candles(),asset="BTC",
                  strategy="EMA Cross",interval="15min",direction="BOTH")
    assert r["folds_passed"]==0
    assert r["state"]=="INSUFFICIENT_OR_INCONSISTENT_EVIDENCE"
    assert all(f["base_closed_net_pnl"]==0 for f in r["folds"])


def test_historical_window_under_180_candles_rejected():
    with pytest.raises(ValueError,match="180"):
        verify_walkforward(candles(170),asset="BTC",
            strategy="EMA Cross",interval="15min",direction="LONG")


def test_api_runner_uses_source_bars_and_cost_setting(monkeypatch):
    from aegis import walkforward_lab as lab
    monkeypatch.setattr(lab,"load_backtest_bars",
        lambda asset,interval,bars,now=None:(candles(),"UNIT TEST DATA ONLY"))
    r=run_walkforward({"asset":"BTC","strategy":"EMA Cross",
               "interval":"15min","direction":"SHORT","bars":"400",
               "cost":"stress"})
    assert r["source"]=="UNIT TEST DATA ONLY"
    assert r["cost_mode"]=="stress"
    assert r["direction"]=="SHORT"
    assert r["live_execution_enabled"] is False
    assert r["auto_promotion_enabled"] is False
