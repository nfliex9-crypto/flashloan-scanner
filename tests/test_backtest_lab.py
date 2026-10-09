"""Source-backed historical backtesting is separate from forward positions."""
from datetime import datetime,timedelta,timezone

import pytest

from aegis.backtest_lab import (
    COST_MODES,STRATEGIES,load_backtest_bars,run_backtest,
    simulate_costed_backtest,validate_backtest_request,_parse_td,
)
from aegis.live_lab import Candle,strategy_positions


def samples(n=360,period=900):
    price=100.0
    bars=[]
    for i in range(n):
        # Alternating trends and several breakouts, no random test dependency.
        change=.009 if 55 <= (i%95) <= 65 else (.0009 if (i%95)<45 else -.003)
        price*=1+change
        bars.append(Candle(ts=1700000000+i*period,
                           open=price*.999,high=price*1.012,
                           low=price*.988,close=price,volume=100))
    return bars


def test_request_is_allowlisted_and_bounded():
    assert validate_backtest_request({"asset":"XAU","interval":"15min","bars":"650"})["bars"]==650
    assert validate_backtest_request({})["strategy"]=="EMA Cross"
    for bad in ({"bars":"10000"},{"strategy":"python code"},
                {"asset":"ETH"},{"interval":"30sec"},{"cost":"free"},
                {"execution":"live"},{"bars":"1.5"}):
        with pytest.raises(ValueError):
            validate_backtest_request(bad)


def test_all_strategies_work_with_closed_15m_series():
    candles=samples()
    for strategy in STRATEGIES:
        report=simulate_costed_backtest(candles,asset="BTC",
                                         strategy=strategy,interval="15min")
        assert report["stats"]["trades"]>=0
        assert report["stats"]["max_drawdown_pct"]>=0
        assert report["parameters"]["risk_per_trade_pct"]==.25
        assert report["parameters"]["max_position_notional_pct"]==20


def test_signals_cannot_fill_at_same_bar_that_generated_them():
    candles=samples()
    signal=strategy_positions([c.close for c in candles],"Channel Breakout")
    starts={candles[i].ts for i in range(1,len(candles))
            if signal[i]==1 and signal[i-1]==0}
    report=simulate_costed_backtest(candles,asset="BTC",
                         strategy="Channel Breakout",interval="15min")
    for trade in report["trades"]:
        actual=int(datetime.fromisoformat(trade["entry_ts"]).timestamp())
        assert actual not in starts
        assert (actual-900) in starts


def test_holdout_only_enters_at_or_after_requested_split():
    candles=samples()
    split=250
    report=simulate_costed_backtest(candles,asset="BTC",
                      strategy="Channel Breakout",interval="15min",entry_from=split)
    assert all(datetime.fromisoformat(t["entry_ts"]).timestamp()>=candles[split].ts
               for t in report["trades"])


def test_circuit_and_cost_model_never_authorize_live():
    candles=samples()
    base=simulate_costed_backtest(candles,asset="BTC",
                  strategy="Channel Breakout",interval="15min")
    stress=simulate_costed_backtest(candles,asset="BTC",
                  strategy="Channel Breakout",interval="15min",cost_multiplier=2)
    assert stress["parameters"]["fee_bps_each_side"]>base["parameters"]["fee_bps_each_side"]
    assert stress["parameters"]["slippage_bps_each_side"]>base["parameters"]["slippage_bps_each_side"]
    assert len(stress["equity_curve"])==len(candles)
    assert all(t["fees"]>=0 and t["slippage_cost"]>=0 for t in stress["trades"])


def test_complete_candles_only_and_source_timestamp():
    now=datetime(2026,10,8,12,18,tzinfo=timezone.utc)
    current=int(now.replace(minute=15,second=0,microsecond=0).timestamp())
    bars=[Candle(ts=current-i*900,open=100,high=101,low=99,close=100,volume=1)
          for i in range(130)]
    from aegis import backtest_lab
    old=backtest_lab.fetch_ohlc
    try:
        backtest_lab.fetch_ohlc=lambda *a,**kw:list(reversed(bars))
        filtered,source=load_backtest_bars("BTC","15min",130,now)
    finally:
        backtest_lab.fetch_ohlc=old
    assert len(filtered)==129
    assert filtered[-1].ts==current-900
    assert "Kraken" in source


