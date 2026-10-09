"""Synthetic fixtures test accounting and gates; never counted as market evidence."""
from datetime import datetime,timedelta,timezone
import pytest
from aegis import backtest_lab as bt
from aegis.live_lab import Candle
from aegis.horizon_selector import rank_forward_horizons
from aegis.stream_core import CompletedBar
from aegis.stream_paper import fill_decision


def flat_bars(n=150):
    return [Candle(1700000040+i*60,100,100.01,99.99,100,1) for i in range(n)]


def test_both_reversal_closes_then_enters_confirmed_opposite_next_open(monkeypatch):
    signals=[0]*69+[1]*11+[-1]*10+[0]*60
    monkeypatch.setattr(bt,"signed_strategy_signals",lambda *args:signals)
    r=bt.simulate_costed_backtest(flat_bars(),asset="BTC",strategy="EMA Cross",
                                interval="1min",direction="BOTH")
    assert [t["direction"] for t in r["trades"]]==["LONG","SHORT"]
    assert datetime.fromisoformat(r["trades"][1]["entry_ts"])>datetime.fromisoformat(r["trades"][0]["exit_ts"])
    assert r["stats"]["closed_net_pnl"]==pytest.approx(sum(t["net_pnl"] for t in r["trades"]),abs=.0001)


def test_paper_exits_flat_signal_even_if_transition_was_missed(monkeypatch):
    from aegis import stream_paper as sp
    bars=flat_bars()
    monkeypatch.setattr(sp,"signed_strategy_signals",lambda *args:[0]*len(bars))
    pos={"direction":"SHORT","opened_at":datetime.fromtimestamp(bars[0].ts,timezone.utc),
         "stop_price":110,"target_price":90,"entry_price":100,"qty":1}
    a={"strategy":"EMA Cross","direction":"SHORT","cash":100000,"halted":False,"max_drawdown":0}
    e=CompletedBar("BTC",1,bars[-1],100,bars[-1].ts+60)
    assert fill_decision(a,pos,bars,e)["reason"]=="SIGNAL_EXIT"
    assert fill_decision(a,pos,bars[-2:],e)["action"]=="MARK"


def forward():
    now=datetime(2026,10,9,tzinfo=timezone.utc)
    return {"agent_id":"candidate","strategy":"EMA Cross","symbol":"BTC","side":"SHORT",
            "interval_minutes":5,"trades":25,"net_pnl":500,"gross_gains":1000,"gross_losses":-500,
            "max_drawdown":.01,"first_trade":now-timedelta(days=10),"last_trade":now}


@pytest.mark.parametrize("patch",[{"max_drawdown":None},{"max_drawdown":float("nan")},
                                 {"max_drawdown":-.01},{"net_pnl":float("inf")},{"halted":True}])
def test_missing_corrupt_or_halted_forward_evidence_cannot_win(patch):
    r=rank_forward_horizons([{**forward(),**patch}],side="BOTH")
    assert r["forward_leader"] is None
    assert r["selected"] is None


def test_forward_only_profit_is_not_a_dual_evidence_selection():
    row=forward()
    r=rank_forward_horizons([row],side="BOTH")
    assert r["forward_leader"] is not None
    assert r["selected"] is None
    assert r["state"]=="AWAITING_MATCHED_OOS_EVIDENCE"
    receipt={"agent_id":"candidate","strategy":"EMA Cross","asset":"BTC","direction":"SHORT",
             "interval":"5min","historical_screen_passed":True,
             "evaluated_at":"2026-09-01T00:00:00+00:00",
             "source":"Kraken XBTUSD closed historical OHLC","history_hash":"0"*64,
             "holdout_days":20,"holdout":{"trades":25,"closed_net_pnl":50,"profit_factor":1.5,"max_drawdown_pct":1},
             "stress_holdout":{"closed_net_pnl":20,"max_drawdown_pct":2},"walkforward":{"folds_passed":3}}
    import hashlib,json
    receipt['evidence_hash']=hashlib.sha256(json.dumps(receipt,sort_keys=True,allow_nan=False).encode()).hexdigest()
    r=rank_forward_horizons([row],side="BOTH",historical_evidence=[receipt])
    assert r["selected"] is not None
    receipt["evaluated_at"]="2026-10-09T00:00:00+00:00"
    receipt.pop('evidence_hash')
    receipt['evidence_hash']=hashlib.sha256(json.dumps(receipt,sort_keys=True,allow_nan=False).encode()).hexdigest()
    assert rank_forward_horizons([row],side="BOTH",historical_evidence=[receipt])["selected"] is None


@pytest.mark.parametrize("capital",[0,-1,float("nan"),float("inf")])
def test_invalid_capital_rejected(capital):
    with pytest.raises(ValueError,match="equity"):
        bt.simulate_costed_backtest(flat_bars(),asset="BTC",strategy="EMA Cross",interval="1min",starting_equity=capital)


def test_directional_comparison_fetches_once_and_never_pools_directions(monkeypatch):
    calls=[]
    def loader(*args,**kwargs):
        calls.append(args)
        return flat_bars(200),'SYNTHETIC TEST FIXTURE'
    monkeypatch.setattr(bt,'load_backtest_bars',loader)
    r=bt.run_directional_comparison({'asset':'BTC','interval':'1min','bars':'200'})
    assert len(calls)==1
    assert [x['direction'] for x in r['reports']]==['LONG','SHORT']
    assert all(len(x['results'])==7 for x in r['reports'])
    assert not r['auto_promotion_enabled']


def test_real_receipt_builder_rejects_short_history_and_tampering():
    from aegis.historical_receipts import build_receipts
    from aegis.horizon_selector import valid_historical_receipt
    r=build_receipts('BTC',1,flat_bars(200),datetime(2026,10,9,tzinfo=timezone.utc))
    assert len(r)==4
    assert all(not x['historical_screen_passed'] for x in r)
    assert len({x['evidence_hash'] for x in r})==4
    r[0]['historical_screen_passed']=True
    assert not valid_historical_receipt(r[0])
    assert not build_receipts('ETH',1,flat_bars(200))


@pytest.mark.parametrize('minutes',[60,240,1440,10080])
def test_higher_horizon_snapshot_is_not_a_forward_fill(minutes):
    from aegis.stream_core import ClosedBarGate
    start=datetime(2026,10,8,tzinfo=timezone.utc)
    row={'symbol':'BTC/USD','interval':minutes,'interval_begin':start.isoformat(),
         'open':100,'high':101,'low':99,'close':100,'volume':1}
    gate=ClosedBarGate()
    assert gate.consume({'channel':'ohlc','type':'snapshot','data':[row]},start)==[]
    end=start+timedelta(minutes=minutes)
    event=gate.consume({'channel':'ohlc','type':'update','data':[{**row,'interval_begin':end.isoformat()}]},end+timedelta(seconds=1))
    assert len(event)==1
    assert event[0].candle.ts==start.timestamp()
    assert event[0].next_start==end.timestamp()
