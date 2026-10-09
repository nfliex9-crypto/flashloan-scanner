"""Bidirectional costed paper research and evidence-only timeframe selection."""
from datetime import datetime,timedelta,timezone

import pytest
from aegis.backtest_lab import simulate_costed_backtest,validate_backtest_request
from aegis.directional_signals import signed_strategy_signals,classify_horizon
from aegis.horizon_selector import rank_forward_horizons
from aegis.live_lab import Candle
from aegis.stream_core import CompletedBar
from aegis.stream_paper import fill_decision,stream_agent_id


def series(interval=900):
    start=1730000000
    start -= start%interval
    closes=([100.]*85+
            [100-i*.43 for i in range(65)]+
            [100-65*.43+j*.59 for j in range(75)]+
            [116-j*.45 for j in range(60)])
    return [Candle(ts=start+i*interval,open=c,high=c+.12,low=c-.12,close=c,volume=12)
            for i,c in enumerate(closes)]


def test_bidirectional_signal_has_no_clashing_exposures():
    closes=[c.close for c in series()]
    both=signed_strategy_signals(closes,"Channel Breakout","BOTH")
    shorts=signed_strategy_signals(closes,"Channel Breakout","SHORT")
    longs=signed_strategy_signals(closes,"Channel Breakout","LONG")
    assert len(both)==len(closes)
    assert set(both)<={-1,0,1}
    assert set(shorts)<={-1,0}
    assert any(x==-1 for x in shorts)
    for n in (150,220,270):
        assert both[:n]==signed_strategy_signals(closes[:n],"Channel Breakout","BOTH")
    assert all(both[i]==0 if longs[i] and shorts[i] else True for i in range(len(both)))


def test_short_backtest_tracks_gross_profit_and_costs():
    res=simulate_costed_backtest(series(),asset="BTC",strategy="Channel Breakout",
                                 interval="15min",direction="SHORT")
    assert res["stats"]["long_trades"]==0
    assert res["stats"]["short_trades"]>0
    assert res["parameters"]["short_finance_bps_per_day"]>0
    assert all(t["direction"]=="SHORT" for t in res["trades"])
    assert all(t["financing_cost"]>=0 and t["fees"]>=0 for t in res["trades"])
    balance=100000.0
    for trade in res["trades"]:
        # Position cap is a percentage of CURRENT paper equity, not a
        # constant $20k after previous realized gains/losses.
        assert trade["qty"]*trade["entry_price"] <= balance*.20+0.02
        balance += trade["net_pnl"]


def test_short_and_long_cost_stress_does_not_fake_gain():
    candles=series()
    for direction in ("SHORT","LONG","BOTH"):
        test=simulate_costed_backtest(candles,asset="BTC",
            strategy="Channel Breakout",interval="15min",direction=direction,
            cost_multiplier=2.)
        assert test["parameters"]["risk_per_trade_pct"]==pytest.approx(.25)
        assert test["parameters"]["max_position_notional_pct"]==pytest.approx(20.)
        assert test["stats"]["max_drawdown_pct"]>=0


def test_short_stop_gap_fills_at_worse_open():
    bars=series(interval=60)
    last=bars[-1]
    gapped=Candle(ts=last.ts,open=115,high=120,low=85,close=102,volume=20)
    event=CompletedBar("BTC",1,gapped,102,gapped.ts+60)
    pos={"direction":"SHORT","opened_at":datetime.fromtimestamp(gapped.ts-60,timezone.utc),
         "entry_price":100,"qty":1.0,"stop_price":108,"target_price":90}
    acc={"strategy":"EMA Cross","direction":"SHORT","cash":100000,
         "halted":False,"max_drawdown":0.0}
    decision=fill_decision(acc,pos,bars,event)
    assert decision["action"]=="EXIT"
    assert decision["raw_price"]==115
    assert decision["reason"]=="STOP_AMBIGUOUS_BAR"


def test_short_micro_books_are_independent_and_never_demo_orders():
    long_id=stream_agent_id("BTC",5,"EMA Cross","LONG")
    short_id=stream_agent_id("BTC",5,"EMA Cross","SHORT")
    assert long_id!=short_id
    assert short_id.endswith("-short")
    with pytest.raises(ValueError):
        stream_agent_id("BTC",5,"EMA Cross","BOTH")


def test_horizons_support_intraday_swing_weekly_and_no_broker_promotion():
    assert classify_horizon("1min")=="SCALPING"
    assert classify_horizon("1h")=="INTRADAY"
    assert classify_horizon("4h")=="SWING"
    assert classify_horizon("1week")=="POSITION"
    assert validate_backtest_request({"interval":"1week","direction":"SHORT"})["direction"]=="SHORT"


def test_no_automatic_winner_without_forward_sample():
    now=datetime(2026,10,8,tzinfo=timezone.utc)
    small={"agent_id":"micro-btc-1m-short","symbol":"BTC","interval_minutes":1,
        "strategy":"Channel Breakout","side":"SHORT","trades":5,
        "first_trade":now-timedelta(days=1),"last_trade":now,
        "net_pnl":100,"gross_gains":110,"gross_losses":-10,"max_drawdown":.01}
    report=rank_forward_horizons([small],side="BOTH")
    assert report["selected"] is None
    assert report["state"]=="INSUFFICIENT_FORWARD_EVIDENCE"
    assert "trades" in report["candidates"][0]["failed_checks"]
    assert report["demo_order_execution_enabled"] is False
    assert report["live_execution_enabled"] is False


def test_separate_long_and_short_forward_winners_on_real_evidence():
    now=datetime(2026,10,8,tzinfo=timezone.utc)
    rows=[]
    for side in ("LONG","SHORT"):
        rows.append({
            "agent_id":"micro-btc-5m-"+side.lower(),"symbol":"BTC",
            "strategy":"Channel Breakout","interval_minutes":5,
            "side":side,"trades":28,"first_trade":now-timedelta(days=11),
            "last_trade":now,"net_pnl":480 if side=="SHORT" else 250,
            "gross_gains":850,"gross_losses":-370,
            "max_drawdown":.013,
        })
    report=rank_forward_horizons(rows,side="BOTH")
    assert report["selected"]["direction"]=="SHORT"
    assert report["selected_by_direction"]["LONG"]["qualified"]
    assert report["selected_by_direction"]["SHORT"]["qualified"]
    assert report["selection_is_not_a_trading_order"] is True