def test_gold_bars_reject_inconsistent_data():
    with pytest.raises(ValueError,match="Inconsistent"):
        _parse_td([{"datetime":"2026-10-08 12:00:00","open":"4000",
                    "high":"3995","low":"3985","close":"4001"}])


def test_run_backtest_reports_holdout_warnings_without_real_orders(monkeypatch):
    from aegis import backtest_lab as bt
    candles=samples()
    monkeypatch.setattr(bt,"load_backtest_bars",
        lambda asset,interval,bars,now=None:(candles,"TEST SYNTHETIC FEED"))
    result=run_backtest({"asset":"BTC","strategy":"Channel Breakout",
                         "interval":"15min","bars":"400"})
    assert result["live_execution_enabled"] is False
    assert result["mode"]=="HISTORICAL_BACKTEST_ONLY"
    assert result["bars"]==len(candles)
    assert result["holdout"]["trades"]<=result["full"]["trades"]
    assert any("historical reconstruction" in x.lower() for x in result["warnings"])


def test_1m_and_5m_risk_model_allowed():
    from aegis.backtest_lab import INTERVALS
    assert INTERVALS["1min"]==60
    assert INTERVALS["5min"]==300
    assert validate_backtest_request({"interval":"1min"})["interval"]=="1min"


def test_backtest_rejects_hidden_missing_candles():
    candles=samples(n=150,period=60)
    broken=candles[:90]+candles[91:]
    with pytest.raises(ValueError,match="nonconsecutive"):
        simulate_costed_backtest(broken,asset="BTC",strategy="EMA Cross",interval="1min")


def test_backtest_rejects_corrupt_price_bars():
    candles=samples(n=150,period=300)
    bar=candles[55]
    candles[55]=Candle(ts=bar.ts,open=bar.open,high=bar.open-10,
                       low=bar.low,close=bar.close,volume=bar.volume)
    with pytest.raises(ValueError,match="Invalid historical OHLC"):
        simulate_costed_backtest(candles,asset="BTC",strategy="EMA Cross",interval="5min")


def test_gold_short_backtest_warnings_do_not_claim_binance_short_is_gold():
    from aegis import backtest_lab as bt
    from pytest import MonkeyPatch
    candles=samples(n=300,period=3600)
    with MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(bt,"load_backtest_bars",
            lambda asset,interval,bars,now=None:(candles,"UNIT TEST ONLY"))
        result=bt.run_backtest({"asset":"XAU","strategy":"EMA Cross",
            "interval":"1h","bars":"300","direction":"SHORT"})
    assert result["live_execution_enabled"] is False
    assert any("MT5 Demo" in w for w in result["warnings"])
    assert not any("Binance Spot Demo" in w for w in result["warnings"])


def test_compare_all_strategies_fetches_real_history_once(monkeypatch):
    from aegis import backtest_lab as bt
    calls=[]
    xs=samples(n=320,period=3600)
    def loader(asset,interval,bars,now=None):
        calls.append((asset,interval,bars))
        return xs,"UNIT TEST CLOSED HISTORICAL CANDLES"
    monkeypatch.setattr(bt,"load_backtest_bars",loader)
    report=bt.run_strategy_comparison(
        {"asset":"BTC","interval":"1h","direction":"BOTH","bars":"320"})
    assert len(calls)==1
    assert report["mode"]=="HISTORICAL_STRATEGY_COMPARISON"
    assert report["strategies_tested"]==7
    assert len({row["strategy"] for row in report["results"]})==7
    assert report["live_execution_enabled"] is False
    assert report["auto_promotion_enabled"] is False
    assert all(row["order_execution_authorized"] is False for row in report["results"])
    assert report["holdout_bars"]==96


def test_comparison_never_shortlists_without_real_holdout_evidence(monkeypatch):
    from aegis import backtest_lab as bt
    xs=samples(n=200,period=300)
    monkeypatch.setattr(bt,"load_backtest_bars",
        lambda asset,interval,bars,now=None:(xs,"UNIT TEST ONLY"))
    report=bt.run_strategy_comparison(
        {"asset":"BTC","interval":"5min","direction":"SHORT","bars":"200"})
    assert report["historical_shortlist"]==[]
    assert report["state"]=="INSUFFICIENT_HISTORICAL_EVIDENCE"
    assert all("held-out calendar window too short" in r["blockers"]
               for r in report["results"])
